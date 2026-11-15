"""Typed reads of per-company settings for feature code.

`api/setting.py` owns the registry and the HTTP surface; this module is the one
place features read a stored value, so a missing row, an empty string and a
malformed flag behave identically everywhere. Booleans are stored as strings
("true"/"false"), exactly like the environment flags.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from site_gpt.app import models

TRUE_VALUES = ("1", "true", "yes", "on")


def values(
    db: Session, company_id: UUID, keys: tuple[str, ...] | list[str]
) -> dict[str, str]:
    """Every requested key this company has a row for (one query)."""
    rows = (
        db.query(models.Setting.key, models.Setting.value)
        .filter(
            models.Setting.company_id == company_id,
            models.Setting.key.in_(keys),
        )
        .all()
    )
    return {key: value for key, value in rows}


def value(db: Session, company_id: UUID, key: str, default: str = "") -> str:
    """The stored value, or `default` when the company has no row."""
    found = values(db, company_id, (key,)).get(key)
    return default if found is None else found


def flag(db: Session, company_id: UUID, key: str) -> bool:
    """True only for an explicitly truthy value; unset means off."""
    return value(db, company_id, key, "false").strip().lower() in TRUE_VALUES


def emails(db: Session, company_id: UUID, configured: str) -> list[str]:
    """Recipients from a comma/semicolon separated setting.

    Empty means "not configured"; callers decide the fallback (team members for
    handoff, active admins for the digest).
    """
    return [
        part.strip()
        for part in (configured or "").replace(";", ",").split(",")
        if part.strip()
    ]
