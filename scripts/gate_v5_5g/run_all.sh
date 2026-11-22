#!/usr/bin/env bash
# Run the complete V5-5G gate. The script creates and drops its own throwaway
# database (default `v5_gate_5g`, override with GATE_DB). It refuses a name that
# does not start with `v5_gate_5g`, so it cannot target a real database.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
exec uv run python scripts/gate_v5_5g/gate.py "$@"
