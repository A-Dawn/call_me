import json
import uuid
from typing import Any, Dict, Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Asset, AvatarCharacter, AvatarMap, AvatarRuntime
from .emotion import EMOTION_TYPES, normalize_emotion


RUNTIME_ID = "default"
LEGACY_MAP_ID = "default"
SCHEMA_VERSION = "1.0"
RENDERER_KIND = "dom2d"

PART_SLOTS = {
    "body_base",
    "eyes_open",
    "eyes_closed",
    "mouth_closed",
    "mouth_half",
    "mouth_open",
    "brow_neutral",
    "brow_happy",
    "brow_sad",
    "brow_angry",
    "fx_blush",
    "fx_sweat",
}
PART_EMOTIONS = {"all", *EMOTION_TYPES}
HIT_SHAPES = {"rect"}
REACTION_TARGETS = {"global"}
REACTION_PROPS = {"translateX", "translateY", "rotateDeg", "scale"}


def default_hit_areas() -> list[dict[str, Any]]:
    return [
        {"id": "head", "label": "头顶", "shape": "rect", "x": 0.33, "y": 0.04, "w": 0.34, "h": 0.18, "reaction_id": "pat_head", "enabled": True},
        {
            "id": "face_left",
            "label": "左脸",
            "shape": "rect",
            "x": 0.22,
            "y": 0.20,
            "w": 0.20,
            "h": 0.20,
            "reaction_id": "tap_face",
            "enabled": True,
        },
        {
            "id": "face_right",
            "label": "右脸",
            "shape": "rect",
            "x": 0.58,
            "y": 0.20,
            "w": 0.20,
            "h": 0.20,
            "reaction_id": "tap_face",
            "enabled": True,
        },
        {
            "id": "chest",
            "label": "胸口",
            "shape": "rect",
            "x": 0.36,
            "y": 0.42,
            "w": 0.28,
            "h": 0.24,
            "reaction_id": "tap_chest",
            "enabled": True,
        },
    ]


def default_reactions() -> list[dict[str, Any]]:
    return [
        {
            "id": "pat_head",
            "label": "摸头",
            "cooldown_ms": 800,
            "timeline": [
                {"target": "global", "prop": "translateY", "t": 0, "v": 0},
                {"target": "global", "prop": "translateY", "t": 120, "v": -8},
                {"target": "global", "prop": "translateY", "t": 260, "v": 0},
            ],
        },
        {
            "id": "tap_face",
            "label": "戳脸",
            "cooldown_ms": 650,
            "timeline": [
                {"target": "global", "prop": "translateX", "t": 0, "v": 0},
                {"target": "global", "prop": "translateX", "t": 90, "v": 4},
                {"target": "global", "prop": "translateX", "t": 180, "v": 0},
            ],
        },
        {
            "id": "tap_chest",
            "label": "轻触",
            "cooldown_ms": 650,
            "timeline": [
                {"target": "global", "prop": "scale", "t": 0, "v": 1.0},
                {"target": "global", "prop": "scale", "t": 120, "v": 1.015},
                {"target": "global", "prop": "scale", "t": 240, "v": 1.0},
            ],
        },
    ]


def default_character_config() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "canvas": {"width": 1080, "height": 1440},
        "fullMap": {emo: None for emo in EMOTION_TYPES},
        "parts": [],
        "hitAreas": default_hit_areas(),
        "reactions": default_reactions(),
        "motions": {
            "idle_blink": {"enabled": True, "min_gap_ms": 2200, "max_gap_ms": 5200, "close_ms": 110},
            "idle_breath": {"enabled": True, "amp_px": 4.0, "period_ms": 2400},
            "idle_sway": {"enabled": True, "deg": 1.0, "period_ms": 4200},
            "speaking_lipsync": {"enabled": True, "sensitivity": 1.0, "smooth_ms": 90},
        },
    }


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        out = int(value)
    except Exception:
        out = default
    if minimum is not None and out < minimum:
        out = minimum
    if maximum is not None and out > maximum:
        out = maximum
    return out


def _as_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        out = float(value)
    except Exception:
        out = default
    if minimum is not None and out < minimum:
        out = minimum
    if maximum is not None and out > maximum:
        out = maximum
    return out


