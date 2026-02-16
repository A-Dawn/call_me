import json
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.avatar_characters import normalize_character_config
from ..database import get_db_session
from ..models import Asset, AvatarCharacter, AvatarMap
from ..core.emotion import extract_emotion_from_tags_json


router = APIRouter(prefix="/api/assets", tags=["assets"])


def _assets_dir() -> str:
    # Keep assets inside plugin folder so tests are hermetic.
    base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "assets", "uploaded")
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def _asset_url(asset_id: str) -> str:
    return f"/api/assets/{asset_id}/file"


def _asset_to_dict(a: Asset) -> dict[str, Any]:
    return {
        "asset_id": a.asset_id,
        "owner_id": a.owner_id,
        "path": a.path,
        "url": _asset_url(a.asset_id),
        "kind": a.kind,
        "tags_json": a.tags_json,
        "emotion": extract_emotion_from_tags_json(a.tags_json),
        "width": a.width,
        "height": a.height,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    kind: str = Form(...),
    tags: str = Form("[]"),
    owner_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Upload a new asset (image).

    Test expectation:
    - POST /api/assets/upload returns JSON with key: asset_id
    """

    try:
        # Validate tags is JSON (usually a list)
        json.loads(tags)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid tags JSON")

    asset_id = uuid.uuid4().hex

    filename = file.filename or "upload.bin"
    _, ext = os.path.splitext(filename)
    if not ext:
        ext = ".bin"
    rel_path = os.path.join("static", "assets", "uploaded", f"{asset_id}{ext}")
    abs_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    content = await file.read()
    with open(abs_path, "wb") as f:
        f.write(content)

    asset = Asset(
        asset_id=asset_id,
        owner_id=owner_id or "",
        path=rel_path.replace("\\", "/"),
        kind=kind,
        tags_json=tags,
        width=None,
        height=None,
    )
    db.add(asset)
    await db.commit()

    return _asset_to_dict(asset)


@router.get("/")
async def list_assets(
    kind: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """List assets.

    Test expectation:
    - GET /api/assets/ returns a JSON list
    - Last element has matching asset_id after upload
    """

    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    if page_size > 100:
        page_size = 100

    stmt = select(Asset)
    if kind:
        stmt = stmt.where(Asset.kind == kind)
    # Stable order for tests.
    stmt = stmt.order_by(Asset.created_at.asc(), Asset.asset_id.asc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()

    return [_asset_to_dict(a) for a in rows]


@router.get("/{asset_id}/file")
async def get_asset_file(asset_id: str, db: AsyncSession = Depends(get_db_session)):
    stmt = select(Asset).where(Asset.asset_id == asset_id)
    asset = (await db.execute(stmt)).scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    abs_path = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), asset.path))
    base_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"))
    if not abs_path.startswith(base_dir):
        raise HTTPException(status_code=400, detail="Invalid asset path")
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="Asset file missing")

    return FileResponse(abs_path)


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    stmt = select(Asset).where(Asset.asset_id == asset_id)
    asset = (await db.execute(stmt)).scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Best-effort file cleanup.
    try:
        abs_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), asset.path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        pass

    await db.delete(asset)

    # Remove dangling references from avatar maps.
    maps = (await db.execute(select(AvatarMap))).scalars().all()
    for m in maps:
        changed = False
        try:
            mapping = json.loads(m.mapping_json or "{}")
        except Exception:
            mapping = {}
        if isinstance(mapping, dict):
            for k in list(mapping.keys()):
                if mapping.get(k) == asset_id:
                    del mapping[k]
                    changed = True
        if changed:
            m.mapping_json = json.dumps(mapping, ensure_ascii=False)

    # Remove dangling references from avatar characters.
    characters = (await db.execute(select(AvatarCharacter))).scalars().all()
    for c in characters:
        changed = False
        try:
            config = normalize_character_config(json.loads(c.config_json or "{}"))
        except Exception:
            continue

        full_map = config.get("fullMap", {})
        if isinstance(full_map, dict):
            for emo in list(full_map.keys()):
                if full_map.get(emo) == asset_id:
                    full_map[emo] = None
                    changed = True

        parts = config.get("parts", [])
        if isinstance(parts, list):
            next_parts = [p for p in parts if not (isinstance(p, dict) and p.get("asset_id") == asset_id)]
            if len(next_parts) != len(parts):
                config["parts"] = next_parts
                changed = True

        if changed:
            c.config_json = json.dumps(config, ensure_ascii=False)

    await db.commit()
    return {"status": "ok"}
