"""V3-4G gate: HTTP smoke on the throwaway gate database (compat embed mode).

Covers the provider-free half of PLAN_V3.md §9: register/login, website,
widget-config keys, embed token in compat, session-token isolation, the inbox
flow, privacy export + erasure and the flags-off V2.1 path. It writes
`.state/smoke.json` for `03_enforce.py` and `04_redis.sh`.
"""

import gate_env  # noqa: F401  — sets DATABASE_URL before site_gpt is imported

import os
from uuid import uuid4

from fastapi.testclient import TestClient

from site_gpt.app import models
from site_gpt.app.db.session import SessionLocal
from site_gpt.app.main import app

assert gate_env.GATE_DB in os.environ["DATABASE_URL"]
assert os.getenv("EMBED_TOKEN_MODE", "compat") == "compat"

client = TestClient(app)
stamp = uuid4().hex[:8]
origin = f"https://smoke-{stamp}.example"
results = []


def check(name, fn):
    try:
        detail = fn()
    except AssertionError as exc:
        print(f"FAIL {name}: {exc}")
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
    results.append(name)
    print(f"ok   {name}{' — ' + detail if detail else ''}")


def health():
    res = client.get("/health")
    assert res.status_code == 200, res.text
    body = res.json()
    return f"status={body.get('status')} rate_limiter={body.get('rate_limiter')}"


admin_email = f"smoke-{stamp}@example.com"
password = "Gate!passw0rd"
state = {}


def register():
    res = client.post(
        "/api/register",
        json={
            "company_name": f"Smoke {stamp}",
            "first_name": "Gate",
            "last_name": "Admin",
            "email": admin_email,
            "password": password,
        },
    )
    assert res.status_code in (200, 201), res.text
    tok = client.post("/api/token", json={"email": admin_email, "password": password})
    assert tok.status_code == 200, tok.text
    state["headers"] = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    me = client.get("/api/users/me", headers=state["headers"])
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "admin", me.json()
    return f"admin role={me.json()['role']}"


def create_website():
    res = client.post(
        "/api/websites/",
        json={"url": origin, "site_map_url": f"{origin}/sitemap.xml", "name": "Smoke site"},
        headers=state["headers"],
    )
    assert res.status_code in (200, 201), res.text
    state["website_id"] = res.json()["id"]
    return state["website_id"]


def widget_config_keys():
    res = client.get("/api/widget-config", params={"website_id": state["website_id"]})
    assert res.status_code == 200, res.text
    keys = set(res.json())
    assert len(keys) == 14, sorted(keys)
    for hidden in ("live_inbox_enabled", "daily_message_limit", "handoff_email"):
        assert hidden not in keys, hidden
    return f"{len(keys)} public keys, no internal keys"


def embed_token_compat():
    res = client.post(
        f"/api/websites/{state['website_id']}/embed-token", headers=state["headers"]
    )
    assert res.status_code == 201, res.text
    raw = res.json()["token"]
    state["embed_token"] = raw
    # A snippet that predates the token keeps working in compat.
    tokenless = client.post(
        "/api/session-token",
        json={"website_id": state["website_id"], "session_id": "s1"},
        headers={"Origin": origin},
    )
    assert tokenless.status_code == 200, tokenless.text
    state["session_token"] = tokenless.json()["token"]
    # A wrong token on an unclaimed session is refused and claims nothing.
    bad = client.post(
        "/api/session-token",
        json={"website_id": state["website_id"], "session_id": "s1b"},
        headers={"Origin": origin, "X-Embed-Token": "not-a-real-token"},
    )
    assert bad.status_code == 403, bad.text
    assert "invalid_embed_token" in bad.text, bad.text
    still_open = client.post(
        "/api/session-token",
        json={"website_id": state["website_id"], "session_id": "s1b"},
        headers={"Origin": origin},
    )
    assert still_open.status_code == 200, still_open.text
    # The refusal did not reset the K4 session s1.
    after = client.get(
        "/api/chat/messages",
        params={"website_id": state["website_id"], "session_id": "s1"},
        headers={"Origin": origin, "X-Session-Token": state["session_token"]},
    )
    assert after.status_code == 200, after.text
    return "tokenless accepted in compat, bad token 403 invalid_embed_token, K4 session intact"


def session_isolation():
    other = client.post(
        "/api/session-token",
        json={"website_id": state["website_id"], "session_id": "s2"},
        headers={"Origin": origin, "X-Embed-Token": state["embed_token"]},
    )
    assert other.status_code == 200, other.text
    res = client.get(
        "/api/chat/messages",
        params={"website_id": state["website_id"], "session_id": "s2"},
        headers={"Origin": origin, "X-Session-Token": state["session_token"]},
    )
    assert res.status_code == 403, res.text
    return "s1 token cannot read s2"


def set_settings(pairs):
    res = client.put(
        "/api/settings/",
        json=[{"key": k, "value": v} for k, v in pairs],
        headers=state["headers"],
    )
    assert res.status_code == 200, res.text


def second_agent():
    res = client.post(
        "/api/companies/users",
        json={
            "email": f"agent2-{stamp}@example.com",
            "first_name": "Second",
            "last_name": "Agent",
            "role": "manager",
            "password": password,
        },
        headers=state["headers"],
    )
    assert res.status_code in (200, 201), res.text
    tok = client.post(
        "/api/token", json={"email": f"agent2-{stamp}@example.com", "password": password}
    )
    assert tok.status_code == 200, tok.text
    state["headers2"] = {"Authorization": f"Bearer {tok.json()['access_token']}"}


