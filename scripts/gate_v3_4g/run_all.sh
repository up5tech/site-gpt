#!/usr/bin/env bash
# Run every V3-4G gate check in order. Creates/drops the throwaway database, so
# point DATABASE_URL (or .env) at a development server and set GATE_DB if the
# default `v3_gate_4g` is taken.
#
# Prerequisites: Postgres with `pgvector`, Redis, `uv`, `curl`, and the
# `.venv` this repo already uses. Blocked by design: the provider-bound
# ingest/embed/chat half of §9 and the SMTP-mail steps — no key is required or
# spent here.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
GATE="$PWD/scripts/gate_v3_4g"

echo "== 00 migration replay (empty DB -> M7 -> M8 -> M9)"
bash "$GATE/00_migrations.sh"

echo "== 01 database checks"
uv run python "$GATE/01_db_checks.py"

echo "== 02 HTTP smoke (EMBED_TOKEN_MODE=compat)"
EMBED_TOKEN_MODE=compat uv run python "$GATE/02_http_smoke.py"

echo "== 03 embed token enforce mode"
EMBED_TOKEN_MODE=enforce uv run python "$GATE/03_enforce.py"

echo "== 04 two-process Redis budget + Redis down"
bash "$GATE/04_redis.sh"

echo "== 05 clustering is opt-in"
uv run python "$GATE/05_clustering_opt_in.py"

echo "V3-4G gate scripts: all checks passed"
