"""Print the V6-21 operator snapshot; exit 1 when it reports a critical alert.

This is the alert path D8 approved in place of a metrics vendor: a host cron or
external check runs it, and the exit code is the alert. It reads the same
snapshot the API serves, so the threshold logic lives in one place
(`core/telemetry.evaluate`).

    OPS_STATUS_URL=https://api.example.com OPS_STATUS_TOKEN=... \\
        uv run python scripts/ops_status.py

Exit codes: 0 no critical alert (warnings are printed), 1 critical alert,
2 the check itself could not run (no token, transport error, non-200).
"""

import json
import os
import sys

import httpx


def main() -> int:
    base = os.getenv("OPS_STATUS_URL", "http://localhost:8000").rstrip("/")
    url = f"{base}/api/ops/status"
    token = os.getenv("OPS_STATUS_TOKEN", "").strip()
    if not token:
        print(
            "OPS_STATUS_TOKEN is not set; the status route answers 404 by design.",
            file=sys.stderr,
        )
        return 2

    try:
        response = httpx.get(url, headers={"X-Ops-Token": token}, timeout=10.0)
    except Exception as exc:  # noqa: BLE001 - the check reports, it does not raise
        print(f"could not reach {url}: {type(exc).__name__}", file=sys.stderr)
        return 2

    if response.status_code != 200:
        # Never print the response body: an auth failure must not echo anything.
        print(f"{url} answered {response.status_code}", file=sys.stderr)
        return 2

    payload = response.json()
    print(json.dumps(payload, indent=2, sort_keys=True))
    critical = [
        alert for alert in payload.get("alerts", []) if alert.get("severity") == "critical"
    ]
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
