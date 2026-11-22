# Platform owner console (V5 Wave 4)

The operator control plane is **not** a tenant feature. It is a separate grant
bound to an existing authenticated user, provisioned out of band, and it is
closed by default. Wave 4 starts here: this document covers the boundary and the
provisioning procedure that V5-40 adds. The console itself — subscription
operations, catalog editing, global settings — is V5-41…V5-43 and does not exist
yet.

## What exists today (V5-40)

| Piece | What it does |
|---|---|
| `models.PlatformOwner` (M12) | One grant row per operator. `revoked_at` ends it; a partial unique index allows **one active grant per user**, so revoked rows stay as history and a re-grant inserts a new row. `ON DELETE CASCADE` on the user removes the grant with them. |
| `models.PlatformAuditLog` (M12) | Append-only trail: actor (`actor_user_id` for API actions, `actor_label` for the CLI), action, target type/id, time, and a JSON `detail` that is redacted by the writer before it is stored. No payload, card, token or credential column. |
| `services/platform.py` | `is_owner` / `active_grant`, the idempotent `grant_owner`, the timestamp `revoke_owner`, `record_audit` and `recent_audit`. The redactor drops any key matching secret/token/password/key/credential/DSN patterns and refuses non-scalar values. |
| `core.auth.require_platform_owner` | The route dependency. A tenant `admin` fails it: it reads the grant, not `users.role`. |
| `api/platform.py` | Two read-only routes: `GET /api/platform/session` (who the operator is) and `GET /api/platform/audit?limit=` (newest audit rows, 1–200). |
| `scripts/platform_owner.py` | The only way to grant or revoke: `grant`, `revoke`, `list [--history]`. |

There is deliberately **no API** that mints a grant, so no request — from a
company admin, a manager, a member or an API key — can escalate itself. The
tenant `/app` console and the operator surface share only the user table.

## The switch

`PLATFORM_CONSOLE_ENABLED` (env, default `false`) gates the whole surface: while
it is false every `/api/platform/*` path answers **404**, even to a signed-in
operator. Keep it false until D10's requirement — approved strong authentication
(MFA/SSO) **or** a private operator-only network restriction — is approved and in
place. Neither has been approved, which is why the default is off and why
`/api/platform` currently has no UI at all.

## Granting and revoking

Run these from a host with the deployment's `DATABASE_URL` exported. `--actor`
is required and is what the audit row records.

```bash
# grant (idempotent: an active grant is reported, not duplicated)
uv run python scripts/platform_owner.py grant --email ops@example.com \
    --actor "on-call SRE (OPS-12)" --note "primary operator"

# see who is active / what history exists
uv run python scripts/platform_owner.py list
uv run python scripts/platform_owner.py list --history

# revoke: stamps revoked_at; the next request is refused, the row stays
uv run python scripts/platform_owner.py revoke --email ops@example.com \
    --actor "on-call SRE (OPS-12)"
```

Revocation is effective immediately because `require_platform_owner` reads the
active grant on every request. Re-granting creates a new row — the old one keeps
its `revoked_at` and any audit rows that reference it.

## Reading the audit trail

`GET /api/platform/audit` returns newest-first rows. Today the writers are the
CLI (`platform_owner.grant`, `platform_owner.revoke`) and anything V5-41+ adds;
each row carries actor, action, target and time, and `detail` has already been
redacted when it was written:

```
platform_owner.grant | user | SRE on-call (OPS-12) | {"note": "primary operator"}
platform_owner.revoke | user | SRE on-call (OPS-12) | null
```

Redaction is a whitelist of shape, not a promise about content: only strings,
numbers, booleans, nulls and lists/dicts of those are stored, and any key
matching `secret|token|password|passwd|api_key|private_key|authorization|bearer|
credential|dsn|database_url|session` is replaced with `[redacted]`. Do not design
a caller that relies on a secret round-tripping through `detail`.

## Migration M12

`0b22b30bf930` chains from M11 `a7c41d9e6b52` and creates both tables with their
indexes (new tables, so no `CONCURRENTLY`). V5-42 and V5-43 extend this still
unapplied revision with the catalog and global-settings tables; it must remain
the sole head while Wave 4 is in flight. Downgrading it drops the grants and the
audit rows — the audit trail is not recoverable, so export it first if a
downgrade is ever genuinely required.

## Not built yet

- Subscription operations, catalog/price management and the `/platform` UI
  (V5-41…V5-43), and therefore no audited mutation path beyond grant/revoke.
- Strong authentication for operators: there is no MFA/SSO, no re-authentication
  prompt and no IP allowlist in the app. Until one is approved (D10), the
  console must stay behind `PLATFORM_CONSOLE_ENABLED=false` or a private
  network.
- Typed runtime global settings and their allowlist (D12/V5-43).
- Tenant impersonation: never planned. The boundary is additive, not a
  super-tenant login.
