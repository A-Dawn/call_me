import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..models import Preset, PresetRule


router = APIRouter(prefix="/api/presets", tags=["presets"])


class CreatePresetRequest(BaseModel):
    name: str
    default_mode: str = "full"


class PatchPresetRequest(BaseModel):
    name: Optional[str] = None
    default_mode: Optional[str] = None


class CreateRuleRequest(BaseModel):
    priority: int = 100
    mode: str = "full"
    match_json: str = "{}"
    payload_json: str


@router.get("/")
async def list_presets(db: AsyncSession = Depends(get_db_session)) -> list[dict[str, Any]]:
    stmt = select(Preset).order_by(Preset.created_at.asc(), Preset.preset_id.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "preset_id": p.preset_id,
            "owner_id": p.owner_id,
            "name": p.name,
            "default_mode": p.default_mode,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.post("/")
async def create_preset(
    req: CreatePresetRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    preset_id = uuid.uuid4().hex
    preset = Preset(
        preset_id=preset_id,
        owner_id="",
        name=req.name,
        default_mode=req.default_mode,
    )
    db.add(preset)
    await db.commit()
    return {"preset_id": preset_id}


@router.get("/{preset_id}")
async def get_preset(preset_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    stmt = select(Preset).where(Preset.preset_id == preset_id)
    preset = (await db.execute(stmt)).scalars().first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {
        "preset_id": preset.preset_id,
        "owner_id": preset.owner_id,
        "name": preset.name,
        "default_mode": preset.default_mode,
        "created_at": preset.created_at.isoformat() if preset.created_at else None,
    }


@router.patch("/{preset_id}")
async def patch_preset(
    preset_id: str,
    req: PatchPresetRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    stmt = select(Preset).where(Preset.preset_id == preset_id)
    preset = (await db.execute(stmt)).scalars().first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    if req.name is not None:
        preset.name = req.name
    if req.default_mode is not None:
        preset.default_mode = req.default_mode

    await db.commit()
    await db.refresh(preset)
    return {
        "preset_id": preset.preset_id,
        "name": preset.name,
        "default_mode": preset.default_mode,
    }


@router.post("/{preset_id}/rules")
async def add_rule(
    preset_id: str,
    req: CreateRuleRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    # Ensure preset exists
    stmt = select(Preset).where(Preset.preset_id == preset_id)
    preset = (await db.execute(stmt)).scalars().first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    rule_id = uuid.uuid4().hex
    rule = PresetRule(
        rule_id=rule_id,
        preset_id=preset_id,
        priority=req.priority,
        mode=req.mode,
        match_json=req.match_json,
        payload_json=req.payload_json,
    )
    db.add(rule)
    await db.commit()
    return {"rule_id": rule_id, "status": "ok"}


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    stmt = select(Preset).where(Preset.preset_id == preset_id)
    preset = (await db.execute(stmt)).scalars().first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    # Delete associated rules first.
    await db.execute(delete(PresetRule).where(PresetRule.preset_id == preset_id))
    await db.delete(preset)
    await db.commit()
    return {"status": "ok"}