def inbox_flow():
    set_settings([("handoff_enabled", "true"), ("live_inbox_enabled", "true")])
    res = client.post(
        "/api/handoff",
        json={"website_id": state["website_id"], "session_id": "s1", "message": "human please"},
        headers={"Origin": origin},
    )
    assert res.status_code in (200, 201), res.text
    db = SessionLocal()
    try:
        conv = (
            db.query(models.Conversation)
            .filter_by(website_id=state["website_id"], session_id="s1")
            .one()
        )
        assert conv.state == "waiting", conv.state
        state["conversation_id"] = str(conv.id)
    finally:
        db.close()

    status = client.get("/api/inbox/status", headers=state["headers"])
    assert status.status_code == 200 and status.json()["enabled"] is True, status.text

    listing = client.get(
        "/api/inbox/conversations",
        params={"state": "waiting"},
        headers=state["headers"],
    )
    assert listing.status_code == 200, listing.text
    ids = [row["id"] for row in listing.json()["items"]]
    assert state["conversation_id"] in ids, ids

    claimed = client.post(
        f"/api/inbox/conversations/{state['conversation_id']}/claim", headers=state["headers"]
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["state"] == "human", claimed.json()
    assert claimed.json()["assigned_user_id"], claimed.json()

    rival = client.post(
        f"/api/inbox/conversations/{state['conversation_id']}/claim",
        headers=state["headers2"],
    )
    assert rival.status_code == 409, (rival.status_code, rival.text)

    reply = client.post(
        f"/api/inbox/conversations/{state['conversation_id']}/messages",
        json={"message": "Agent here, how can I help?"},
        headers=state["headers"],
    )
    assert reply.status_code in (200, 201), reply.text

    widget = client.get(
        "/api/chat/messages",
        params={"website_id": state["website_id"], "session_id": "s1"},
        headers={"Origin": origin, "X-Session-Token": state["session_token"]},
    )
    assert widget.status_code == 200, widget.text
    body = widget.json()
    assert body["state"] == "human", body
    assert any(m["role"] == "agent" and "Agent here" in m["message"] for m in body["items"]), body

    closed = client.post(
        f"/api/inbox/conversations/{state['conversation_id']}/close", headers=state["headers"]
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "closed", closed.json()
    return "waiting → claim → human → second claim 409 → reply delivered → closed"


def privacy_roundtrip():
    export = client.get(
        "/api/privacy/export",
        params={"website_id": state["website_id"]},
        headers=state["headers"],
    )
    assert export.status_code == 200, export.text
    body = export.json()
    convs = [c for c in body["conversations"] if c["session_id"] == "s1"]
    msgs = [m for m in body["chat_messages"] if m["session_id"] == "s1"]
    assert convs, [c["session_id"] for c in body["conversations"]]
    assert convs[0]["state"] == "closed", convs[0]
    assert convs[0]["closed_at"], convs[0]
    assert any(m.get("author_user_id") for m in msgs), msgs
    assert any(m["role"] == "agent" for m in msgs), [m["role"] for m in msgs]

    erased = client.delete(
        "/api/privacy/conversations/s1",
        params={"website_id": state["website_id"]},
        headers=state["headers"],
    )
    assert erased.status_code == 200, erased.text
    counts = erased.json()["deleted"]
    after = client.get(
        "/api/privacy/export",
        params={"website_id": state["website_id"]},
        headers=state["headers"],
    )
    assert after.status_code == 200, after.text
    left = [c for c in after.json()["conversations"] if c["session_id"] == "s1"]
    left_msgs = [m for m in after.json()["chat_messages"] if m["session_id"] == "s1"]
    assert not left and not left_msgs, (left, left_msgs)
    return f"export carried state/assignee/agent authors; erased {counts}; export empty after"


def flags_off_path():
    set_settings([("live_inbox_enabled", "false")])
    db = SessionLocal()
    try:
        website_id = state["website_id"]
        db.query(models.Conversation).filter_by(website_id=website_id, session_id="s9").delete()
        db.commit()
    finally:
        db.close()
    res = client.post(
        "/api/handoff",
        json={"website_id": state["website_id"], "session_id": "s9", "message": "v2.1 path"},
        headers={"Origin": origin},
    )
    assert res.status_code in (200, 201), res.text
    db = SessionLocal()
    try:
        rows = (
            db.query(models.Conversation)
            .filter_by(website_id=state["website_id"], session_id="s9")
            .count()
        )
    finally:
        db.close()
    assert rows == 0, f"flag off still created {rows} conversation row(s)"
    status = client.get("/api/inbox/status", headers=state["headers"])
    assert status.status_code == 200 and status.json()["enabled"] is False, status.text
    hidden = client.get("/api/inbox/conversations", headers=state["headers"])
    assert hidden.status_code == 404, hidden.status_code
    return "handoff still queued, no conversation row, /inbox surface 404"


def company_id():
    db = SessionLocal()
    try:
        row = db.query(models.User).filter_by(email=admin_email).one()
        state["company_id"] = row.company_id
    finally:
        db.close()
    return str(state["company_id"])


check("/health", health)
check("register + admin login", register)
check("website created", create_website)
check("company id resolved", company_id)
check("/api/widget-config key set", widget_config_keys)
check("embed token compat behaviour", embed_token_compat)
check("session-token isolation", session_isolation)
check("second agent created", second_agent)
check("inbox end-to-end", inbox_flow)
check("privacy export + erasure", privacy_roundtrip)
check("all flags off = V2.1 path", flags_off_path)

gate_env.save_state(
    stamp=stamp,
    email=admin_email,
    password=password,
    website_id=state["website_id"],
    company_id=state["company_id"],
)
print(f"\n{len(results)} HTTP smoke checks passed")
