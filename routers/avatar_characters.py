import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.avatar_characters import (
    RENDERER_KIND,
    SCHEMA_VERSION,
    collect_config_asset_ids,
    default_character_config,
    ensure_active_character,
    ensure_assets_exist,
    normalize_character_config,
    serialize_character,
    upsert_legacy_avatar_map_from_full_map,
)
from ..database import get_db_session
from ..models import AvatarCharacter


router = APIRouter(prefix="/api/avatar-characters", tags=["avatar-characters"])


class CreateCharacterRequest(BaseModel):
    name: Optional[str] = None
    renderer_kind: str = RENDERER_KIND
    seed_from_legacy: bool = True


class UpdateCharacterConfigRequest(BaseModel):
    config: dict[str, Any]


class SetActiveCharacterRequest(BaseModel):
    character_id: str


@router.get("/")
async def list_characters(db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    runtime, _ = await ensure_active_character(db)
    rows = (
        await db.execute(select(AvatarCharacter).order_by(AvatarCharacter.created_at.asc(), AvatarCharacter.character_id.asc()))
    ).scalars().all()
    return {
        "active_character_id": runtime.active_character_id,
        "items": [
            {
                "character_id": row.character_id,
                "owner_id": row.owner_id,
                "name": row.name,
                "renderer_kind": row.renderer_kind,
                "schema_version": row.schema_version,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
    }


@router.post("/")
async def create_character(req: CreateCharacterRequest, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    runtime, active_char = await ensure_active_character(db)

    if req.seed_from_legacy:
        try:
            config = normalize_character_config(json.loads(active_char.config_json))
        except Exception:
            config = default_character_config()
    else:
        config = default_character_config()

    character = AvatarCharacter(
        character_id=uuid.uuid4().hex,
        owner_id="",
        name=(req.name or "New Character").strip() or "New Character",
        renderer_kind=(req.renderer_kind or RENDERER_KIND).strip() or RENDERER_KIND,
        schema_version=SCHEMA_VERSION,
        config_json=json.dumps(config, ensure_ascii=False),
    )
    db.add(character)
    await db.commit()
    await db.refresh(character)

    # If runtime was empty for any reason, keep it valid.
    if runtime.active_character_id is None:
        runtime.active_character_id = character.character_id
        await upsert_legacy_avatar_map_from_full_map(db, config.get("fullMap", {}))
        await db.commit()

    return await serialize_character(db, character, include_resolved=True)


@router.get("/active")
async def get_active_character(db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    runtime, active_char = await ensure_active_character(db)
    return {
        "active_character_id": runtime.active_character_id,
        "character": await serialize_character(db, active_char, include_resolved=True),
    }


@router.put("/active")
async def put_active_character(req: SetActiveCharacterRequest, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    runtime, _ = await ensure_active_character(db)
    row = (await db.execute(select(AvatarCharacter).where(AvatarCharacter.character_id == req.character_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")
    runtime.active_character_id = row.character_id
    config = default_character_config()
    try:
        config = normalize_character_config(json.loads(row.config_json))
    except Exception:
        pass
    await upsert_legacy_avatar_map_from_full_map(db, config.get("fullMap", {}))
    await db.commit()
    await db.refresh(runtime)
    await db.refresh(row)
    return {"active_character_id": runtime.active_character_id, "character": await serialize_character(db, row, include_resolved=True)}


@router.get("/{character_id}")
async def get_character(character_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    await ensure_active_character(db)
    row = (await db.execute(select(AvatarCharacter).where(AvatarCharacter.character_id == character_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")
    return await serialize_character(db, row, include_resolved=True)


@router.put("/{character_id}/config")
async def put_character_config(
    character_id: str, req: UpdateCharacterConfigRequest, db: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    runtime, _ = await ensure_active_character(db)
    row = (await db.execute(select(AvatarCharacter).where(AvatarCharacter.character_id == character_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")

    try:
        normalized = normalize_character_config(req.config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await ensure_assets_exist(db, collect_config_asset_ids(normalized))
    row.config_json = json.dumps(normalized, ensure_ascii=False)
    row.schema_version = SCHEMA_VERSION

    if runtime.active_character_id == row.character_id:
        await upsert_legacy_avatar_map_from_full_map(db, normalized.get("fullMap", {}))

    await db.commit()
    await db.refresh(row)
    return await serialize_character(db, row, include_resolved=True)


@router.delete("/{character_id}")
async def delete_character(character_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    runtime, _ = await ensure_active_character(db)
    if runtime.active_character_id == character_id:
        raise HTTPException(status_code=400, detail="Cannot delete active character")
    row = (await db.execute(select(AvatarCharacter).where(AvatarCharacter.character_id == character_id))).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Character not found")
    await db.delete(row)
    await db.commit()
    return {"status": "ok"}
