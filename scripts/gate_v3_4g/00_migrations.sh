#!/usr/bin/env bash
# V3-4G gate: M7 (embed_tokens) -> M8 (topic_clusters) -> M9 (conversations)
# from an empty database, proving each migration's downgrade and re-upgrade.
#
# Drops and recreates GATE_DB (default v3_gate_4g) on the server behind
# DATABASE_URL/.env, so never point this at a database you care about.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
export PYTHONWARNINGS=ignore
export GATE_DB="${GATE_DB:-v3_gate_4g}"

# Resolve the gate URL with the same helper the Python steps use, so there is
# one place that knows how the database name is swapped.
DATABASE_URL="$(
  PYTHONPATH="scripts/gate_v3_4g${PYTHONPATH:+:$PYTHONPATH}" uv run python -c \
    'import gate_env; print(gate_env.gate_database_url())'
)"
export DATABASE_URL

uv run python - <<'PY'
import os
import psycopg2

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
name = url.rsplit("/", 1)[1]
admin = url.rsplit("/", 1)[0] + "/postgres"
conn = psycopg2.connect(admin)
conn.autocommit = True
cur = conn.cursor()
cur.execute("select pg_terminate_backend(pid) from pg_stat_activity where datname=%s", (name,))
cur.execute(f'drop database if exists "{name}"')
cur.execute(f'create database "{name}"')
conn.close()
conn = psycopg2.connect(url)
conn.autocommit = True
conn.cursor().execute("create extension if not exists vector")
print(f"fresh database ready with pgvector: {name}")
PY

step() { echo "== alembic $*"; uv run alembic "$@" 2>&1 | tail -2; }

echo "-- empty database -> head"
uv run alembic upgrade head 2>&1 | tail -2
uv run alembic current 2>&1 | tail -1

echo "-- M7 downgrade/upgrade"
step downgrade c9d3e5a71b28
step upgrade 76f46b510350

echo "-- M8 downgrade/upgrade"
step upgrade afef1e91e0b5
step downgrade 76f46b510350
step upgrade afef1e91e0b5

echo "-- M9 downgrade/upgrade"
step upgrade 1c5516fa864d
step downgrade afef1e91e0b5
step upgrade head

echo "-- single head"
uv run alembic heads 2>&1 | tail -1
uv run alembic current 2>&1 | tail -1
echo "migration replay ok"
