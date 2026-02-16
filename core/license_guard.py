import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ModelLicenseAcceptance

DEFAULT_LICENSE_ALLOWLIST = [
    "Apache-2.0",
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MPL-2.0",
    "LGPL-3.0",
    "GPL-3.0",
    "AGPL-3.0",
]


def normalize_license(value: str | None) -> str:
    return str(value or "").strip()


def get_license_allowlist(config: dict | None) -> list[str]:
    if not isinstance(config, dict):
        return list(DEFAULT_LICENSE_ALLOWLIST)

    downloader = config.get("model_downloader", {})
    if not isinstance(downloader, dict):
        return list(DEFAULT_LICENSE_ALLOWLIST)

    raw = downloader.get("license_allowlist", DEFAULT_LICENSE_ALLOWLIST)
    if not isinstance(raw, list):
        return list(DEFAULT_LICENSE_ALLOWLIST)

    allowlist: list[str] = []
    for item in raw:
        v = normalize_license(str(item))
        if v:
            allowlist.append(v)

    if not allowlist:
        return list(DEFAULT_LICENSE_ALLOWLIST)

    return allowlist


def is_license_allowed(license_spdx: str | None, allowlist: Iterable[str]) -> bool:
    license_norm = normalize_license(license_spdx).lower()
    if not license_norm:
        return False
    allow_norm = {normalize_license(x).lower() for x in allowlist if normalize_license(x)}
    return license_norm in allow_norm


async def has_license_acceptance(db: AsyncSession, source_id: str, license_spdx: str) -> bool:
    stmt = select(ModelLicenseAcceptance).where(
        ModelLicenseAcceptance.source_id == source_id,
        ModelLicenseAcceptance.license_spdx == normalize_license(license_spdx),
    )
    row = (await db.execute(stmt)).scalars().first()
    return row is not None


async def accept_license(db: AsyncSession, source_id: str, license_spdx: str) -> ModelLicenseAcceptance:
    normalized = normalize_license(license_spdx)
    stmt = select(ModelLicenseAcceptance).where(
        ModelLicenseAcceptance.source_id == source_id,
        ModelLicenseAcceptance.license_spdx == normalized,
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing is not None:
        return existing

    row = ModelLicenseAcceptance(
        acceptance_id=uuid.uuid4().hex,
        source_id=source_id,
        license_spdx=normalized,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
