import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config_manager import config_manager
from ..core.license_guard import (
    accept_license,
    get_license_allowlist,
    has_license_acceptance,
    is_license_allowed,
)
from ..core.model_installer import InstallError, model_installer
from ..core.model_registry import AsrSourceItem, model_registry
from ..core.service import call_me_service
from ..core.tts_manager import tts_manager
from ..database import get_db_session
from ..models import AsrInstalledModel, AsrModelSourceCustom


router = APIRouter(prefix="/api/asr-models", tags=["asr-models"])


class CustomSourcePayload(BaseModel):
    source_id: str
    repo: str
    enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["releases"])
    file_patterns: list[str] = Field(default_factory=lambda: ["*.tar.bz2", "*.tar.gz", "*.zip"])
    sha256_map: dict[str, str] = Field(default_factory=dict)
    license_spdx: str = ""
    license_url: str = ""
    extract_layout: str = "auto"


class CustomSourcePatchPayload(BaseModel):
    repo: str | None = None
    enabled: bool | None = None
    channels: list[str] | None = None
    file_patterns: list[str] | None = None
    sha256_map: dict[str, str] | None = None
    license_spdx: str | None = None
    license_url: str | None = None
    extract_layout: str | None = None


class ScanRequest(BaseModel):
    source_ids: list[str] | None = None
    include_disabled: bool = False
    timeout_sec: float = 60.0
    max_items: int = 500


class LicenseAcceptPayload(BaseModel):
    source_id: str
    license_spdx: str


class InstallRequest(BaseModel):
    candidate: dict[str, Any]


class ApplyInstalledRequest(BaseModel):
    install_id: str
    model_kind: str | None = None


async def _apply_runtime_config(request: Request, cfg: dict[str, Any]) -> dict[str, Any]:
    server_cfg = cfg.get("server", {}) if isinstance(cfg, dict) else {}
    host = str(server_cfg.get("host", "127.0.0.1"))
    port = int(server_cfg.get("port", 8989))

    call_me_service.configure(host, port, cfg)
    tts_manager.configure(cfg.get("tts", {}) if isinstance(cfg, dict) else {})

    plugin_cfg = cfg.get("plugin", {}) if isinstance(cfg, dict) else {}
    enabled = bool(plugin_cfg.get("enabled", True)) if isinstance(plugin_cfg, dict) else True

    restarted = False
    if getattr(call_me_service, "_is_running", False):
        call_me_service.stop()
        await asyncio.sleep(0.8)
        if enabled:
            call_me_service.start(request.app)
            restarted = True

    await asyncio.sleep(0.2)
    status = call_me_service.get_status()
    health_ok = True if not enabled else ("运行中" in status or not getattr(call_me_service, "_is_running", False))
    return {
        "restarted": restarted,
        "health_ok": health_ok,
        "status": status,
    }


async def _list_sources(db: AsyncSession) -> list[AsrSourceItem]:
    return await model_registry.list_sources(db)


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    sources = await _list_sources(db)
    return {"items": [s.to_dict() for s in sources]}


@router.post("/sources/custom")
async def create_custom_source(payload: CustomSourcePayload, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    sources = await _list_sources(db)
    if any(s.source_id == payload.source_id for s in sources):
        raise HTTPException(status_code=400, detail={"code": "SOURCE_EXISTS", "message": "source_id already exists"})

    row = AsrModelSourceCustom(
        source_id=payload.source_id.strip(),
        repo=payload.repo.strip(),
        enabled=bool(payload.enabled),
        channels_json=json.dumps(payload.channels, ensure_ascii=False),
        file_patterns_json=json.dumps(payload.file_patterns, ensure_ascii=False),
        sha256_map_json=json.dumps(payload.sha256_map, ensure_ascii=False),
        license_spdx=payload.license_spdx.strip(),
        license_url=payload.license_url.strip(),
        extract_layout=payload.extract_layout.strip() or "auto",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"status": "ok", "source_id": row.source_id}


@router.patch("/sources/custom/{source_id}")
async def patch_custom_source(
    source_id: str,
    payload: CustomSourcePatchPayload,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = (await db.execute(select(AsrModelSourceCustom).where(AsrModelSourceCustom.source_id == source_id))).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "SOURCE_NOT_FOUND", "message": "custom source not found"})

    if payload.repo is not None:
        row.repo = payload.repo.strip()
    if payload.enabled is not None:
        row.enabled = bool(payload.enabled)
    if payload.channels is not None:
        row.channels_json = json.dumps(payload.channels, ensure_ascii=False)
    if payload.file_patterns is not None:
        row.file_patterns_json = json.dumps(payload.file_patterns, ensure_ascii=False)
    if payload.sha256_map is not None:
        row.sha256_map_json = json.dumps(payload.sha256_map, ensure_ascii=False)
    if payload.license_spdx is not None:
        row.license_spdx = payload.license_spdx.strip()
    if payload.license_url is not None:
        row.license_url = payload.license_url.strip()
    if payload.extract_layout is not None:
        row.extract_layout = payload.extract_layout.strip() or "auto"

    await db.commit()
    return {"status": "ok", "source_id": row.source_id}