def _as_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def normalize_character_config(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("config must be an object")

    defaults = default_character_config()
    out: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "canvas": {
            "width": _as_int(raw.get("canvas", {}).get("width") if isinstance(raw.get("canvas"), dict) else None, 1080, 256, 4096),
            "height": _as_int(raw.get("canvas", {}).get("height") if isinstance(raw.get("canvas"), dict) else None, 1440, 256, 4096),
        },
    }

    full_raw = raw.get("fullMap")
    if full_raw is None:
        full_raw = defaults["fullMap"]
    if not isinstance(full_raw, dict):
        raise ValueError("fullMap must be an object")
    full_map: dict[str, str | None] = {}
    for emo in EMOTION_TYPES:
        value = full_raw.get(emo)
        full_map[emo] = value.strip() if isinstance(value, str) and value.strip() else None
    out["fullMap"] = full_map

    parts_raw = raw.get("parts", [])
    if not isinstance(parts_raw, list):
        raise ValueError("parts must be a list")
    parts: list[dict[str, Any]] = []
    for idx, item in enumerate(parts_raw):
        if not isinstance(item, dict):
            raise ValueError(f"parts[{idx}] must be an object")
        slot = _as_non_empty_str(item.get("slot"), f"parts[{idx}].slot")
        if slot not in PART_SLOTS:
            raise ValueError(f"parts[{idx}].slot is invalid")
        emotion = normalize_emotion(str(item.get("emotion", "all")), default="")
        if item.get("emotion") == "all":
            emotion = "all"
        if not emotion:
            emotion = "all"
        if emotion not in PART_EMOTIONS:
            raise ValueError(f"parts[{idx}].emotion is invalid")
        part = {
            "part_id": _as_non_empty_str(item.get("part_id", uuid.uuid4().hex), f"parts[{idx}].part_id"),
            "slot": slot,
            "emotion": emotion,
            "asset_id": _as_non_empty_str(item.get("asset_id"), f"parts[{idx}].asset_id"),
            "z": _as_int(item.get("z"), 0, -9999, 9999),
            "anchor_x": _as_float(item.get("anchor_x"), 0.5, -2.0, 2.0),
            "anchor_y": _as_float(item.get("anchor_y"), 1.0, -2.0, 2.0),
            "offset_x": _as_float(item.get("offset_x"), 0.0, -4096, 4096),
            "offset_y": _as_float(item.get("offset_y"), 0.0, -4096, 4096),
            "scale": _as_float(item.get("scale"), 1.0, 0.01, 8.0),
            "rotate_deg": _as_float(item.get("rotate_deg"), 0.0, -360.0, 360.0),
            "opacity": _as_float(item.get("opacity"), 1.0, 0.0, 1.0),
            "enabled": _as_bool(item.get("enabled"), True),
        }
        parts.append(part)
    parts.sort(key=lambda x: (x["z"], x["part_id"]))
    out["parts"] = parts

    hit_raw = raw.get("hitAreas")
    if hit_raw is None:
        hit_raw = defaults["hitAreas"]
    if not isinstance(hit_raw, list):
        raise ValueError("hitAreas must be a list")
    hit_areas: list[dict[str, Any]] = []
    for idx, item in enumerate(hit_raw):
        if not isinstance(item, dict):
            raise ValueError(f"hitAreas[{idx}] must be an object")
        shape = str(item.get("shape", "rect")).strip().lower() or "rect"
        if shape not in HIT_SHAPES:
            raise ValueError(f"hitAreas[{idx}].shape is invalid")
        hit = {
            "id": _as_non_empty_str(item.get("id"), f"hitAreas[{idx}].id"),
            "label": str(item.get("label", item.get("id", "区域"))),
            "shape": shape,
            "x": _as_float(item.get("x"), 0.0, 0.0, 1.0),
            "y": _as_float(item.get("y"), 0.0, 0.0, 1.0),
            "w": _as_float(item.get("w"), 0.1, 0.01, 1.0),
            "h": _as_float(item.get("h"), 0.1, 0.01, 1.0),
            "reaction_id": str(item.get("reaction_id", "")).strip(),
            "enabled": _as_bool(item.get("enabled"), True),
        }
        hit_areas.append(hit)
    out["hitAreas"] = hit_areas

    reaction_raw = raw.get("reactions")
    if reaction_raw is None:
        reaction_raw = defaults["reactions"]
    if not isinstance(reaction_raw, list):
        raise ValueError("reactions must be a list")
    reactions: list[dict[str, Any]] = []
    for idx, item in enumerate(reaction_raw):
        if not isinstance(item, dict):
            raise ValueError(f"reactions[{idx}] must be an object")
        timeline_raw = item.get("timeline", [])
        if not isinstance(timeline_raw, list):
            raise ValueError(f"reactions[{idx}].timeline must be a list")
        timeline: list[dict[str, Any]] = []
        for tidx, step in enumerate(timeline_raw):
            if not isinstance(step, dict):
                raise ValueError(f"reactions[{idx}].timeline[{tidx}] must be an object")
            target = str(step.get("target", "global")).strip() or "global"
            if target not in REACTION_TARGETS:
                raise ValueError(f"reactions[{idx}].timeline[{tidx}].target is invalid")
            prop = str(step.get("prop", "")).strip()
            if prop not in REACTION_PROPS:
                raise ValueError(f"reactions[{idx}].timeline[{tidx}].prop is invalid")
            timeline.append(
                {
                    "target": target,
                    "prop": prop,
                    "t": _as_int(step.get("t"), 0, 0, 60000),
                    "v": _as_float(step.get("v"), 0.0, -4096.0, 4096.0),
                }
            )
        timeline.sort(key=lambda x: x["t"])
        reactions.append(
            {
                "id": _as_non_empty_str(item.get("id"), f"reactions[{idx}].id"),
                "label": str(item.get("label", item.get("id", "反馈"))),
                "cooldown_ms": _as_int(item.get("cooldown_ms"), 800, 0, 60000),
                "timeline": timeline,
            }
        )
    out["reactions"] = reactions

    motion_defaults = defaults["motions"]
    motion_raw = raw.get("motions", {})
    if not isinstance(motion_raw, dict):
        raise ValueError("motions must be an object")
    out["motions"] = {
        "idle_blink": {
            "enabled": _as_bool(motion_raw.get("idle_blink", {}).get("enabled") if isinstance(motion_raw.get("idle_blink"), dict) else None, motion_defaults["idle_blink"]["enabled"]),
            "min_gap_ms": _as_int(motion_raw.get("idle_blink", {}).get("min_gap_ms") if isinstance(motion_raw.get("idle_blink"), dict) else None, motion_defaults["idle_blink"]["min_gap_ms"], 400, 10000),
            "max_gap_ms": _as_int(motion_raw.get("idle_blink", {}).get("max_gap_ms") if isinstance(motion_raw.get("idle_blink"), dict) else None, motion_defaults["idle_blink"]["max_gap_ms"], 400, 15000),
            "close_ms": _as_int(motion_raw.get("idle_blink", {}).get("close_ms") if isinstance(motion_raw.get("idle_blink"), dict) else None, motion_defaults["idle_blink"]["close_ms"], 40, 1200),
        },
        "idle_breath": {
            "enabled": _as_bool(motion_raw.get("idle_breath", {}).get("enabled") if isinstance(motion_raw.get("idle_breath"), dict) else None, motion_defaults["idle_breath"]["enabled"]),
            "amp_px": _as_float(motion_raw.get("idle_breath", {}).get("amp_px") if isinstance(motion_raw.get("idle_breath"), dict) else None, motion_defaults["idle_breath"]["amp_px"], 0.0, 64.0),
            "period_ms": _as_int(motion_raw.get("idle_breath", {}).get("period_ms") if isinstance(motion_raw.get("idle_breath"), dict) else None, motion_defaults["idle_breath"]["period_ms"], 200, 20000),
        },
        "idle_sway": {
            "enabled": _as_bool(motion_raw.get("idle_sway", {}).get("enabled") if isinstance(motion_raw.get("idle_sway"), dict) else None, motion_defaults["idle_sway"]["enabled"]),
            "deg": _as_float(motion_raw.get("idle_sway", {}).get("deg") if isinstance(motion_raw.get("idle_sway"), dict) else None, motion_defaults["idle_sway"]["deg"], 0.0, 25.0),
            "period_ms": _as_int(motion_raw.get("idle_sway", {}).get("period_ms") if isinstance(motion_raw.get("idle_sway"), dict) else None, motion_defaults["idle_sway"]["period_ms"], 200, 20000),
        },
        "speaking_lipsync": {
            "enabled": _as_bool(motion_raw.get("speaking_lipsync", {}).get("enabled") if isinstance(motion_raw.get("speaking_lipsync"), dict) else None, motion_defaults["speaking_lipsync"]["enabled"]),
            "sensitivity": _as_float(motion_raw.get("speaking_lipsync", {}).get("sensitivity") if isinstance(motion_raw.get("speaking_lipsync"), dict) else None, motion_defaults["speaking_lipsync"]["sensitivity"], 0.1, 5.0),
            "smooth_ms": _as_int(motion_raw.get("speaking_lipsync", {}).get("smooth_ms") if isinstance(motion_raw.get("speaking_lipsync"), dict) else None, motion_defaults["speaking_lipsync"]["smooth_ms"], 0, 1000),
        },
    }

    if out["motions"]["idle_blink"]["max_gap_ms"] < out["motions"]["idle_blink"]["min_gap_ms"]:
        out["motions"]["idle_blink"]["max_gap_ms"] = out["motions"]["idle_blink"]["min_gap_ms"]

    return out


