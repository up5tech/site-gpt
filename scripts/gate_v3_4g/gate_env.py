"""Shared setup for the V3-4G gate scripts.

Importing this module points `DATABASE_URL` at the throwaway gate database
*before* `site_gpt` is imported, because the app builds its engine at import
time. The base URL comes from `GATE_DATABASE_URL` or `DATABASE_URL` (loaded from
`.env` when the environment does not carry one); only the database name is
swapped, so the credentials are never copied into this file.

The state file `scripts/gate_v3_4g/.state/smoke.json` carries the account the
HTTP smoke created (email, password, website/company id) to the enforce and
Redis steps, which run in fresh processes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(__file__).resolve().parent / ".state"
STATE_FILE = STATE_DIR / "smoke.json"
GATE_DB = os.getenv("GATE_DB", "v3_gate_4g")


def gate_database_url() -> str:
    """The base connection URL with only the database name replaced."""
    dotenv.load_dotenv(ROOT / ".env")
    base = os.environ.get("GATE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not base:
        raise SystemExit("set GATE_DATABASE_URL or DATABASE_URL (or a .env with one)")
    prefix, current = base.rsplit("/", 1)
    if not current:
        raise SystemExit(f"unexpected DATABASE_URL shape: {prefix}/")
    return f"{prefix}/{GATE_DB}"


os.environ["DATABASE_URL"] = gate_database_url()


def save_state(**values) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(values, indent=2, default=str))
    print(f"state written to {STATE_FILE.relative_to(ROOT)}")


def load_state() -> dict:
    if not STATE_FILE.exists():
        raise SystemExit(
            f"{STATE_FILE.relative_to(ROOT)} is missing — run 02_http_smoke.py first"
        )
    return json.loads(STATE_FILE.read_text())
