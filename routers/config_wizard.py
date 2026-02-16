import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config_manager import config_manager
from ..core.service import call_me_service
from ..core.tts_manager import tts_manager
from ..database import get_db_session


router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigPayload(BaseModel):
    config: dict[str, Any]


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
    else:
        # Standalone uvicorn path: runtime config can still be applied without owning lifecycle.
        if enabled:
            restarted = False

    await asyncio.sleep(0.2)
    status = call_me_service.get_status()
    health_ok = True if not enabled else ("运行中" in status or not getattr(call_me_service, "_is_running", False))
    return {
        "restarted": restarted,
        "health_ok": health_ok,
        "status": status,
    }


@router.get("/asr-tts/schema")
async def get_asr_tts_schema(db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    del db
    return config_manager.build_schema()


@router.get("/asr-tts/current")
async def get_asr_tts_current(db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    del db
    cfg = config_manager.get_current_config()
    return {
        "config": config_manager.mask_sensitive(cfg),
        "config_path": str(config_manager.config_path),
    }


@router.post("/asr-tts/validate")
async def validate_asr_tts(payload: ConfigPayload, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    del db
    result = config_manager.validate_config(payload.config)
    result["normalized"] = config_manager.mask_sensitive(result.get("normalized", {}))
    return result


@router.post("/asr-tts/test-connectivity")
async def test_asr_tts_connectivity(payload: ConfigPayload, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    del db
    valid = config_manager.validate_config(payload.config)
    if not valid.get("ok", False):
        raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "validation": valid})

    result = await config_manager.test_connectivity(payload.config)
    return result


@router.put("/asr-tts/apply")
async def apply_asr_tts_config(
    payload: ConfigPayload,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    del db
    async with config_manager.apply_lock:
        old_cfg = config_manager.get_current_config()
        validation = config_manager.validate_config(payload.config)
        if not validation.get("ok", False):
            raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED", "validation": validation})

        write_result = config_manager.write_config(validation["normalized"])
        backup_path = write_result.get("backup_path")

        rollback_used = False
        try:
            runtime = await _apply_runtime_config(request, validation["normalized"])
            return {
                "saved": True,
                "restarted": bool(runtime.get("restarted", False)),
                "health_ok": bool(runtime.get("health_ok", False)),
                "rollback_used": False,
                "status": runtime.get("status", ""),
                "config_path": write_result.get("config_path"),
                "backup_path": backup_path,
            }
        except Exception as e:
            config_manager.rollback(backup_path)
            rollback_used = True
            # Try to restore runtime with old config as best effort.
            try:
                await _apply_runtime_config(request, old_cfg)
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "RESTART_FAILED",
                    "message": str(e),
                    "saved": True,
                    "rollback_used": rollback_used,
                },
            )
