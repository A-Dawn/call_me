import hashlib
import os
import shutil
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


class InstallError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ModelInstaller:
    def __init__(self):
        self.plugin_dir = Path(__file__).resolve().parent.parent
        self.download_dir = self.plugin_dir / "asr" / "_downloads"
        self.models_dir = self.plugin_dir / "asr" / "models"
        self.tmp_dir = self.plugin_dir / "asr" / "_tmp"

    @staticmethod
    def _safe_resolve(base: Path, target: str) -> Path:
        resolved = (base / target).resolve()
        base_resolved = base.resolve()
        if os.path.commonpath([str(base_resolved), str(resolved)]) != str(base_resolved):
            raise InstallError("EXTRACT_UNSAFE_PATH", f"Unsafe archive path: {target}")
        return resolved

    def _safe_extract_tar(self, archive_path: Path, dest: Path):
        with tarfile.open(archive_path, "r:*") as tf:
            members = tf.getmembers()
            for m in members:
                self._safe_resolve(dest, m.name)
            tf.extractall(dest)

    def _safe_extract_zip(self, archive_path: Path, dest: Path):
        with zipfile.ZipFile(archive_path, "r") as zf:
            infos = zf.infolist()
            for info in infos:
                self._safe_resolve(dest, info.filename)
            zf.extractall(dest)

    def _extract_archive(self, archive_path: Path, dest: Path):
        name = archive_path.name.lower()
        if name.endswith(".zip"):
            self._safe_extract_zip(archive_path, dest)
            return

        if name.endswith(".tar.gz") or name.endswith(".tar.bz2") or tarfile.is_tarfile(archive_path):
            self._safe_extract_tar(archive_path, dest)
            return

        raise InstallError("UNSUPPORTED_ARCHIVE", f"Unsupported archive format: {archive_path.name}")

    def _download_with_sha256(self, url: str, expected_sha: str, out_path: Path, timeout_sec: float) -> str:
        digest = hashlib.sha256()
        req = urllib.request.Request(url, headers={"User-Agent": "MaiBot-call_me-model-installer"})
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, timeout_sec)) as resp, out_path.open("wb") as f:
                while True:
                    chunk = resp.read(1024 * 128)
                    if not chunk:
                        break
                    f.write(chunk)
                    digest.update(chunk)
        except Exception as e:
            raise InstallError("DOWNLOAD_FAILED", str(e)) from e

        actual = digest.hexdigest().lower()
        if actual != expected_sha.lower():
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise InstallError(
                "SHA256_MISMATCH",
                f"SHA256 mismatch for {out_path.name}: expected={expected_sha.lower()} actual={actual}",
            )

        return actual

    def _detect_model_manifest(self, root_dir: Path) -> dict[str, Any]:
        def _pick(patterns: list[str]) -> str:
            for pattern in patterns:
                items = sorted(root_dir.rglob(pattern))
                if items:
                    return str(items[0])
            return ""

        tokens_path = _pick(["tokens.txt"])
        model_path = _pick(["model.int8.onnx", "*ctc*.onnx", "model.onnx"])
        encoder_path = _pick(["encoder*.onnx"])
        decoder_path = _pick(["decoder*.onnx"])
        joiner_path = _pick(["joiner*.onnx"])

        model_kind = ""
        if tokens_path and model_path:
            model_kind = "zipformer2_ctc"
        elif tokens_path and encoder_path and decoder_path and joiner_path:
            model_kind = "transducer"

        return {
            "tokens_path": tokens_path,
            "model_path": model_path,
            "encoder_path": encoder_path,
            "decoder_path": decoder_path,
            "joiner_path": joiner_path,
            "recommended_model_kind": model_kind,
        }

    def install_candidate(self, candidate: dict[str, Any], timeout_sec: float = 600.0) -> dict[str, Any]:
        source_id = str(candidate.get("source_id", "") or "").strip()
        artifact_name = str(candidate.get("artifact_name", "") or "").strip()
        artifact_key = str(candidate.get("artifact_key", "") or "").strip()
        download_url = str(candidate.get("download_url", "") or "").strip()
        sha256 = str(candidate.get("sha256", "") or "").strip().lower()

        if not source_id or not artifact_name or not artifact_key or not download_url:
            raise InstallError("INVALID_CANDIDATE", "candidate fields are incomplete")
        if not sha256:
            raise InstallError("SHA256_MISSING", "candidate sha256 is required")

        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        download_path = self.download_dir / artifact_name
        actual_sha = self._download_with_sha256(download_url, sha256, download_path, timeout_sec=timeout_sec)

        tmp_extract_dir = self.tmp_dir / f"extract_{int(time.time())}_{artifact_key}"
        tmp_extract_dir.mkdir(parents=True, exist_ok=True)

        final_dir_base = self.models_dir / source_id
        final_dir_base.mkdir(parents=True, exist_ok=True)
        final_dir = final_dir_base / artifact_key
        if final_dir.exists():
            final_dir = final_dir_base / f"{artifact_key}_{int(time.time())}"

        try:
            self._extract_archive(download_path, tmp_extract_dir)

            subdirs = [p for p in tmp_extract_dir.iterdir() if p.is_dir()]
            files = [p for p in tmp_extract_dir.iterdir() if p.is_file()]

            if len(subdirs) == 1 and not files:
                shutil.move(str(subdirs[0]), str(final_dir))
                shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            else:
                shutil.move(str(tmp_extract_dir), str(final_dir))
        except InstallError:
            shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            raise
        except Exception as e:
            shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            raise InstallError("EXTRACT_FAILED", str(e)) from e

        manifest = self._detect_model_manifest(final_dir)
        return {
            "source_id": source_id,
            "artifact_name": artifact_name,
            "artifact_key": artifact_key,
            "download_url": download_url,
            "sha256": actual_sha,
            "download_path": str(download_path),
            "install_dir": str(final_dir),
            "manifest": manifest,
        }


model_installer = ModelInstaller()
