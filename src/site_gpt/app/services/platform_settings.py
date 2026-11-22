"""The typed, non-secret global settings allowlist (V5 F5, V5-43, D12).

An operator may change only the keys in `REGISTRY`, and only within their
declared type. Deployment configuration stays authoritative for everything else:
there is no way to read or write a secret, a database URL, an auth setting, a
CORS origin or a destructive retention value through this module. `core.config`
is not scanned, imported dynamically or enumerated — adding a key here is an
explicit, reviewed code change.

Rows in `platform_settings` are overrides; an absent row means the safe default.
Values are display-only on purpose while D12 is unapproved: they surface in the
public marketing shell and cannot alter authentication, billing enforcement or
data deletion. Every write is audited by the API layer.
"""

import re
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

from site_gpt.app import models

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SettingError(Exception):
    """A settings request that must not proceed, with the HTTP answer to send."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class SettingSpec:
    """One allowlisted key and the only shape its value may take."""

    key: str
    label: str
    description: str
    default: Any
    kind: str = "string"
    max_length: int = 0
    allow_blank: bool = True
    high_impact: bool = False


#: The complete writable surface. Display-only values: no auth, network, secret
#: or billing-enforcement key belongs here (D12).
REGISTRY: Mapping[str, SettingSpec] = {
    "public_status_message": SettingSpec(
        key="public_status_message",
        label="Public status message",
        description=(
            "Optional announcement shown on the marketing pages. Leave blank "
            "to hide it."
        ),
        default="",
        max_length=280,
        allow_blank=True,
    ),
    "support_contact_email": SettingSpec(
        key="support_contact_email",
        label="Support contact email",
        description=(
            "Address shown in the public footer. Leave blank to hide it."
        ),
        default="",
        max_length=254,
        allow_blank=True,
    ),
}

PUBLIC_KEYS = ("public_status_message", "support_contact_email")


def spec(key: str) -> SettingSpec:
    item = REGISTRY.get((key or "").strip())
    if item is None:
        raise SettingError(404, "Unknown setting")
    return item


def validate(key: str, value: Any) -> Any:
    """Return the normalized value or raise `SettingError(400)`.

    Only strings are allowed in this allowlist; the shape is checked before a
    row is written so an operator typo cannot become runtime state.
    """
    item = spec(key)
    if item.kind != "string" or not isinstance(value, str):
        raise SettingError(400, f"{item.label} must be text.")
    text = value.strip()
    if not text and not item.allow_blank:
        raise SettingError(400, f"{item.label} cannot be blank.")
    if item.max_length and len(text) > item.max_length:
        raise SettingError(
            400, f"{item.label} is limited to {item.max_length} characters."
        )
    if key == "support_contact_email" and text and not EMAIL_RE.match(text):
        raise SettingError(400, "Support contact email is not a valid address.")
    return text


def _row(db: Session, key: str) -> models.PlatformSetting | None:
    return (
        db.query(models.PlatformSetting)
        .filter(models.PlatformSetting.key == key)
        .first()
    )


def get_value(db: Session, key: str) -> Any:
    """The effective value: the stored override, else the safe default."""
    item = spec(key)
    row = _row(db, key)
    return row.value if row is not None else item.default


def public_config(db: Session) -> dict[str, str]:
    """The public display values, with defaults for anything unset."""
    return {
        "status_message": get_value(db, "public_status_message") or "",
        "support_email": get_value(db, "support_contact_email") or "",
    }


def entries(db: Session) -> list[dict]:
    """Every allowlisted key with its current and default value."""
    result = []
    for key, item in REGISTRY.items():
        row = _row(db, key)
        result.append(
            {
                "key": key,
                "label": item.label,
                "description": item.description,
                "kind": item.kind,
                "max_length": item.max_length,
                "default": item.default,
                "value": row.value if row is not None else item.default,
                "is_override": row is not None,
                "high_impact": item.high_impact,
                "updated_at": row.updated_at if row is not None else None,
                "updated_by_user_id": (
                    row.updated_by_user_id if row is not None else None
                ),
            }
        )
    return result


def preview(db: Session, key: str, value: Any) -> dict:
    """Validate a proposed value without writing it."""
    normalized = validate(key, value)
    return {
        "key": key,
        "current": get_value(db, key),
        "next": normalized,
        "changed": normalized != get_value(db, key),
    }


def set_value(
    db: Session,
    key: str,
    value: Any,
    *,
    actor_user_id=None,
    commit: bool = True,
) -> tuple[models.PlatformSetting, Any]:
    """Upsert one allowlisted value; returns `(row, previous_value)`.

    The caller writes the audit row in the same transaction (`commit=False`) so
    a change cannot be stored without its trail.
    """
    normalized = validate(key, value)
    previous = get_value(db, key)
    row = _row(db, key)
    if row is None:
        row = models.PlatformSetting(
            key=key, value=normalized, updated_by_user_id=actor_user_id
        )
        db.add(row)
    else:
        row.value = normalized
        row.updated_by_user_id = actor_user_id
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row, previous
