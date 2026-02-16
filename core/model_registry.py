import fnmatch
import json
import os
import re
from datetime import date, datetime
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AsrModelSourceCustom


ARCHIVE_SUFFIXES = (".tar.bz2", ".tar.gz", ".zip")
CHECKSUM_ASSET_NAMES = ("checksum.txt", "checksums.txt", "sha256.txt", "sha256sum.txt")
SUPPORTED_SHERPA_MODEL_PATTERNS = (
    re.compile(r"^sherpa-onnx-streaming-zipformer-ctc-zh-int8-\d{4}-\d{2}-\d{2}\.(tar\.bz2|tar\.gz|zip)$"),
    re.compile(r"^sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-\d{4}-\d{2}-\d{2}\.(tar\.bz2|tar\.gz|zip)$"),
    re.compile(r"^sherpa-onnx-streaming-zipformer-zh-int8-\d{4}-\d{2}-\d{2}\.(tar\.bz2|tar\.gz|zip)$"),
)
MIN_SUPPORTED_MODEL_DATE = date(2025, 1, 1)
MODEL_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class AsrSourceItem:
    source_id: str
    repo: str
    enabled: bool
    channels: list[str]
    file_patterns: list[str]
    sha256_map: dict[str, str]
    license_spdx: str
    license_url: str
    extract_layout: str
    source_type: str = "builtin"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "repo": self.repo,
            "enabled": self.enabled,
            "channels": list(self.channels),
            "file_patterns": list(self.file_patterns),
            "sha256_map": dict(self.sha256_map),
            "license_spdx": self.license_spdx,
            "license_url": self.license_url,
            "extract_layout": self.extract_layout,
            "source_type": self.source_type,
        }


@dataclass
class AsrModelCandidate:
    candidate_id: str
    source_id: str
    repo: str
    channel: str
    release_tag: str
    artifact_name: str
    artifact_key: str
    download_url: str
    size_bytes: int
    sha256: str
    license_spdx: str
    license_url: str
    downloadable: bool
    blocked_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_id": self.source_id,
            "repo": self.repo,
            "channel": self.channel,
            "release_tag": self.release_tag,
            "artifact_name": self.artifact_name,
            "artifact_key": self.artifact_key,
            "download_url": self.download_url,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "license_spdx": self.license_spdx,
            "license_url": self.license_url,
            "downloadable": self.downloadable,
            "blocked_reason": self.blocked_reason,
        }


