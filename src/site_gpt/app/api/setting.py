from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.core.config import (
    DAILY_MESSAGE_LIMIT,
    DEFAULT_WIDGET_LANGUAGE,
    SESSION_MESSAGE_LIMIT,
)
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.setting import SettingRes
from site_gpt.app.services.quota import parse_limit

router = APIRouter()

# Single source of truth for the default per-company settings. Both the
# registration flow (`_default_setting_rows`) and `POST /api/settings` derive
# from this dict so new keys only have to be added in one place.
DEFAULT_SETTINGS: dict[str, str] = {
    "assistant_name": "Site GPT",
    "widget_header_color": "#4c74af",
    "widget_footer_color": "#4c74af",
    "widget_position": "bottom-right",
    "greeting_message": "Hi 👋 How can I help you?",
    "placeholder_text": "Type a message...",
    "suggested_questions": "",
    # V2 widget-facing keys (plans/SPEC.md §9). Public by decision: they describe
    # how the visitor's own widget looks and behaves, never internal state.
    # Seed value for new companies. `DEFAULT_WIDGET_LANGUAGE` (env) lets a
    # deployment pick the fallback the widget uses when it cannot detect the
    # visitor's browser language; `auto` follows the browser.
    "widget_language": DEFAULT_WIDGET_LANGUAGE,
    "widget_ui_strings": "",
    "widget_logo_url": "",
    "handoff_enabled": "false",
    "handoff_label": "Talk to a human",
    "require_consent": "false",
    "privacy_policy_url": "",
}

# Internal per-company settings. They describe backend behaviour rather than the
# widget's appearance, so they are seeded like the rest but never published by
# the public `GET /api/widget-config`.
INTERNAL_SETTINGS: dict[str, str] = {
    # Messages this company's websites may answer per UTC day. Seeded with the
    # env default; clearing the row (or an old company without it) also falls
    # back to that env value.
    "daily_message_limit": str(DAILY_MESSAGE_LIMIT),
    # V2 server-side keys (plans/SPEC.md §9). They stay here permanently: none of
    # them may be readable by an unauthenticated visitor.
    #
    # Chat model override: a short catalogue label resolved to a
    # (provider, model) pair server-side, never a raw model name from a client.
    "llm_provider": "",
    "llm_model": "",
    # Where handoff requests are emailed (F5).
    "handoff_email": "",
    # Weekly digest (F6). Booleans are stored as strings, like the env flags.
    "digest_enabled": "false",
    "digest_hour": "9",
    "digest_day": "monday",
    "digest_recipients": "",
    # How long visitor data is kept, in days (F9). "0" means "keep for ever",
    # which is the behaviour of every company created before the setting
    # existed. The worker's retention job deletes rows older than this from
    # `chat_messages`, `chat_feedback`, `handoff_requests`, `contacts` and
    # `digest_log`; see `services/retention.py`.
    "retention_days": "0",
    # V3-03 scaffolding (registry only; wired in Waves 3-4). All off by
    # default so V2.1 behaviour is unchanged until a company opts in.
    "topic_clustering_enabled": "false",  # F2: LLM topic clustering
    "topic_cluster_count": "5",  # F2: max named clusters per window
    "live_inbox_enabled": "false",  # F3: live-agent inbox
    # V4-02 scaffolding (registry only; each feature is wired in its own wave).
    # Off by default, so an untouched company behaves exactly like tag `v3`.
    "session_message_limit": str(SESSION_MESSAGE_LIMIT),  # F4: per-session cap
    "sitemap_scan_enabled": "false",  # F4: daily sitemap diff scan
    "conversation_insights_enabled": "false",  # F2: per-conversation insights
}

# Every setting a company can have: seeded on register, accepted by
# `POST /api/settings`, and validated by the same helpers.
ALL_SETTINGS: dict[str, str] = {**DEFAULT_SETTINGS, **INTERNAL_SETTINGS}

