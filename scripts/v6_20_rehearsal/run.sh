#!/usr/bin/env bash
# Run the V6-20 failure-injection rehearsal against a throwaway Redis.
#
# The rehearsal pushes, duplicates and abandons real jobs while killing a real
# worker, so it FLUSHDBs its keyspace and LPUSHes onto `queue:jobs`. That must
# never be the Redis this checkout shares (the development 6379), so this wrapper
# starts its own container, points the rehearsal at it, and removes it when the
# run ends — on success, on failure and on Ctrl-C. PostgreSQL is a database this
# script creates and drops on the server in REHEARSAL_PG; the server is never
# stopped, which is the same definition of "disposable" the V6-2G gate uses.
#
#   bash scripts/v6_20_rehearsal/run.sh            # whole rehearsal
#   bash scripts/v6_20_rehearsal/run.sh --keep-db  # flags pass through
#
# REHEARSAL_REDIS_IMAGE (default redis:6.2) picks the server image,
# REHEARSAL_REDIS_DB (default 14) the index on it.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

IMAGE="${REHEARSAL_REDIS_IMAGE:-redis:6.2}"
DB="${REHEARSAL_REDIS_DB:-14}"
NAME="v6-20-rehearsal-redis-$$"

if [[ -n "${REHEARSAL_REDIS:-}" ]]; then
    echo "Refusing: REHEARSAL_REDIS=${REHEARSAL_REDIS} is already set. This script starts" >&2
    echo "its own instance and never points the rehearsal at a server it did not create;" >&2
    echo "unset REHEARSAL_REDIS to use it." >&2
    exit 2
fi
if [[ "$DB" == "0" ]]; then
    echo "Refusing REHEARSAL_REDIS_DB=0: it is the development keyspace." >&2
    exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "Refusing: docker is required (this checkout has no redis-server binary)." >&2
    exit 2
fi

if [[ -n "${REHEARSAL_PYTHON:-}" ]]; then
    RUN=("$REHEARSAL_PYTHON")
elif command -v uv >/dev/null 2>&1; then
    RUN=(uv run python)
elif [[ -x .venv/bin/python ]]; then
    RUN=(.venv/bin/python)
else
    RUN=(python3)
fi

cleanup() {
    if docker inspect "$NAME" >/dev/null 2>&1; then
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        echo "removed throwaway Redis $NAME"
    fi
}
trap cleanup EXIT INT TERM

echo "starting throwaway $IMAGE as $NAME (loopback, random port)"
docker run -d --rm --name "$NAME" -p 127.0.0.1::6379 "$IMAGE" >/dev/null

published="$(docker port "$NAME" 6379/tcp 2>/dev/null | head -n 1)"
port="${published##*:}"
host="${published%:*}"
if [[ -z "$port" || "$host" != "127.0.0.1" ]]; then
    echo "could not read a loopback port from 'docker port': ${published:-<none>}" >&2
    exit 2
fi

ready=""
for _ in $(seq 1 30); do
    if docker exec "$NAME" redis-cli ping 2>/dev/null | grep -q PONG; then
        ready=1
        break
    fi
    sleep 1
done
if [[ -z "$ready" ]]; then
    echo "throwaway Redis $NAME did not answer PING within 30 s" >&2
    exit 2
fi

echo "throwaway Redis ready on 127.0.0.1:${port}/${DB}"

REHEARSAL_REDIS="redis://127.0.0.1:${port}/${DB}" \
    "${RUN[@]}" -u scripts/v6_20_rehearsal/rehearse.py "$@"
