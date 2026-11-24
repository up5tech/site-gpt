"""Print the V6-21 operator snapshot for every API replica; exit the worst result.

This is the alert path D8 approved in place of a metrics vendor: a host cron or
external check runs it, and the exit code is the alert. It reads the same
snapshot the API serves, so the threshold logic lives in one place
(`core/telemetry.evaluate`).

V6-23: one URL could only ever prove the one replica it reached, so behind the
ingress a run that happened to hit a healthy instance looked like a pass while
another replica was broken. The check now takes a deployment-fed list, one
origin per replica, and prints every snapshot with the origin that answered it,
so partial coverage is visible and its exit code is the worst it saw.

    OPS_STATUS_URLS=https://a.example,https://b.example OPS_STATUS_TOKEN=... \\
        uv run python scripts/ops_status.py

`OPS_STATUS_URLS` is comma-separated and wins when set; `OPS_STATUS_URL` stays
the single-origin default it falls back to (then `http://localhost:8000`), so an
existing cron line keeps working unchanged.

Exit codes, worst across origins: 0 no critical alert anywhere, 1 at least one
critical alert, 2 the check itself could not run somewhere (no token, transport
error, non-200, unreadable body) — so a partially covered run is never 0.
"""

import json
import os
import sys
from typing import Any, Callable

import httpx

EXIT_OK = 0
EXIT_ALERT = 1
EXIT_UNUSABLE = 2

DEFAULT_ORIGIN = "http://localhost:8000"
REQUEST_TIMEOUT_SECONDS = 10.0


def origins(env: dict[str, str] | None = None) -> list[str]:
    """Every origin to check, in order and without duplicates.

    A trailing slash is dropped so `https://a/` and `https://a` are the same
    replica, and one origin listed twice is checked once.
    """
    source = os.environ if env is None else env
    raw = str(source.get("OPS_STATUS_URLS", "") or "")
    candidates = (
        raw.split(",") if raw.strip() else [source.get("OPS_STATUS_URL", DEFAULT_ORIGIN)]
    )
    result: list[str] = []
    for candidate in candidates:
        origin = str(candidate or "").strip().rstrip("/")
        if origin and origin not in result:
            result.append(origin)
    return result


def check_origin(
    origin: str,
    token: str,
    *,
    get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """One replica: its snapshot, its critical alerts and whether it answered.

    `ok` is false for anything that stopped the read, so the caller can treat
    it as unusable rather than clean. A non-200 body is never reported (an auth
    failure must not echo anything) and the token is never part of the report,
    so the JSON the check prints is safe to forward.
    """
    url = f"{origin}/api/ops/status"
    report: dict[str, Any] = {
        "origin": origin,
        "url": url,
        "ok": False,
        "error": None,
        "snapshot": None,
        "critical": [],
    }
    getter = httpx.get if get is None else get
    try:
        response = getter(
            url, headers={"X-Ops-Token": token}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - the check reports, it does not raise
        report["error"] = f"unreachable: {type(exc).__name__}"
        return report

    if response.status_code != 200:
        report["error"] = f"answered {response.status_code}"
        return report

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - a broken body is a failed check
        report["error"] = f"unreadable body: {type(exc).__name__}"
        return report

    report["ok"] = True
    if isinstance(payload, dict):
        report["snapshot"] = payload
        alerts = payload.get("alerts") or []
        report["critical"] = [
            alert
            for alert in alerts
            if isinstance(alert, dict) and alert.get("severity") == "critical"
        ]
    return report


def exit_code(report: dict[str, Any]) -> int:
    """0 clean, 1 a critical alert, 2 this origin could not be read."""
    if not report.get("ok"):
        return EXIT_UNUSABLE
    return EXIT_ALERT if report.get("critical") else EXIT_OK


def main() -> int:
    token = os.getenv("OPS_STATUS_TOKEN", "").strip()
    if not token:
        print(
            "OPS_STATUS_TOKEN is not set; the status route answers 404 by design.",
            file=sys.stderr,
        )
        return EXIT_UNUSABLE

    targets = origins()
    if not targets:
        print(
            "No origin to check: set OPS_STATUS_URLS or OPS_STATUS_URL.",
            file=sys.stderr,
        )
        return EXIT_UNUSABLE

    results = [check_origin(origin, token) for origin in targets]
    worst = EXIT_OK
    for report in results:
        worst = max(worst, exit_code(report))
        if report["error"]:
            # The reason only — never the body, and never the token.
            print(f"{report['url']}: {report['error']}", file=sys.stderr)

    print(
        json.dumps(
            {"checked": targets, "worst_exit": worst, "results": results},
            indent=2,
            sort_keys=True,
        )
    )
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
