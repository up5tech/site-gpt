#!/usr/bin/env python
"""V6-11 emergency disable/recovery exercise for the platform-owner boundary.

Run from the repo root:

    uv run python scripts/exercise_platform_disable.py

It creates a throwaway SQLite database in a temporary directory (and removes it
afterwards), then proves the operator half of D5 end to end, using the real
out-of-band CLI:

1. `APP_ENV=production` refuses to boot with `PLATFORM_CONSOLE_ENABLED=true`
   unless `OPERATOR_ALLOWED_NETWORKS` is a valid, non-blanket list (the
   V6-11 rule since D5 was reopened on 2026-11-27), naming only that setting.
2. With the switch off, every `/api/platform` route answers 404 — to a granted
   operator and to a tenant admin — and an alternate `Host`,
   `X-Forwarded-Host`, `X-Forwarded-Proto` or `Origin` changes nothing.
3. With it on, the granted operator is allowed and a tenant admin is refused.
4. `scripts/platform_owner.py revoke` takes effect on the very next request,
   with no restart, and `list` reports no active grant.
5. Re-granting restores access (recovery) without touching the switch.
6. Turning the switch back off hides the surface again and leaves grants, audit
   rows and grant history intact.

Exit code 0 means every check passed. No other database, Redis, provider or
network call is involved: `DATABASE_URL` is overridden for this process and for
the CLI subprocesses it starts.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

OWNER_EMAIL = "ops@v6-11.test"
ADMIN_EMAIL = "admin@v6-11.test"

# A complete and otherwise valid production profile, used to prove the console
# switch alone is what fails the boot check.
VALID_PRODUCTION = {
    "JWT_SECRET_KEY": "4f3c" * 16,
    "CORS_ORIGINS": "https://app.example.com",
    "SQL_ECHO": False,
    "RATE_LIMIT_BACKEND": "redis",
    "API_KEY_PEPPER": "pepper-value",
    "INTEGRATION_WEBHOOK_SECRET": "webhook-secret-value",
    "TRUSTED_PROXY_IPS": ("203.0.113.10",),
    "DOCS_ENABLED": False,
    "PLATFORM_CONSOLE_ENABLED": True,
}

ALT_ORIGIN_HEADERS = {
    "Host": "platform.internal.example",
    "X-Forwarded-Host": "platform.internal.example",
    "X-Forwarded-Proto": "https",
    "X-Forwarded-For": "203.0.113.10",
    "Origin": "https://platform.internal.example",
}


def _route_path(route, company_id) -> str:
    """Substitute path parameters so a route can be called while it is hidden."""
    path = route.path
    while "{" in path:
        start = path.index("{")
        end = path.index("}", start)
        path = f"{path[:start]}{company_id}{path[end + 1:]}"
    return path


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="v6-11-exercise-")
    db_path = Path(workdir) / "exercise.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    # `site_gpt.app.db.session` reads DATABASE_URL at import time, and the CLI
    # subprocess reads it from this environment.
    os.environ["DATABASE_URL"] = database_url

    results: list[bool] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        results.append(ok)
        line = f"{'PASS' if ok else 'FAIL'}  {label}"
        if detail and not ok:
            line += f"  ({detail})"
        print(line)

    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import NullPool

        from site_gpt.app import models
        from site_gpt.app.api import platform as platform_api
        from site_gpt.app.core import config
        from site_gpt.app.core.auth import get_current_user
        from site_gpt.app.db.base import Base
        from site_gpt.app.db.session import get_db

        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        Base.metadata.create_all(
            engine,
            tables=[
                models.Company.__table__,
                models.User.__table__,
                models.PlatformOwner.__table__,
                models.PlatformAuditLog.__table__,
            ],
        )

        with Session() as db:
            company = models.Company(name="V6-11 exercise")
            db.add(company)
            db.flush()
            db.add_all(
                [
                    models.User(
                        company_id=company.id,
                        email=OWNER_EMAIL,
                        password_hash="x",
                        first_name="Ops",
                        last_name="Exercise",
                        role="admin",
                        status="active",
                    ),
                    models.User(
                        company_id=company.id,
                        email=ADMIN_EMAIL,
                        password_hash="x",
                        first_name="Tenant",
                        last_name="Admin",
                        role="admin",
                        status="active",
                    ),
                ]
            )
            db.commit()
            company_id = company.id

        with Session() as db:
            owner = db.query(models.User).filter_by(email=OWNER_EMAIL).one()
            admin = db.query(models.User).filter_by(email=ADMIN_EMAIL).one()

        def cli(*args) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "platform_owner.py"), *args],
                capture_output=True,
                text=True,
                cwd=ROOT,
                env=dict(os.environ, DATABASE_URL=database_url),
            )

        def counts() -> tuple[int, int, int]:
            with Session() as db:
                grants = db.query(models.PlatformOwner).count()
                active = (
                    db.query(models.PlatformOwner)
                    .filter(models.PlatformOwner.revoked_at.is_(None))
                    .count()
                )
                audit = db.query(models.PlatformAuditLog).count()
            return grants, active, audit

        # --- 1. production refuses the switch without a network boundary -----
        problems = config.production_config_errors(VALID_PRODUCTION)
        check(
            "APP_ENV=production refuses the console switch without a valid operator allowlist, naming only that setting",
            problems == ["OPERATOR_ALLOWED_NETWORKS"],
            str(problems),
        )

        # --- 2. the switch hides every route --------------------------------
        granted = cli("grant", "--email", OWNER_EMAIL, "--actor", "v6-11 exercise")
        check(
            "the out-of-band CLI grants the operator",
            granted.returncode == 0 and granted.stdout.startswith("granted:"),
            (granted.stdout + granted.stderr).strip(),
        )

        app = FastAPI()
        app.include_router(platform_api.router)
        current = {"user": owner}

        def _db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: current["user"]
        client = TestClient(app)

        def call(method: str, path: str, user):
            current["user"] = user
            if method == "GET":
                return client.request(method, path)
            return client.request(method, path, json={})

        routes = [
            route
            for route in platform_api.router.routes
            if getattr(route, "path", "").startswith("/api/platform")
        ]

        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", False):
            failures = []
            for route in routes:
                method = "GET" if "GET" in route.methods else sorted(route.methods)[0]
                path = _route_path(route, company_id)
                for label, user in (("owner", owner), ("tenant admin", admin)):
                    response = call(method, path, user)
                    if response.status_code != 404 or response.json() != {
                        "detail": "Not found"
                    }:
                        failures.append(
                            f"{method} {path} as {label} -> {response.status_code}"
                        )
            check(
                f"the switch hides all {len(routes)} routes from a granted operator and a tenant admin",
                not failures,
                "; ".join(failures),
            )

            current["user"] = owner
            alt = client.get("/api/platform/session", headers=ALT_ORIGIN_HEADERS)
            check(
                "an alternate Host/X-Forwarded-Host/Origin does not reveal the surface",
                alt.status_code == 404 and alt.json() == {"detail": "Not found"},
                f"status {alt.status_code}",
            )

        # --- 3. on: operator only -------------------------------------------
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True):
            allowed = call("GET", "/api/platform/session", owner)
            check(
                "with the switch on, the granted operator is allowed",
                allowed.status_code == 200 and allowed.json()["email"] == OWNER_EMAIL,
                f"status {allowed.status_code}",
            )
            refused = call("GET", "/api/platform/session", admin)
            check(
                "with the switch on, a tenant admin is still refused",
                refused.status_code == 403,
                f"status {refused.status_code}",
            )
            alt_admin = client.get(
                "/api/platform/session",
                headers=ALT_ORIGIN_HEADERS,
            )
            check(
                "an alternate hostname does not replace the owner check",
                alt_admin.status_code == 403,
                f"status {alt_admin.status_code}",
            )

            # --- 4. revocation is immediate ---------------------------------
            revoked = cli(
                "revoke", "--email", OWNER_EMAIL, "--actor", "v6-11 exercise"
            )
            check(
                "the CLI revokes the active grant",
                revoked.returncode == 0 and "revoked:" in revoked.stdout,
                (revoked.stdout + revoked.stderr).strip(),
            )
            after = call("GET", "/api/platform/session", owner)
            check(
                "the revoked grant is refused on the very next request, with no restart",
                after.status_code == 403,
                f"status {after.status_code}",
            )
            listing = cli("list")
            check(
                "the CLI reports no active operator",
                listing.returncode == 0
                and listing.stdout.startswith("0 active operator"),
                listing.stdout.strip(),
            )

            # --- 5. recovery: re-grant --------------------------------------
            regranted = cli("grant", "--email", OWNER_EMAIL, "--actor", "v6-11 exercise")
            restored = call("GET", "/api/platform/session", owner)
            check(
                "re-granting restores access (recovery path)",
                regranted.returncode == 0
                and restored.status_code == 200,
                f"status {restored.status_code}",
            )

        # --- 6. emergency disable leaves state intact ------------------------
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", False):
            disabled = call("GET", "/api/platform/session", owner)
            check(
                "the switch takes the recovered access away again",
                disabled.status_code == 404,
                f"status {disabled.status_code}",
            )

        grants, active, audit = counts()
        check(
            "grants and their history survive the switch (2 rows, 1 active)",
            grants == 2 and active == 1,
            f"{grants} rows, {active} active",
        )
        check(
            "grant and revoke actions are audited (3 rows)",
            audit == 3,
            f"{audit} rows",
        )

        passed = sum(results)
        print(
            f"\nV6-11 emergency disable/recovery exercise: "
            f"{passed}/{len(results)} checks passed"
        )
        print(f"throwaway database: {db_path}")
        return 0 if passed == len(results) else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
