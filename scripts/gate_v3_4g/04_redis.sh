#!/usr/bin/env bash
# V3-4G gate: two API processes over one shared Redis budget, then Redis down.
#
# Needs the real Redis from .env (REDIS_HOST/REDIS_PORT). Uses three uvicorn
# processes on :8011, :8012 and :8013 and kills exactly those PIDs afterwards.
# Run after `02_http_smoke.py` (it reuses that account and company).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
export PYTHONPATH="scripts/gate_v3_4g${PYTHONPATH:+:$PYTHONPATH}"
export DATABASE_URL="$(uv run python -c 'import gate_env; print(gate_env.gate_database_url())')"
export PYTHONWARNINGS=ignore
TEST_IP="198.51.100.$(( (RANDOM % 200) + 20 ))"

wait_health() {
  for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:$1/health" >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  echo "server on $1 never answered /health"
  return 1
}

gate_flag() {  # $1 = true|false
  uv run python - "$1" <<'PY'
import sys
from uuid import UUID

import gate_env
from site_gpt.app import models
from site_gpt.app.db.session import SessionLocal

value = sys.argv[1]
state = gate_env.load_state()
db = SessionLocal()
row = (
    db.query(models.Setting)
    .filter_by(company_id=UUID(state["company_id"]), key="live_inbox_enabled")
    .first()
)
assert row is not None, "the smoke company has no live_inbox_enabled row"
row.value = value
db.commit()
db.close()
print(f"live_inbox_enabled={value}")
PY
}

RATE_LIMIT_BACKEND=redis uv run uvicorn site_gpt.app.main:app --port 8011 --log-level warning >/tmp/v3_gate_uv1.log 2>&1 &
P1=$!
RATE_LIMIT_BACKEND=redis uv run uvicorn site_gpt.app.main:app --port 8012 --log-level warning >/tmp/v3_gate_uv2.log 2>&1 &
P2=$!
trap 'kill $P1 $P2 2>/dev/null || true' EXIT
wait_health 8011
wait_health 8012

echo "health(8011): $(curl -fsS http://127.0.0.1:8011/health)"

ok=0; limited=0; other=0
for i in $(seq 1 16); do
  if [ $((i % 2)) -eq 0 ]; then port=8011; else port=8012; fi
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$port/api/token" \
    -H 'Content-Type: application/json' -H "X-Forwarded-For: $TEST_IP" \
    -d '{"email":"nobody@example.com","password":"wrong"}')
  case "$code" in
    401) ok=$((ok+1)) ;;
    429) limited=$((limited+1)) ;;
    *) other=$((other+1)); echo "unexpected $code on :$port" ;;
  esac
done
echo "two processes, one Redis budget (client ip $TEST_IP): 401=$ok 429=$limited other=$other"
[ "$limited" -gt 0 ] || { echo "FAIL: no 429 — the budget was not shared"; exit 1; }
[ "$ok" -eq 10 ] || { echo "FAIL: expected exactly 10 allowed attempts, got $ok"; exit 1; }
echo "ok   login budget 10/min shared across :8011 and :8012 (one 429 bucket)"

# A token minted by one process is valid for the Redis-down process (same secret).
TOKEN=$(uv run python - <<'PY'
import json

import gate_env
import httpx

state = gate_env.load_state()
res = httpx.post(
    "http://127.0.0.1:8011/api/token",
    json={"email": state["email"], "password": state["password"]},
    timeout=10,
)
res.raise_for_status()
print(res.json()["access_token"])
PY
)

kill $P1 $P2 2>/dev/null || true
wait $P1 $P2 2>/dev/null || true
trap - EXIT

gate_flag true

REDIS_PORT=6399 RATE_LIMIT_BACKEND=redis uv run uvicorn site_gpt.app.main:app --port 8013 --log-level warning >/tmp/v3_gate_uv3.log 2>&1 &
P3=$!
trap 'kill $P3 2>/dev/null || true' EXIT
wait_health 8013

down=$(curl -fsS http://127.0.0.1:8013/health)
echo "health(redis down): $down"
echo "$down" | grep -q '"status":"degraded"' || { echo "FAIL: health did not report degradation"; exit 1; }
echo "$down" | grep -q '"redis":false' || { echo "FAIL: health still reports redis up"; exit 1; }

# One attempt makes the limiter fall back, which is what flips its own flag.
curl -s -o /dev/null -X POST http://127.0.0.1:8013/api/token -H 'Content-Type: application/json' \
  -H "X-Forwarded-For: $TEST_IP" -d '{"email":"nobody@example.com","password":"wrong"}' || true
after=$(curl -fsS http://127.0.0.1:8013/health)
echo "health after one login: $after"
echo "$after" | grep -q '"rate_limiter":{"backend":"redis","degraded":true' \
  || { echo "FAIL: limiter did not report its fallback"; exit 1; }

code=$(curl -s -o /tmp/v3_gate_events_body.txt -w '%{http_code}' "http://127.0.0.1:8013/api/inbox/events" \
  -H "Authorization: Bearer $TOKEN")
echo "GET /api/inbox/events with Redis down: $code"
[ "$code" = "503" ] || { echo "FAIL: expected 503 before streaming"; cat /tmp/v3_gate_events_body.txt; exit 1; }
echo "ok   Redis down: /health degraded and /api/inbox/events answers 503 before streaming"

kill $P3 2>/dev/null || true
trap - EXIT
gate_flag false
echo "gate redis checks done"
