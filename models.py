from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from .database import Base

class Asset(Base):
    __tablename__ = "assets"

    asset_id = Column(String, primary_key=True, index=True)
    owner_id = Column(String, index=True)
    path = Column(String, nullable=False)
    kind = Column(String, nullable=False) # base/mouth/eyes/brow/effect/bg/full/other
    tags_json = Column(Text, default="[]")
    width = Column(Integer)
    height = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Preset(Base):
    __tablename__ = "presets"

    preset_id = Column(String, primary_key=True, index=True)
    owner_id = Column(String, index=True)
    name = Column(String, nullable=False)
    default_mode = Column(String, default="full") # "full"|"layers"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PresetRule(Base):
    __tablename__ = "preset_rules"

    rule_id = Column(String, primary_key=True, index=True)
    preset_id = Column(String, index=True)
    priority = Column(Integer, default=100) # 越小越优先
    mode = Column(String, default="full") # "full"|"layers"
    match_json = Column(Text, default="{}") # state/emotion/content/intensity区间等
    payload_json = Column(Text, nullable=False) # full: image_asset_id; layers: layers[]
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TTSProvider(Base):
    __tablename__ = "tts_providers"

    provider_id = Column(String, primary_key=True, index=True)
    owner_id = Column(String, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False) # "sovits_http"|"external_http"|"external_ws"
    endpoint = Column(String, nullable=False)
    headers_json = Column(Text, default="{}")
    config_json = Column(Text, default="{}") # speaker_id、默认采样率等
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AvatarMap(Base):
    __tablename__ = "avatar_maps"

    map_id = Column(String, primary_key=True, index=True)  # default
    owner_id = Column(String, index=True, default="")
    name = Column(String, nullable=False, default="default")
    mapping_json = Column(Text, default="{}")  # {"neutral":"asset_id", ...}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AvatarCharacter(Base):
    __tablename__ = "avatar_characters"

    character_id = Column(String, primary_key=True, index=True)
    owner_id = Column(String, index=True, default="")
    name = Column(String, nullable=False)
    renderer_kind = Column(String, nullable=False, default="dom2d")
    schema_version = Column(String, nullable=False, default="1.0")
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AvatarRuntime(Base):
    __tablename__ = "avatar_runtime"

    runtime_id = Column(String, primary_key=True, index=True)  # default
    active_character_id = Column(String, index=True, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
