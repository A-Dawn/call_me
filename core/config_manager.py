import asyncio
import copy
import os
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import tomlkit

from ..config import PLUGIN_CONFIG_SCHEMA
from .asr_adapter import SherpaASR


SENSITIVE_FIELDS = {
    "doubao_app_key",
    "doubao_access_key",
}


class ConfigManager:
    def __init__(self):
        self.plugin_dir = Path(__file__).resolve().parent.parent
        self.config_path = self.plugin_dir / "config.toml"
        self.backup_dir = self.plugin_dir / "config_backups"
        self._apply_lock = asyncio.Lock()

    @property
    def apply_lock(self) -> asyncio.Lock:
        return self._apply_lock

    def _schema_defaults(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {}
        for section, fields in PLUGIN_CONFIG_SCHEMA.items():
            if not isinstance(fields, dict):
                continue
            defaults[section] = {}
            for key, field in fields.items():
                defaults[section][key] = copy.deepcopy(field.default)
        return defaults

    def load_raw_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            import tomllib

            with self.config_path.open("rb") as f:
                data = tomllib.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def merge_with_defaults(self, value: dict[str, Any] | None) -> dict[str, Any]:
        merged = self._schema_defaults()
        incoming = value if isinstance(value, dict) else {}

        for section, section_data in incoming.items():
            if not isinstance(section_data, dict):
                continue
            if section not in merged:
                merged[section] = {}
            for key, v in section_data.items():
                merged[section][key] = copy.deepcopy(v)

        return merged

    def _coerce_bool(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "on"}:
                return True
            if v in {"0", "false", "no", "off"}:
                return False
        return default

    def normalize(self, value: dict[str, Any] | None) -> dict[str, Any]:
        cfg = self.merge_with_defaults(value)

        for section, fields in PLUGIN_CONFIG_SCHEMA.items():
            section_data = cfg.get(section)
            if not isinstance(section_data, dict):
                cfg[section] = {}
                section_data = cfg[section]

            if not isinstance(fields, dict):
                continue

            for key, field in fields.items():
                current = section_data.get(key, copy.deepcopy(field.default))
                try:
                    if field.type is bool:
                        section_data[key] = self._coerce_bool(current, bool(field.default))
                    elif field.type is int:
                        section_data[key] = int(current)
                    elif field.type is float:
                        section_data[key] = float(current)
                    elif field.type is list:
                        section_data[key] = current if isinstance(current, list) else copy.deepcopy(field.default)
                    elif field.type is dict:
                        section_data[key] = current if isinstance(current, dict) else copy.deepcopy(field.default)
                    elif field.type is str:
                        section_data[key] = str(current)
                    else:
                        section_data[key] = copy.deepcopy(current)
                except Exception:
                    section_data[key] = copy.deepcopy(field.default)

        return cfg

    def get_current_config(self) -> dict[str, Any]:
        return self.normalize(self.load_raw_config())

    def mask_sensitive(self, cfg: dict[str, Any]) -> dict[str, Any]:
        masked = copy.deepcopy(cfg)
        tts = masked.get("tts")
        if isinstance(tts, dict):
            for key in SENSITIVE_FIELDS:
                raw = str(tts.get(key, "") or "")
                if not raw:
                    continue
                if len(raw) <= 6:
                    tts[key] = "***"
                else:
                    tts[key] = f"{raw[:3]}***{raw[-2:]}"
        return masked

    def _add_issue(self, bucket: list[dict[str, str]], code: str, field: str, message: str):
        bucket.append({"code": code, "field": field, "message": message})

    @staticmethod
    def _resolve_cosyvoice_endpoint(tts: dict[str, Any]) -> str:
        mode = str(tts.get("cosyvoice_mode", "cross_lingual") or "cross_lingual").strip().lower()
        endpoint = "/inference_zero_shot" if mode == "zero_shot" else "/inference_cross_lingual"
        return str(tts.get("api_url", "")).rstrip("/") + endpoint

    def validate_config(self, value: dict[str, Any] | None) -> dict[str, Any]:
        cfg = self.normalize(value)
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        fix_hints: list[dict[str, str]] = []

        tts = cfg.get("tts", {})
        asr = cfg.get("asr", {})
        sherpa = cfg.get("sherpa", {})

        tts_type = str(tts.get("type", "")).strip()
        tts_url = str(tts.get("api_url", "")).strip()

        if tts_type not in {"sovits", "doubao_ws", "cosyvoice_http", "mock"}:
            self._add_issue(errors, "INVALID_VALUE", "tts.type", "tts.type 必须为 sovits / doubao_ws / cosyvoice_http / mock")

        if tts_type == "sovits":
            if not tts_url:
                self._add_issue(errors, "REQUIRED", "tts.api_url", "SoVITS 模式必须填写 tts.api_url")
            ref_audio = str(tts.get("ref_audio_path", "") or "").strip()
            if ref_audio and not Path(ref_audio).exists():
                self._add_issue(warnings, "PATH_NOT_FOUND", "tts.ref_audio_path", "参考音频路径不存在，可能会导致合成失败")

        if tts_type == "doubao_ws":
            required = [
                "api_url",
                "doubao_app_key",
                "doubao_access_key",
                "doubao_resource_id",
                "doubao_voice_type",
            ]
            for key in required:
                if not str(tts.get(key, "") or "").strip():
                    self._add_issue(errors, "REQUIRED", f"tts.{key}", f"豆包模式必须填写 {key}")

            if str(tts.get("doubao_audio_format", "pcm")).strip().lower() != "pcm":
                self._add_issue(errors, "INVALID_VALUE", "tts.doubao_audio_format", "豆包模式当前仅支持 pcm")

            parsed = urlparse(tts_url)
            if parsed.scheme not in {"ws", "wss"}:
                self._add_issue(errors, "INVALID_URL", "tts.api_url", "豆包 API URL 必须使用 ws/wss 协议")

        if tts_type == "cosyvoice_http":
            if not tts_url:
                self._add_issue(errors, "REQUIRED", "tts.api_url", "CosyVoice 模式必须填写 tts.api_url")
            parsed = urlparse(tts_url)
            if tts_url and parsed.scheme not in {"http", "https"}:
                self._add_issue(errors, "INVALID_URL", "tts.api_url", "CosyVoice API URL 必须使用 http/https 协议")

            cosy_mode = str(tts.get("cosyvoice_mode", "cross_lingual") or "cross_lingual").strip().lower()
            if cosy_mode not in {"cross_lingual", "zero_shot"}:
                self._add_issue(
                    errors,
                    "INVALID_VALUE",
                    "tts.cosyvoice_mode",
                    "CosyVoice 模式必须为 cross_lingual / zero_shot",
                )

            ref_audio = str(tts.get("cosyvoice_ref_audio_path", "") or "").strip()
            if not ref_audio:
                self._add_issue(errors, "REQUIRED", "tts.cosyvoice_ref_audio_path", "CosyVoice 模式必须填写 cosyvoice_ref_audio_path")
            elif not Path(ref_audio).exists():
                self._add_issue(errors, "PATH_NOT_FOUND", "tts.cosyvoice_ref_audio_path", f"参考音频路径不存在: {ref_audio}")

            if cosy_mode == "zero_shot":
                ref_text = str(tts.get("cosyvoice_ref_text", "") or "").strip()
                if not ref_text:
                    self._add_issue(errors, "REQUIRED", "tts.cosyvoice_ref_text", "zero_shot 模式必须填写 cosyvoice_ref_text")

        asr_type = str(asr.get("type", "")).strip()
        if asr_type not in {"sherpa", "funasr", "openai", "mock"}:
            self._add_issue(errors, "INVALID_VALUE", "asr.type", "asr.type 必须为 sherpa / funasr / openai / mock")

        if asr_type == "sherpa":
            model_kind = str(sherpa.get("model_kind", "zipformer2_ctc")).strip().lower()
            if model_kind not in {"zipformer2_ctc", "ctc", "transducer"}:
                self._add_issue(errors, "INVALID_VALUE", "sherpa.model_kind", "sherpa.model_kind 必须为 zipformer2_ctc 或 transducer")
            if model_kind in {"zipformer2_ctc", "ctc"}:
                for key in ("tokens_path", "model_path"):
                    p = str(sherpa.get(key, "") or "").strip()
                    if not p:
                        self._add_issue(errors, "REQUIRED", f"sherpa.{key}", f"CTC 模式必须填写 {key}")
                    elif not Path(p).exists():
                        self._add_issue(warnings, "PATH_NOT_FOUND", f"sherpa.{key}", f"文件不存在: {p}")
            else:
                for key in ("tokens_path", "encoder_path", "decoder_path", "joiner_path"):
                    p = str(sherpa.get(key, "") or "").strip()
                    if not p:
                        self._add_issue(errors, "REQUIRED", f"sherpa.{key}", f"Transducer 模式必须填写 {key}")
                    elif not Path(p).exists():
                        self._add_issue(warnings, "PATH_NOT_FOUND", f"sherpa.{key}", f"文件不存在: {p}")

        if asr_type in {"funasr", "openai"}:
            api_url = str(asr.get("api_url", "") or "").strip()
            if not api_url:
                self._add_issue(errors, "REQUIRED", "asr.api_url", "HTTP ASR 模式必须填写 asr.api_url")

        if errors:
            self._add_issue(fix_hints, "FIX_FIRST", "*", "请先修复错误项，再执行应用")
        elif warnings:
            self._add_issue(fix_hints, "REVIEW_WARNINGS", "*", "建议检查 warning 项，避免运行时回退或失败")

        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "fix_hints": fix_hints,
            "normalized": cfg,
        }

    async def _probe_http(self, url: str, timeout_sec: float) -> tuple[bool, str]:
        timeout = aiohttp.ClientTimeout(total=max(1.0, timeout_sec))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    return resp.status < 500, f"HTTP {resp.status}"
        except Exception as e:
            return False, str(e)

    async def _probe_ws(self, url: str, headers: dict[str, str], timeout_sec: float) -> tuple[bool, str]:
        timeout = aiohttp.ClientTimeout(total=max(1.0, timeout_sec))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                ws = await session.ws_connect(url, headers=headers, heartbeat=10)
                await ws.close()
            return True, "ws_connect ok"
        except Exception as e:
            return False, str(e)

    async def test_connectivity(self, value: dict[str, Any] | None) -> dict[str, Any]:
        cfg = self.normalize(value)
        result = {
            "ok": True,
            "checks": {
                "tts": {"ok": True, "message": "skipped"},
                "asr": {"ok": True, "message": "skipped"},
            },
        }

        tts = cfg.get("tts", {})
        tts_type = str(tts.get("type", "mock")).strip()

        if tts_type == "sovits":
            ok, message = await self._probe_http(str(tts.get("api_url", "")).rstrip("/") + "/tts", float(tts.get("connect_timeout_sec", 3.0)))
            result["checks"]["tts"] = {"ok": ok, "message": message, "type": tts_type}
            result["ok"] = result["ok"] and ok
        elif tts_type == "doubao_ws":
            headers = {
                "X-Api-App-Key": str(tts.get("doubao_app_key", "")),
                "X-Api-Access-Key": str(tts.get("doubao_access_key", "")),
                "X-Api-Resource-Id": str(tts.get("doubao_resource_id", "")),
            }
            ok, message = await self._probe_ws(str(tts.get("api_url", "")), headers, float(tts.get("connect_timeout_sec", 3.0)))
            result["checks"]["tts"] = {"ok": ok, "message": message, "type": tts_type}
            result["ok"] = result["ok"] and ok
        elif tts_type == "cosyvoice_http":
            endpoint = self._resolve_cosyvoice_endpoint(tts)
            ok, message = await self._probe_http(endpoint, float(tts.get("connect_timeout_sec", 3.0)))
            result["checks"]["tts"] = {"ok": ok, "message": message, "type": tts_type}
            result["ok"] = result["ok"] and ok
        else:
            result["checks"]["tts"] = {"ok": True, "message": "mock mode", "type": tts_type}

        asr = cfg.get("asr", {})
        asr_type = str(asr.get("type", "mock")).strip()

        if asr_type == "sherpa":
            sherpa_cfg = cfg.get("sherpa", {})
            asr_obj = SherpaASR(sherpa_cfg)
            ok = getattr(asr_obj, "recognizer", None) is not None
            message = "Sherpa model loaded" if ok else "Sherpa recognizer unavailable"
            result["checks"]["asr"] = {"ok": ok, "message": message, "type": asr_type}
            result["ok"] = result["ok"] and ok
        elif asr_type in {"funasr", "openai"}:
            api_url = str(asr.get("api_url", ""))
            parsed = urlparse(api_url)
            if parsed.scheme in {"ws", "wss"}:
                ok, message = await self._probe_ws(api_url, {}, 5.0)
            else:
                ok, message = await self._probe_http(api_url, 5.0)
            result["checks"]["asr"] = {"ok": ok, "message": message, "type": asr_type}
            result["ok"] = result["ok"] and ok
        else:
            result["checks"]["asr"] = {"ok": True, "message": "mock mode", "type": asr_type}

        return result

    def _prune_backups(self, keep: int = 10) -> None:
        if not self.backup_dir.exists():
            return
        backups = sorted(self.backup_dir.glob("config.toml.backup.*"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in backups[keep:]:
            try:
                old.unlink()
            except Exception:
                pass

    def write_config(self, value: dict[str, Any]) -> dict[str, Any]:
        cfg = self.normalize(value)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        backup_path: Path | None = None
        if self.config_path.exists():
            ts = time.strftime("%Y%m%d%H%M%S")
            backup_path = self.backup_dir / f"config.toml.backup.{ts}"
            shutil.copy2(self.config_path, backup_path)

        tmp_path = self.config_path.with_suffix(".toml.tmp")
        tmp_path.write_text(tomlkit.dumps(cfg), encoding="utf-8")
        os.replace(tmp_path, self.config_path)
        self._prune_backups(keep=10)

        return {
            "backup_path": str(backup_path) if backup_path else None,
            "config_path": str(self.config_path),
            "config": cfg,
        }

    def rollback(self, backup_path: str | None) -> bool:
        if not backup_path:
            return False
        p = Path(backup_path)
        if not p.exists():
            return False
        shutil.copy2(p, self.config_path)
        return True

    def build_schema(self) -> dict[str, Any]:
        sections: dict[str, Any] = {}
        for section, fields in PLUGIN_CONFIG_SCHEMA.items():
            if not isinstance(fields, dict):
                continue
            sections[section] = {
                "fields": {
                    key: field.to_dict() for key, field in fields.items()
                }
            }

        return {
            "sections": sections,
            "wizard": {
                "tts_provider_options": [
                    {"value": "doubao_ws", "label": "Doubao WS"},
                    {"value": "sovits", "label": "GPT-SoVITS"},
                    {"value": "cosyvoice_http", "label": "CosyVoice HTTP"},
                    {"value": "mock", "label": "Mock"},
                ],
                "tts_templates": {
                    "doubao_ws": [
                        {
                            "id": "doubao_seed_tts_2",
                            "label": "Doubao seed-tts-2.0",
                            "defaults": {
                                "type": "doubao_ws",
                                "api_url": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
                                "doubao_resource_id": "seed-tts-2.0",
                                "doubao_namespace": "BidirectionalTTS",
                                "doubao_audio_format": "pcm",
                                "doubao_sample_rate": 24000,
                                "doubao_enable_timestamp": False,
                                "doubao_disable_markdown_filter": False,
                            },
                        },
                        {
                            "id": "doubao_seed_icl_2",
                            "label": "Doubao seed-icl-2.0",
                            "defaults": {
                                "type": "doubao_ws",
                                "api_url": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
                                "doubao_resource_id": "seed-icl-2.0",
                                "doubao_namespace": "BidirectionalTTS",
                                "doubao_audio_format": "pcm",
                                "doubao_sample_rate": 24000,
                                "doubao_enable_timestamp": False,
                                "doubao_disable_markdown_filter": False,
                            },
                        },
                        {
                            "id": "doubao_seed_tts_1_concurr",
                            "label": "Doubao seed-tts-1.0-concurr",
                            "defaults": {
                                "type": "doubao_ws",
                                "api_url": "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
                                "doubao_resource_id": "seed-tts-1.0-concurr",
                                "doubao_namespace": "BidirectionalTTS",
                                "doubao_audio_format": "pcm",
                                "doubao_sample_rate": 24000,
                                "doubao_enable_timestamp": False,
                                "doubao_disable_markdown_filter": False,
                            },
                        },
                    ],
                    "sovits": [
                        {
                            "id": "sovits_default",
                            "label": "SoVITS local default",
                            "defaults": {
                                "type": "sovits",
                                "api_url": "http://127.0.0.1:9880",
                                "voice_id": "default",
                                "gpt_weights": "",
                                "sovits_weights": "",
                            },
                        }
                    ],
                    "cosyvoice_http": [
                        {
                            "id": "cosyvoice_cross_lingual",
                            "label": "CosyVoice cross_lingual",
                            "defaults": {
                                "type": "cosyvoice_http",
                                "api_url": "http://127.0.0.1:50000",
                                "cosyvoice_mode": "cross_lingual",
                                "cosyvoice_ref_audio_path": "",
                                "cosyvoice_ref_text": "",
                                "cosyvoice_sample_rate": 22050,
                            },
                        },
                        {
                            "id": "cosyvoice_zero_shot",
                            "label": "CosyVoice zero_shot",
                            "defaults": {
                                "type": "cosyvoice_http",
                                "api_url": "http://127.0.0.1:50000",
                                "cosyvoice_mode": "zero_shot",
                                "cosyvoice_ref_audio_path": "",
                                "cosyvoice_ref_text": "",
                                "cosyvoice_sample_rate": 22050,
                            },
                        },
                    ],
                    "mock": [
                        {
                            "id": "mock",
                            "label": "Mock",
                            "defaults": {"type": "mock"},
                        }
                    ],
                },
                "steps": [
                    "Select provider/template",
                    "Fill required fields",
                    "Validate",
                    "Connectivity test",
                    "Apply and restart",
                ],
            },
        }


config_manager = ConfigManager()