class ModelRegistry:
    def __init__(self):
        self.plugin_dir = Path(__file__).resolve().parent.parent
        self.builtin_sources_path = self.plugin_dir / "asr_sources_builtin.json"

    def _json_get(self, url: str, timeout: float, headers: dict[str, str] | None = None) -> Any:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=max(1.0, timeout)) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        return json.loads(raw)

    def _text_get(self, url: str, timeout: float, headers: dict[str, str] | None = None) -> str:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=max(1.0, timeout)) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    @staticmethod
    def _github_headers() -> dict[str, str]:
        token = str(os.getenv("GITHUB_TOKEN", "") or "").strip()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "MaiBot-call_me-model-registry",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _normalize_str_list(raw: Any, default: list[str]) -> list[str]:
        if not isinstance(raw, list):
            return list(default)
        out: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out or list(default)

    @staticmethod
    def _normalize_sha_map(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in raw.items():
            k = str(key or "").strip()
            v = str(value or "").strip().lower()
            if not k or not re.fullmatch(r"[0-9a-f]{64}", v):
                continue
            out[k] = v
            out[Path(k).name] = v
        return out

    @staticmethod
    def _sanitize_key(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")[:120] or "artifact"

    @staticmethod
    def _is_archive(name: str) -> bool:
        lower = name.lower()
        return any(lower.endswith(suf) for suf in ARCHIVE_SUFFIXES)

    @staticmethod
    def _match_patterns(name: str, patterns: list[str]) -> bool:
        if not patterns:
            return True
        return any(fnmatch.fnmatch(name, pat) for pat in patterns)

    @staticmethod
    def _extract_model_date(name: str) -> date | None:
        m = MODEL_DATE_RE.search(name)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except Exception:
            return None

    def _is_supported_for_source(self, source: AsrSourceItem, artifact_name: str) -> bool:
        if source.source_id != "sherpa_onnx_official":
            return True

        name = artifact_name.strip().lower()
        if not any(pat.fullmatch(name) for pat in SUPPORTED_SHERPA_MODEL_PATTERNS):
            return False

        model_date = self._extract_model_date(name)
        if model_date is not None and model_date < MIN_SUPPORTED_MODEL_DATE:
            return False
        return True

    @staticmethod
    def _parse_checksum_text(text: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue

            parts_tab = [p.strip() for p in s.split("\t") if p.strip()]
            if len(parts_tab) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts_tab[1]):
                name = parts_tab[0].lstrip("* ")
                sha = parts_tab[1].lower()
                mapping[name] = sha
                mapping[Path(name).name] = sha
                continue

            m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", s)
            if m:
                sha = m.group(1).lower()
                name = m.group(2).strip()
                mapping[name] = sha
                mapping[Path(name).name] = sha
                continue

            m2 = re.match(r"^(.+)\s+([0-9a-fA-F]{64})$", s)
            if m2:
                name = m2.group(1).strip().lstrip("* ")
                sha = m2.group(2).lower()
                mapping[name] = sha
                mapping[Path(name).name] = sha
        return mapping

    def load_builtin_sources(self) -> list[AsrSourceItem]:
        if not self.builtin_sources_path.exists():
            return []
        try:
            raw = json.loads(self.builtin_sources_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        out: list[AsrSourceItem] = []
        if not isinstance(raw, list):
            return out

        for item in raw:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id", "") or "").strip()
            repo = str(item.get("repo", "") or "").strip()
            if not source_id or not repo:
                continue
            out.append(
                AsrSourceItem(
                    source_id=source_id,
                    repo=repo,
                    enabled=bool(item.get("enabled", False)),
                    channels=self._normalize_str_list(item.get("channels"), ["releases"]),
                    file_patterns=self._normalize_str_list(item.get("file_patterns"), ["*.tar.bz2", "*.tar.gz", "*.zip"]),
                    sha256_map=self._normalize_sha_map(item.get("sha256_map", {})),
                    license_spdx=str(item.get("license_spdx", "") or "").strip(),
                    license_url=str(item.get("license_url", "") or "").strip(),
                    extract_layout=str(item.get("extract_layout", "auto") or "auto").strip(),
                    source_type="builtin",
                )
            )

        return out

    async def load_custom_sources(self, db: AsyncSession) -> list[AsrSourceItem]:
        rows = (await db.execute(select(AsrModelSourceCustom))).scalars().all()
        out: list[AsrSourceItem] = []
        for row in rows:
            try:
                channels = json.loads(row.channels_json or "[]")
            except Exception:
                channels = []
            try:
                patterns = json.loads(row.file_patterns_json or "[]")
            except Exception:
                patterns = []
            try:
                sha_map = json.loads(row.sha256_map_json or "{}")
            except Exception:
                sha_map = {}

            out.append(
                AsrSourceItem(
                    source_id=row.source_id,
                    repo=row.repo,
                    enabled=bool(row.enabled),
                    channels=self._normalize_str_list(channels, ["releases"]),
                    file_patterns=self._normalize_str_list(patterns, ["*.tar.bz2", "*.tar.gz", "*.zip"]),
                    sha256_map=self._normalize_sha_map(sha_map),
                    license_spdx=str(row.license_spdx or ""),
                    license_url=str(row.license_url or ""),
                    extract_layout=str(row.extract_layout or "auto"),
                    source_type="custom",
                )
            )
        return out

    async def list_sources(self, db: AsyncSession) -> list[AsrSourceItem]:
        builtins = self.load_builtin_sources()
        customs = await self.load_custom_sources(db)
        merged: dict[str, AsrSourceItem] = {s.source_id: s for s in builtins}
        for c in customs:
            merged[c.source_id] = c
        return list(merged.values())

    def _fetch_release_checksum_map(self, release: dict[str, Any], timeout_sec: float) -> dict[str, str]:
        assets = release.get("assets", []) if isinstance(release, dict) else []
        if not isinstance(assets, list):
            return {}
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "") or "").lower()
            if name not in CHECKSUM_ASSET_NAMES and "checksum" not in name and "sha256" not in name:
                continue
            download_url = str(asset.get("browser_download_url", "") or "")
            if not download_url:
                continue
            try:
                text = self._text_get(download_url, timeout_sec, headers=self._github_headers())
                mapping = self._parse_checksum_text(text)
                if mapping:
                    return mapping
            except Exception:
                continue
        return {}

    def _scan_releases(self, source: AsrSourceItem, timeout_sec: float) -> list[AsrModelCandidate]:
        out: list[AsrModelCandidate] = []
        headers = self._github_headers()
        try:
            if source.source_id == "sherpa_onnx_official":
                tagged = self._json_get(
                    f"https://api.github.com/repos/{source.repo}/releases/tags/asr-models",
                    timeout_sec,
                    headers=headers,
                )
                releases = [tagged] if isinstance(tagged, dict) else []
            else:
                releases = self._json_get(
                    f"https://api.github.com/repos/{source.repo}/releases?per_page=20",
                    timeout_sec,
                    headers=headers,
                )
        except Exception as e:
            raise RuntimeError(f"scan releases failed: {e}") from e

        if not isinstance(releases, list):
            return out

        for release in releases:
            if not isinstance(release, dict):
                continue
            tag = str(release.get("tag_name", "") or "")
            assets = release.get("assets", [])
            if not isinstance(assets, list):
                continue

            checksum_map = dict(source.sha256_map)
            checksum_map.update(self._fetch_release_checksum_map(release, timeout_sec))

            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                name = str(asset.get("name", "") or "")
                if not name:
                    continue
                if not self._is_archive(name):
                    continue
                if not self._match_patterns(name, source.file_patterns):
                    continue
                if not self._is_supported_for_source(source, name):
                    continue
                url = str(asset.get("browser_download_url", "") or "")
                if not url:
                    continue
                sha = checksum_map.get(name) or checksum_map.get(Path(name).name) or ""
                blocked = ""
                downloadable = bool(source.enabled)
                if not downloadable:
                    blocked = "SOURCE_DISABLED"
                elif not sha:
                    blocked = "SHA256_MISSING"
                    downloadable = False

                key = self._sanitize_key(f"{tag}_{name}")
                candidate_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{source.source_id}:releases:{tag}:{name}:{url}").hex
                out.append(
                    AsrModelCandidate(
                        candidate_id=candidate_id,
                        source_id=source.source_id,
                        repo=source.repo,
                        channel="releases",
                        release_tag=tag,
                        artifact_name=name,
                        artifact_key=key,
                        download_url=url,
                        size_bytes=int(asset.get("size") or 0),
                        sha256=sha,
                        license_spdx=source.license_spdx,
                        license_url=source.license_url,
                        downloadable=downloadable,
                        blocked_reason=blocked,
                    )
                )

        return out

    def _scan_repo_files(self, source: AsrSourceItem, timeout_sec: float) -> list[AsrModelCandidate]:
        out: list[AsrModelCandidate] = []
        headers = self._github_headers()

        try:
            repo_info = self._json_get(f"https://api.github.com/repos/{source.repo}", timeout_sec, headers=headers)
            default_branch = str(repo_info.get("default_branch") or "main")
            tree = self._json_get(
                f"https://api.github.com/repos/{source.repo}/git/trees/{urllib.parse.quote(default_branch, safe='')}?recursive=1",
                timeout_sec,
                headers=headers,
            )
        except Exception as e:
            raise RuntimeError(f"scan repo files failed: {e}") from e

        entries = tree.get("tree", []) if isinstance(tree, dict) else []
        if not isinstance(entries, list):
            return out

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("type", "")) != "blob":
                continue
            path = str(entry.get("path", "") or "")
            if not path:
                continue
            name = Path(path).name
            if not self._is_archive(name):
                continue
            if not (self._match_patterns(path, source.file_patterns) or self._match_patterns(name, source.file_patterns)):
                continue
            if not self._is_supported_for_source(source, name):
                continue

            sha = source.sha256_map.get(path) or source.sha256_map.get(name) or ""
            blocked = ""
            downloadable = bool(source.enabled)
            if not downloadable:
                blocked = "SOURCE_DISABLED"
            elif not sha:
                blocked = "SHA256_MISSING"
                downloadable = False

            encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
            download_url = f"https://raw.githubusercontent.com/{source.repo}/{default_branch}/{encoded_path}"
            key = self._sanitize_key(f"{default_branch}_{name}")
            candidate_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{source.source_id}:repo_files:{default_branch}:{path}").hex
            out.append(
                AsrModelCandidate(
                    candidate_id=candidate_id,
                    source_id=source.source_id,
                    repo=source.repo,
                    channel="repo_files",
                    release_tag=default_branch,
                    artifact_name=name,
                    artifact_key=key,
                    download_url=download_url,
                    size_bytes=0,
                    sha256=sha,
                    license_spdx=source.license_spdx,
                    license_url=source.license_url,
                    downloadable=downloadable,
                    blocked_reason=blocked,
                )
            )

        return out

    def scan_source_with_errors(self, source: AsrSourceItem, timeout_sec: float = 20.0) -> tuple[list[AsrModelCandidate], list[str]]:
        out: list[AsrModelCandidate] = []
        errors: list[str] = []
        channels = set(source.channels)
        releases_found = False
        if "releases" in channels:
            try:
                release_items = self._scan_releases(source, timeout_sec=timeout_sec)
                out.extend(release_items)
                releases_found = len(release_items) > 0
            except Exception as e:
                errors.append(f"releases: {e}")
        if "repo_files" in channels:
            # Repo file tree scan can be very heavy on large repos.
            # If releases already returned usable candidates, keep scan responsive.
            if not releases_found:
                try:
                    out.extend(self._scan_repo_files(source, timeout_sec=timeout_sec))
                except Exception as e:
                    errors.append(f"repo_files: {e}")

        dedup: dict[str, AsrModelCandidate] = {}
        for item in out:
            k = f"{item.source_id}:{item.channel}:{item.release_tag}:{item.artifact_name}"
            if k not in dedup:
                dedup[k] = item
        return list(dedup.values()), errors

    def scan_source(self, source: AsrSourceItem, timeout_sec: float = 20.0) -> list[AsrModelCandidate]:
        items, _errors = self.scan_source_with_errors(source, timeout_sec=timeout_sec)
        return items


model_registry = ModelRegistry()