def collect_config_asset_ids(config: dict[str, Any]) -> set[str]:
    asset_ids: set[str] = set()
    full_map = config.get("fullMap", {})
    if isinstance(full_map, dict):
        for value in full_map.values():
            if isinstance(value, str) and value.strip():
                asset_ids.add(value.strip())
    parts = config.get("parts", [])
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                asset_id = part.get("asset_id")
                if isinstance(asset_id, str) and asset_id.strip():
                    asset_ids.add(asset_id.strip())
    return asset_ids


async def ensure_assets_exist(db: AsyncSession, asset_ids: Iterable[str]) -> None:
    wanted = {x.strip() for x in asset_ids if isinstance(x, str) and x.strip()}
    if not wanted:
        return
    stmt = select(Asset).where(Asset.asset_id.in_(wanted))
    rows = (await db.execute(stmt)).scalars().all()
    existing = {row.asset_id for row in rows}
    missing = sorted(wanted - existing)
    if missing:
        raise HTTPException(status_code=400, detail=f"asset not found: {missing[0]}")


def _parse_legacy_mapping(mapping_json: str | None) -> dict[str, str | None]:
    out = {emo: None for emo in EMOTION_TYPES}
    if not mapping_json:
        return out
    try:
        data = json.loads(mapping_json)
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for key, value in data.items():
        if not isinstance(value, str) or not value.strip():
            continue
        emo = normalize_emotion(str(key), default="")
        if emo in EMOTION_TYPES:
            out[emo] = value.strip()
    return out


