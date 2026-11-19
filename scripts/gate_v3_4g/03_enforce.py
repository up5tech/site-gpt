"""V3-4G gate: `EMBED_TOKEN_MODE=enforce` refuses a tokenless snippet.

Run after `02_http_smoke.py` (it reuses that account and website) with
`EMBED_TOKEN_MODE=enforce` set in the environment.
"""

import os

import gate_env  # noqa: F401  — sets DATABASE_URL before site_gpt is imported
from fastapi.testclient import TestClient

from site_gpt.app.main import app

assert gate_env.GATE_DB in os.environ["DATABASE_URL"], os.environ["DATABASE_URL"]
assert os.getenv("EMBED_TOKEN_MODE") == "enforce", os.getenv("EMBED_TOKEN_MODE")

state = gate_env.load_state()
client = TestClient(app)
origin = f"https://smoke-{state['stamp']}.example"

tok = client.post(
    "/api/token", json={"email": state["email"], "password": state["password"]}
)
assert tok.status_code == 200, tok.text
headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}

rotated = client.post(
    f"/api/websites/{state['website_id']}/embed-token/rotate", headers=headers
)
assert rotated.status_code in (200, 201), rotated.text
raw = rotated.json()["token"]

config = client.get(
    "/api/widget-config", params={"website_id": state["website_id"]}, headers={"Origin": origin}
)
assert config.status_code == 403, config.text
assert "embed_token_required" in config.text, config.text

config_ok = client.get(
    "/api/widget-config",
    params={"website_id": state["website_id"]},
    headers={"Origin": origin, "X-Embed-Token": raw},
)
assert config_ok.status_code == 200, config_ok.text
assert len(config_ok.json()) == 14, sorted(config_ok.json())

session = client.post(
    "/api/session-token",
    json={"website_id": state["website_id"], "session_id": "s3"},
    headers={"Origin": origin},
)
assert session.status_code == 403, session.text
assert "embed_token_required" in session.text, session.text

session_ok = client.post(
    "/api/session-token",
    json={"website_id": state["website_id"], "session_id": "s3"},
    headers={"Origin": origin, "X-Embed-Token": raw},
)
assert session_ok.status_code == 200, session_ok.text

stale = client.post(
    "/api/session-token",
    json={"website_id": state["website_id"], "session_id": "s3"},
    headers={"Origin": origin, "X-Embed-Token": "rotated-away"},
)
assert stale.status_code == 403 and "invalid_embed_token" in stale.text, stale.text

print("ok   enforce: tokenless 403 embed_token_required (widget-config + session-token)")
print("ok   enforce: the rotated token works, the previous one is refused as invalid_embed_token")
print("\n2 enforce-mode checks passed")
