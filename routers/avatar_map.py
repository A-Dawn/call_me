import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.avatar_characters import (
    collect_config_asset_ids,
    default_character_config,
    ensure_active_character,
    ensure_assets_exist,
    normalize_character_config,
    upsert_legacy_avatar_map_from_full_map,
)
from ..core.emotion import EMOTION_TYPES, normalize_emotion
from ..database import get_db_session
from ..models import Asset, AvatarCharacter


router = APIRouter(prefix="/api/avatar-map", tags=["avatar-map"])


class AvatarMapUpsertRequest(BaseModel):
    mapping: Dict[str, str]


class AvatarMapBindRequest(BaseModel):
    emotion: str
    asset_id: str


def _safe_load_config(character: AvatarCharacter) -> dict[str, Any]:
    try:
        return normalize_character_config(json.loads(character.config_json))
    except Exception:
        return default_character_config()


def _normalize_full_map(value: dict[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {emo: None for emo in EMOTION_TYPES}
    for emo in EMOTION_TYPES:
        raw = value.get(emo) if isinstance(value, dict) else None
        out[emo] = raw.strip() if isinstance(raw, str) and raw.strip() else None
    return out


async def _serialize_legacy_map(
    db: AsyncSession, character: AvatarCharacter, full_map: dict[str, str | None]
) -> dict[str, Any]:
    mapping = _normalize_full_map(full_map)

    assets_by_id: Dict[str, Asset] = {}
    asset_ids = [v for v in mapping.values() if isinstance(v, str) and v.strip()]
    if asset_ids:
        rows = (await db.execute(select(Asset).where(Asset.asset_id.in_(asset_ids)))).scalars().all()
        assets_by_id = {a.asset_id: a for a in rows}

    data: Dict[str, Any] = {}
    for emo in EMOTION_TYPES:
        asset_id = mapping.get(emo)
        if not asset_id:
            data[emo] = None
            continue
        asset = assets_by_id.get(asset_id)
        if not asset:
            data[emo] = {"asset_id": asset_id, "url": None, "exists": False}
            continue
        data[emo] = {
            "asset_id": asset.asset_id,
            "url": f"/api/assets/{asset.asset_id}/file",
            "path": asset.path,
            "exists": True,
        }

    return {
        "map_id": "default",
        "name": character.name,
        "mapping": data,
        "updated_at": character.updated_at.isoformat() if character.updated_at else None,
    }


@router.get("/active")
async def get_active_avatar_map(db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    _, character = await ensure_active_character(db)
    config = _safe_load_config(character)
    return await _serialize_legacy_map(db, character, config.get("fullMap", {}))


@router.put("/active")
async def put_active_avatar_map(
    req: AvatarMapUpsertRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _, character = await ensure_active_character(db)
    config = _safe_load_config(character)

    incoming: Dict[str, str] = {}
    for k, v in req.mapping.items():
        emo = normalize_emotion(k, default="")
        if emo not in EMOTION_TYPES:
            continue
        asset_id = str(v).strip()
        if asset_id:
            incoming[emo] = asset_id

    await ensure_assets_exist(db, incoming.values())
    next_full_map: dict[str, str | None] = {emo: None for emo in EMOTION_TYPES}
    for emo, asset_id in incoming.items():
        next_full_map[emo] = asset_id
    config["fullMap"] = next_full_map

    await ensure_assets_exist(db, collect_config_asset_ids(config))
    character.config_json = json.dumps(config, ensure_ascii=False)
    await upsert_legacy_avatar_map_from_full_map(db, next_full_map)
    await db.commit()
    await db.refresh(character)
    return await _serialize_legacy_map(db, character, next_full_map)


@router.put("/bind")
async def bind_avatar_map(
    req: AvatarMapBindRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    emo = normalize_emotion(req.emotion, default="")
    if emo not in EMOTION_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid emotion: {req.emotion}")

    await ensure_assets_exist(db, [req.asset_id])
    _, character = await ensure_active_character(db)
    config = _safe_load_config(character)
    full_map = _normalize_full_map(config.get("fullMap", {}))
    full_map[emo] = req.asset_id
    config["fullMap"] = full_map

    await ensure_assets_exist(db, collect_config_asset_ids(config))
    character.config_json = json.dumps(config, ensure_ascii=False)
    await upsert_legacy_avatar_map_from_full_map(db, full_map)
    await db.commit()
    await db.refresh(character)
    return await _serialize_legacy_map(db, character, full_map)


@router.delete("/bind/{emotion}")
async def unbind_avatar_map(
    emotion: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    emo = normalize_emotion(emotion, default="")
    if emo not in EMOTION_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid emotion: {emotion}")

    _, character = await ensure_active_character(db)
    config = _safe_load_config(character)
    full_map = _normalize_full_map(config.get("fullMap", {}))
    full_map[emo] = None
    config["fullMap"] = full_map

    character.config_json = json.dumps(config, ensure_ascii=False)
    await upsert_legacy_avatar_map_from_full_map(db, full_map)
    await db.commit()
    await db.refresh(character)
    return await _serialize_legacy_map(db, character, full_map)
