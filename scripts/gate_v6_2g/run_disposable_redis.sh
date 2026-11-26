#!/usr/bin/env bash
# Run the V6-2G gate with item 11's mutation half against a throwaway Redis.
#
# Item 11 flips `maxmemory-policy`, and `CONFIG SET` changes the whole instance,
# so it must never touch the Redis this checkout shares (the development 6379).
# This wrapper starts its own container, points the gate at it with
# GATE_REDIS_ALLOW_CONFIG=1, and removes the container when the run ends — on
# success, on failure and on Ctrl-C.
#
# Docker is used because a `redis-server` binary is not assumed to exist. The
# container publishes to a random loopback port, so it cannot collide with a
# running server and is not reachable from another host.
#
#   bash scripts/gate_v6_2g/run_disposable_redis.sh            # whole table
#   bash scripts/gate_v6_2g/run_disposable_redis.sh --keep-db  # flags pass through
#
# GATE_REDIS_IMAGE (default redis:6.2) picks the server image, GATE_REDIS_DB
# (default 15) the index on it; the database name still comes from GATE_DB.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

IMAGE="${GATE_REDIS_IMAGE:-redis:6.2}"
DB="${GATE_REDIS_DB:-15}"
NAME="v6-gate-redis-$$"

if [[ -n "${GATE_REDIS:-}" ]]; then
    echo "Refusing: GATE_REDIS=${GATE_REDIS} is already set. This script starts its" >&2
    echo "own instance and never points the gate at a server it did not create;" >&2
    echo "unset GATE_REDIS to use it." >&2
    exit 2
fi
if [[ "$DB" == "0" ]]; then
    echo "Refusing GATE_REDIS_DB=0: it is the development keyspace." >&2
    exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "Refusing: docker is required (this checkout has no redis-server binary)." >&2
    exit 2
fi

if [[ -n "${GATE_PYTHON:-}" ]]; then
    RUN=("$GATE_PYTHON")
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
echo "GATE_REDIS_ALLOW_CONFIG=1 — the CONFIG SET pair touches this container only"

GATE_REDIS="redis://127.0.0.1:${port}/${DB}" GATE_REDIS_ALLOW_CONFIG=1 \
    "${RUN[@]}" scripts/gate_v6_2g/gate.py "$@"