@router.delete("/sources/custom/{source_id}")
async def delete_custom_source(source_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    row = (await db.execute(select(AsrModelSourceCustom).where(AsrModelSourceCustom.source_id == source_id))).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "SOURCE_NOT_FOUND", "message": "custom source not found"})
    await db.delete(row)
    await db.commit()
    return {"status": "ok"}


@router.post("/scan")
async def scan_models(payload: ScanRequest, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    cfg = config_manager.get_current_config()
    downloader_cfg = cfg.get("model_downloader", {}) if isinstance(cfg, dict) else {}
    timeout_sec = float(downloader_cfg.get("connect_timeout_sec", payload.timeout_sec))

    sources = await _list_sources(db)
    if payload.source_ids:
        selected = set(payload.source_ids)
        sources = [s for s in sources if s.source_id in selected]

    if not payload.include_disabled:
        sources = [s for s in sources if s.enabled]

    async def _scan_one(src: AsrSourceItem):
        items, channel_errors = await asyncio.to_thread(model_registry.scan_source_with_errors, src, timeout_sec)
        return src, items, channel_errors

    per_source_timeout = max(5.0, float(payload.timeout_sec))
    scan_tasks = [asyncio.wait_for(_scan_one(src), timeout=per_source_timeout) for src in sources]
    batches = await asyncio.gather(*scan_tasks, return_exceptions=True)

    candidates = []
    errors: list[dict[str, str]] = []
    for src, batch in zip(sources, batches, strict=False):
        if isinstance(batch, asyncio.TimeoutError):
            errors.append({"source_id": src.source_id, "message": f"scan timeout after {per_source_timeout:.1f}s"})
            continue
        if isinstance(batch, Exception):
            errors.append({"source_id": src.source_id, "message": str(batch)})
            continue
        _src, items, channel_errors = batch
        candidates.extend(items)
        for msg in channel_errors:
            errors.append({"source_id": src.source_id, "message": msg})

    allowlist = get_license_allowlist(cfg)
    for candidate in candidates:
        if candidate.downloadable and not is_license_allowed(candidate.license_spdx, allowlist):
            candidate.downloadable = False
            candidate.blocked_reason = "LICENSE_NOT_ALLOWED"
            continue
        if candidate.downloadable and not await has_license_acceptance(db, candidate.source_id, candidate.license_spdx):
            candidate.downloadable = False
            candidate.blocked_reason = "LICENSE_NOT_ACCEPTED"

    total_candidates = len(candidates)
    max_items = max(1, min(int(payload.max_items), 5000))
    truncated = total_candidates > max_items
    if truncated:
        candidates = candidates[:max_items]

    return {
        "items": [x.to_dict() for x in candidates],
        "errors": errors,
        "total_candidates": total_candidates,
        "returned_candidates": len(candidates),
        "truncated": truncated,
    }


@router.post("/licenses/accept")
async def accept_model_license(payload: LicenseAcceptPayload, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    cfg = config_manager.get_current_config()
    allowlist = get_license_allowlist(cfg)
    if not is_license_allowed(payload.license_spdx, allowlist):
        raise HTTPException(
            status_code=400,
            detail={"code": "LICENSE_NOT_ALLOWED", "message": "license not in allowlist"},
        )

    row = await accept_license(db, payload.source_id, payload.license_spdx)
    return {
        "status": "ok",
        "acceptance_id": row.acceptance_id,
        "source_id": row.source_id,
        "license_spdx": row.license_spdx,
    }


@router.post("/install")
async def install_model(payload: InstallRequest, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    cfg = config_manager.get_current_config()
    allowlist = get_license_allowlist(cfg)
    candidate = payload.candidate

    source_id = str(candidate.get("source_id", "") or "")
    license_spdx = str(candidate.get("license_spdx", "") or "")
    sha256 = str(candidate.get("sha256", "") or "")

    if not source_id:
        raise HTTPException(status_code=400, detail={"code": "INVALID_CANDIDATE", "message": "missing source_id"})
    if not is_license_allowed(license_spdx, allowlist):
        raise HTTPException(status_code=400, detail={"code": "LICENSE_NOT_ALLOWED", "message": "license not in allowlist"})
    if not await has_license_acceptance(db, source_id, license_spdx):
        raise HTTPException(status_code=400, detail={"code": "LICENSE_NOT_ACCEPTED", "message": "license must be accepted first"})
    if not sha256:
        raise HTTPException(status_code=400, detail={"code": "SHA256_MISSING", "message": "candidate sha256 required"})

    timeout_sec = float((cfg.get("model_downloader", {}) or {}).get("download_timeout_sec", 600.0))

    try:
        install_result = await asyncio.to_thread(model_installer.install_candidate, candidate, timeout_sec)
    except InstallError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message}) from e

    row = AsrInstalledModel(
        install_id=uuid.uuid4().hex,
        source_id=install_result["source_id"],
        artifact_key=install_result["artifact_key"],
        artifact_name=install_result["artifact_name"],
        channel=str(candidate.get("channel", "releases") or "releases"),
        download_url=install_result["download_url"],
        sha256=install_result["sha256"],
        install_dir=install_result["install_dir"],
        manifest_json=json.dumps(install_result["manifest"], ensure_ascii=False),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return {
        "status": "ok",
        "install_id": row.install_id,
        "install_dir": row.install_dir,
        "manifest": install_result["manifest"],
    }


@router.get("/installed")
async def list_installed_models(db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(AsrInstalledModel).order_by(AsrInstalledModel.created_at.desc(), AsrInstalledModel.install_id.desc())
        )
    ).scalars().all()

    items = []
    for row in rows:
        try:
            manifest = json.loads(row.manifest_json or "{}")
        except Exception:
            manifest = {}
        items.append(
            {
                "install_id": row.install_id,
                "source_id": row.source_id,
                "artifact_key": row.artifact_key,
                "artifact_name": row.artifact_name,
                "channel": row.channel,
                "download_url": row.download_url,
                "sha256": row.sha256,
                "install_dir": row.install_dir,
                "manifest": manifest,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    return {"items": items}


@router.post("/apply-installed")
async def apply_installed_model(
    payload: ApplyInstalledRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = (await db.execute(select(AsrInstalledModel).where(AsrInstalledModel.install_id == payload.install_id))).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "INSTALL_NOT_FOUND", "message": "installed model not found"})

    try:
        manifest = json.loads(row.manifest_json or "{}")
    except Exception:
        manifest = {}

    model_kind = str(payload.model_kind or manifest.get("recommended_model_kind") or "").strip().lower()
    if model_kind not in {"zipformer2_ctc", "transducer"}:
        if manifest.get("model_path"):
            model_kind = "zipformer2_ctc"
        elif manifest.get("encoder_path") and manifest.get("decoder_path") and manifest.get("joiner_path"):
            model_kind = "transducer"
        else:
            raise HTTPException(status_code=400, detail={"code": "MODEL_KIND_UNRESOLVED", "message": "cannot infer model_kind"})

    async with config_manager.apply_lock:
        old_cfg = config_manager.get_current_config()
        cfg = config_manager.get_current_config()

        cfg.setdefault("asr", {})
        cfg.setdefault("sherpa", {})
        cfg["asr"]["type"] = "sherpa"
        cfg["sherpa"]["model_kind"] = model_kind
        cfg["sherpa"]["tokens_path"] = str(manifest.get("tokens_path", "") or "")

        if model_kind == "zipformer2_ctc":
            cfg["sherpa"]["model_path"] = str(manifest.get("model_path", "") or "")
            cfg["sherpa"]["encoder_path"] = ""
            cfg["sherpa"]["decoder_path"] = ""
            cfg["sherpa"]["joiner_path"] = ""
        else:
            cfg["sherpa"]["model_path"] = ""
            cfg["sherpa"]["encoder_path"] = str(manifest.get("encoder_path", "") or "")
            cfg["sherpa"]["decoder_path"] = str(manifest.get("decoder_path", "") or "")
            cfg["sherpa"]["joiner_path"] = str(manifest.get("joiner_path", "") or "")

        validation = config_manager.validate_config(cfg)
        if not validation.get("ok", False):
            raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "validation": validation})

        write_result = config_manager.write_config(validation["normalized"])
        backup_path = write_result.get("backup_path")

        try:
            runtime = await _apply_runtime_config(request, validation["normalized"])
            return {
                "status": "ok",
                "saved": True,
                "restarted": runtime.get("restarted", False),
                "health_ok": runtime.get("health_ok", False),
                "rollback_used": False,
            }
        except Exception as e:
            config_manager.rollback(backup_path)
            try:
                await _apply_runtime_config(request, old_cfg)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail={"code": "RESTART_FAILED", "message": str(e)}) from e
