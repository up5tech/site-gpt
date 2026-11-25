#!/usr/bin/env bash
# Run the V6-2G items 1-14 against throwaway infrastructure. The script creates
# and drops its own database (default `v6_gate_2g`, override with GATE_DB) and
# uses one Redis database index (default 15, override with GATE_REDIS). It
# refuses a database name without the `v6_gate_2g` prefix and a Redis database 0,
# so it cannot flush or drop anything that matters.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
exec uv run python scripts/gate_v6_2g/gate.py "$@"