async def _load_or_create_runtime(db: AsyncSession) -> AvatarRuntime:
    runtime = (await db.execute(select(AvatarRuntime).where(AvatarRuntime.runtime_id == RUNTIME_ID))).scalars().first()
    if runtime:
        return runtime
    runtime = AvatarRuntime(runtime_id=RUNTIME_ID, active_character_id=None)
    db.add(runtime)
    await db.flush()
    return runtime


async def _load_legacy_full_map(db: AsyncSession) -> dict[str, str | None]:
    row = (await db.execute(select(AvatarMap).where(AvatarMap.map_id == LEGACY_MAP_ID))).scalars().first()
    if not row:
        return {emo: None for emo in EMOTION_TYPES}
    return _parse_legacy_mapping(row.mapping_json)


async def upsert_legacy_avatar_map_from_full_map(db: AsyncSession, full_map: dict[str, str | None]) -> None:
    row = (await db.execute(select(AvatarMap).where(AvatarMap.map_id == LEGACY_MAP_ID))).scalars().first()
    if not row:
        row = AvatarMap(map_id=LEGACY_MAP_ID, owner_id="", name="default", mapping_json="{}")
        db.add(row)
        await db.flush()
    payload = {emo: value for emo, value in full_map.items() if isinstance(value, str) and value.strip()}
    row.mapping_json = json.dumps(payload, ensure_ascii=False)


