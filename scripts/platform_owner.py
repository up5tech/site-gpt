#!/usr/bin/env python
"""Grant, revoke and list platform-owner access — out of band only (V5-40, D10).

This is the whole provisioning path. There is deliberately no API for it: a
tenant admin, manager, member or API key cannot promote itself, and the operator
console (V5-41+) only reads what this script wrote.

Usage (from the repo root, with the deployment's `DATABASE_URL` exported):

    uv run python scripts/platform_owner.py list
    uv run python scripts/platform_owner.py grant --email ops@example.com \
        --actor "on-call SRE (OPS-12)" --note "primary operator"
    uv run python scripts/platform_owner.py revoke --email ops@example.com \
        --actor "on-call SRE (OPS-12)"

`--actor` is required for grant and revoke and is written to the audit row: an
out-of-band action has no session, but it still has to say who took it.
"""

import argparse
import sys

from site_gpt.app import models
from site_gpt.app.db.session import SessionLocal
from site_gpt.app.services import platform


def _user(db, email: str) -> models.User:
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise SystemExit(f"no user with email {email!r}")
    return user


def cmd_grant(args) -> int:
    db = SessionLocal()
    try:
        user = _user(db, args.email)
        row, created = platform.grant_owner(
            db, user.id, actor_label=args.actor, note=args.note
        )
        state = "granted" if created else "already active"
        print(f"{state}: {user.email} (grant {row.id})")
        return 0 if created else 0
    finally:
        db.close()


def cmd_revoke(args) -> int:
    db = SessionLocal()
    try:
        user = _user(db, args.email)
        if not platform.revoke_owner(db, user.id, actor_label=args.actor):
            print(f"no active grant for {user.email}")
            return 1
        print(f"revoked: {user.email}")
        return 0
    finally:
        db.close()


def cmd_list(args) -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(models.PlatformOwner, models.User)
            .join(models.User, models.User.id == models.PlatformOwner.user_id)
            .order_by(models.PlatformOwner.created_at.desc())
            .all()
        )
        active = [
            (grant, user) for grant, user in rows if grant.revoked_at is None
        ]
        print(f"{len(active)} active operator(s)")
        for grant, user in active:
            note = f" — {grant.note}" if grant.note else ""
            print(f"  {user.email}  granted {grant.created_at:%Y-%m-%d}{note}")
        if args.history:
            revoked = [(g, u) for g, u in rows if g.revoked_at is not None]
            print(f"{len(revoked)} revoked grant(s)")
            for grant, user in revoked:
                print(f"  {user.email}  revoked {grant.revoked_at:%Y-%m-%d}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    grant = sub.add_parser("grant", help="grant operator access to an existing user")
    grant.add_argument("--email", required=True)
    grant.add_argument("--actor", required=True, help="who is granting (audited)")
    grant.add_argument("--note", default=None)
    grant.set_defaults(func=cmd_grant)

    revoke = sub.add_parser("revoke", help="revoke the active grant")
    revoke.add_argument("--email", required=True)
    revoke.add_argument("--actor", required=True, help="who is revoking (audited)")
    revoke.set_defaults(func=cmd_revoke)

    listing = sub.add_parser("list", help="show active grants")
    listing.add_argument("--history", action="store_true", help="also show revoked")
    listing.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