# Only these keys are exposed by the public, unauthenticated
# `GET /api/widget-config`. Deliberately an explicit literal tuple instead of
# `tuple(DEFAULT_SETTINGS)`: registering a settings row must never make it
# public by accident. Extend this only as a deliberate product decision, adding
# the key to `DEFAULT_SETTINGS` in the same commit.
WIDGET_PUBLIC_KEYS: tuple[str, ...] = (
    # 7 V1 appearance keys
    "assistant_name",
    "widget_header_color",
    "widget_footer_color",
    "widget_position",
    "greeting_message",
    "placeholder_text",
    "suggested_questions",
    # 7 V2 widget-facing keys (SPEC.md §9)
    "widget_language",
    "widget_ui_strings",
    "widget_logo_url",
    "handoff_enabled",
    "handoff_label",
    "require_consent",
    "privacy_policy_url",
)


def _default_setting_rows(company_id):
    """Build the default Setting rows for a newly created company."""
    return [
        models.Setting(key=key, value=value, company_id=company_id)
        for key, value in ALL_SETTINGS.items()
    ]


def company_setting(db: Session, company_id, key: str) -> str | None:
    """One company's raw setting value, or None when the row is absent."""
    row = (
        db.query(models.Setting)
        .filter(
            models.Setting.company_id == company_id,
            models.Setting.key == key,
        )
        .first()
    )
    return row.value if row is not None else None


def apply_settings(
    db: Session, company_id, pairs: list[tuple[str, str]]
) -> int:
    """Upsert `(key, value)` rows for one company; returns how many were written.

    Shared by the admin `PUT /api/settings` and `PUT /api/v1/settings`, so the
    upsert (and its "create the row for an older company" behaviour) exists once.
    """
    if not pairs:
        return 0
    existing = {
        row.key: row
        for row in db.query(models.Setting)
        .filter(
            models.Setting.company_id == company_id,
            models.Setting.key.in_([key for key, _ in pairs]),
        )
        .all()
    }
    for key, value in pairs:
        row = existing.get(key)
        if row is not None:
            row.value = value
        else:
            # Upsert so companies created before a key existed can still store
            # it (e.g. widget_position, greeting_message, widget_language).
            db.add(models.Setting(key=key, value=value, company_id=company_id))
    db.commit()
    return len(pairs)


def company_daily_message_limit(db: Session, company_id) -> int:
    """This company's daily message ceiling per website.

    A company created before the setting existed has no row, so the env value
    (`DAILY_MESSAGE_LIMIT`) remains the default.
    """
    return parse_limit(
        company_setting(db, company_id, "daily_message_limit"),
        default=DAILY_MESSAGE_LIMIT,
    )


def company_session_message_limit(db: Session, company_id) -> int:
    """This company's per-session message ceiling (V4 F4, D6).

    A missing row falls back to `SESSION_MESSAGE_LIMIT`, `0` disables the cap,
    and a typo or negative value falls back to the default through `parse_limit`
    — the `company_daily_message_limit` rules, deliberately identical.
    """
    return parse_limit(
        company_setting(db, company_id, "session_message_limit"),
        default=SESSION_MESSAGE_LIMIT,
    )


@router.get("/")
def get_settings(
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    query = (
        db.query(models.Setting)
        .filter(models.Setting.company_id == user.company_id)
        .all()
    )
    return [SettingRes.model_validate(q, from_attributes=True) for q in query]


@router.put("/")
def update_settings(
    settings: list[SettingRes],
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    apply_settings(
        db, user.company_id, [(setting.key, setting.value) for setting in settings]
    )
    return {"message": "Settings updated successfully"}


@router.post("/")
def create_settings(
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    """Seed missing default settings rows — idempotent.

    Only keys the company does not have yet are inserted, so repeated calls
    never stack duplicate rows. Existing values are left untouched.
    """
    existing_keys = {
        key
        for (key,) in db.query(models.Setting.key)
        .filter(models.Setting.company_id == user.company_id)
        .all()
    }
    missing = [
        models.Setting(key=key, value=value, company_id=user.company_id)
        for key, value in ALL_SETTINGS.items()
        if key not in existing_keys
    ]
    if missing:
        db.add_all(missing)
        db.commit()
    return {
        "created": len(missing),
        "skipped": len(ALL_SETTINGS) - len(missing),
    }