def _safe_json_to_config(text: str | None) -> dict[str, Any]:
    if not isinstance(text, str):
        return default_character_config()
    try:
        data = json.loads(text)
    except Exception:
        return default_character_config()
    try:
        return normalize_character_config(data)
    except Exception:
        return default_character_config()


async def ensure_active_character(db: AsyncSession) -> tuple[AvatarRuntime, AvatarCharacter]:
    runtime = await _load_or_create_runtime(db)

    active_char: AvatarCharacter | None = None
    if runtime.active_character_id:
        active_char = (await db.execute(select(AvatarCharacter).where(AvatarCharacter.character_id == runtime.active_character_id))).scalars().first()

    if not active_char:
        active_char = (await db.execute(select(AvatarCharacter).order_by(AvatarCharacter.created_at.asc(), AvatarCharacter.character_id.asc()))).scalars().first()

    if not active_char:
        config = default_character_config()
        config["fullMap"].update(await _load_legacy_full_map(db))
        active_char = AvatarCharacter(
            character_id=uuid.uuid4().hex,
            owner_id="",
            name="legacy-default",
            renderer_kind=RENDERER_KIND,
            schema_version=SCHEMA_VERSION,
            config_json=json.dumps(config, ensure_ascii=False),
        )
        db.add(active_char)
        await db.flush()

    if runtime.active_character_id != active_char.character_id:
        runtime.active_character_id = active_char.character_id
    await upsert_legacy_avatar_map_from_full_map(db, _safe_json_to_config(active_char.config_json).get("fullMap", {}))
    await db.commit()
    await db.refresh(runtime)
    await db.refresh(active_char)
    return runtime, active_char


async def resolve_assets(db: AsyncSession, config: dict[str, Any]) -> dict[str, Any]:
    asset_ids = collect_config_asset_ids(config)
    assets_by_id: dict[str, Asset] = {}
    if asset_ids:
        rows = (await db.execute(select(Asset).where(Asset.asset_id.in_(asset_ids)))).scalars().all()
        assets_by_id = {row.asset_id: row for row in rows}

    full_map_resolved: dict[str, dict[str, Any] | None] = {}
    full_map = config.get("fullMap", {})
    for emo in EMOTION_TYPES:
        asset_id = full_map.get(emo) if isinstance(full_map, dict) else None
        if not asset_id:
            full_map_resolved[emo] = None
            continue
        asset = assets_by_id.get(asset_id)
        if not asset:
            full_map_resolved[emo] = {"asset_id": asset_id, "url": None, "path": None, "exists": False}
        else:
            full_map_resolved[emo] = {
                "asset_id": asset.asset_id,
                "url": f"/api/assets/{asset.asset_id}/file",
                "path": asset.path,
                "exists": True,
            }

    parts_resolved: list[dict[str, Any]] = []
    parts = config.get("parts", [])
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            asset_id = part.get("asset_id")
            asset = assets_by_id.get(asset_id) if isinstance(asset_id, str) else None
            enriched = dict(part)
            if asset:
                enriched["url"] = f"/api/assets/{asset.asset_id}/file"
                enriched["path"] = asset.path
                enriched["exists"] = True
            else:
                enriched["url"] = None
                enriched["path"] = None
                enriched["exists"] = False
            parts_resolved.append(enriched)

    return {"fullMap": full_map_resolved, "parts": parts_resolved}


async def serialize_character(db: AsyncSession, character: AvatarCharacter, include_resolved: bool = False) -> dict[str, Any]:
    config = _safe_json_to_config(character.config_json)
    payload: dict[str, Any] = {
        "character_id": character.character_id,
        "owner_id": character.owner_id,
        "name": character.name,
        "renderer_kind": character.renderer_kind,
        "schema_version": character.schema_version,
        "config": config,
        "created_at": character.created_at.isoformat() if character.created_at else None,
        "updated_at": character.updated_at.isoformat() if character.updated_at else None,
    }
    if include_resolved:
        payload["resolved"] = await resolve_assets(db, config)
    return payload
