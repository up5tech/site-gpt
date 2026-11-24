"""V6-23: the external check covers every replica, and partial coverage fails.

What is pinned here:

* `OPS_STATUS_URLS` wins over the single `OPS_STATUS_URL` default, and a
  trailing slash or a repeated origin cannot make one replica look like two;
* each origin's snapshot is one result labelled with that origin, and a
  critical alert is kept as such rather than flattened into prose;
* the exit code is the worst across origins (2 > 1 > 0), so a run that reached
  one healthy replica out of two cannot exit 0;
* a non-200 prints no body, and neither output stream ever contains the token.
"""

import importlib.util
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ops_status.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("ops_status_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops_status = _load_script()

CLEAN = {"alerts": [], "db": True}
CRITICAL = {
    "alerts": [{"code": "api.database_unreachable", "severity": "critical"}],
    "db": False,
}


class _Response:
    def __init__(self, status_code=200, payload=None, body="secret-body"):
        self.status_code = status_code
        self._payload = payload
        self.text = body

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Stub:
    """A `httpx.get` replacement keyed by URL; records every call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _run(environ, stub):
    """Call `main()` with environment and stubbed transport; return outputs."""
    stdout, stderr = StringIO(), StringIO()
    with (
        patch.dict(os.environ, environ, clear=False),
        patch.object(ops_status.httpx, "get", stub),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        code = ops_status.main()
    return code, stdout.getvalue(), stderr.getvalue()


class OriginListTests(unittest.TestCase):
    def test_the_list_wins_over_the_single_url(self):
        targets = ops_status.origins(
            {
                "OPS_STATUS_URLS": " https://a.example/, https://b.example ",
                "OPS_STATUS_URL": "https://c.example",
            }
        )

        self.assertEqual(targets, ["https://a.example", "https://b.example"])

    def test_the_single_url_is_still_the_default(self):
        self.assertEqual(
            ops_status.origins({"OPS_STATUS_URL": "https://only.example/"}),
            ["https://only.example"],
        )

    def test_an_empty_list_falls_back_to_the_single_url(self):
        self.assertEqual(
            ops_status.origins(
                {"OPS_STATUS_URLS": "  ", "OPS_STATUS_URL": "https://only.example"}
            ),
            ["https://only.example"],
        )

    def test_nothing_configured_checks_localhost(self):
        self.assertEqual(ops_status.origins({}), ["http://localhost:8000"])

    def test_a_repeated_origin_is_checked_once(self):
        targets = ops_status.origins(
            {"OPS_STATUS_URLS": "https://a.example,https://a.example/,https://b.example"}
        )

        self.assertEqual(targets, ["https://a.example", "https://b.example"])


class CheckOriginTests(unittest.TestCase):
    def test_a_clean_snapshot_is_reachable_and_clean(self):
        stub = _Stub({"https://a.example/api/ops/status": _Response(payload=CLEAN)})

        report = ops_status.check_origin("https://a.example", "t", get=stub)

        self.assertTrue(report["ok"])
        self.assertEqual(report["origin"], "https://a.example")
        self.assertEqual(report["snapshot"], CLEAN)
        self.assertEqual(report["critical"], [])
        self.assertEqual(ops_status.exit_code(report), ops_status.EXIT_OK)

    def test_a_critical_alert_is_kept_and_exits_one(self):
        stub = _Stub(
            {"https://a.example/api/ops/status": _Response(payload=CRITICAL)}
        )

        report = ops_status.check_origin("https://a.example", "t", get=stub)

        self.assertEqual([alert["code"] for alert in report["critical"]], ["api.database_unreachable"])
        self.assertEqual(ops_status.exit_code(report), ops_status.EXIT_ALERT)

    def test_a_non_200_reports_the_status_and_no_body(self):
        stub = _Stub(
            {"https://a.example/api/ops/status": _Response(status_code=401, body="invalid ops token")}
        )

        report = ops_status.check_origin("https://a.example", "t", get=stub)

        self.assertFalse(report["ok"])
        self.assertEqual(report["error"], "answered 401")
        self.assertEqual(ops_status.exit_code(report), ops_status.EXIT_UNUSABLE)
        self.assertNotIn("invalid ops token", json.dumps(report))

    def test_a_transport_failure_is_unusable_not_clean(self):
        stub = _Stub({"https://a.example/api/ops/status": RuntimeError("boom")})

        report = ops_status.check_origin("https://a.example", "t", get=stub)

        self.assertFalse(report["ok"])
        self.assertTrue(report["error"].startswith("unreachable:"))
        self.assertEqual(ops_status.exit_code(report), ops_status.EXIT_UNUSABLE)

    def test_the_token_travels_in_the_header_only(self):
        stub = _Stub({"https://a.example/api/ops/status": _Response(payload=CLEAN)})

        report = ops_status.check_origin("https://a.example", "s3cret", get=stub)

        self.assertEqual(stub.calls[0]["headers"], {"X-Ops-Token": "s3cret"})
        self.assertNotIn("s3cret", json.dumps(report))


class CoverageTests(unittest.TestCase):
    ENV = {"OPS_STATUS_TOKEN": "token", "OPS_STATUS_URL": ""}

    def _env(self, urls):
        return {**self.ENV, "OPS_STATUS_URLS": urls}

    def test_one_clean_and_one_critical_cannot_pass(self):
        stub = _Stub(
            {
                "https://a.example/api/ops/status": _Response(payload=CLEAN),
                "https://b.example/api/ops/status": _Response(payload=CRITICAL),
            }
        )

        code, stdout, _ = _run(
            self._env("https://a.example,https://b.example"), stub
        )
        document = json.loads(stdout)

        self.assertEqual(code, ops_status.EXIT_ALERT)
        self.assertEqual(document["checked"], ["https://a.example", "https://b.example"])
        self.assertEqual(document["worst_exit"], ops_status.EXIT_ALERT)

    def test_an_unreachable_replica_is_worse_than_an_alert(self):
        stub = _Stub(
            {
                "https://a.example/api/ops/status": _Response(payload=CRITICAL),
                "https://b.example/api/ops/status": RuntimeError("boom"),
            }
        )

        code, _, stderr = _run(
            self._env("https://a.example,https://b.example"), stub
        )

        self.assertEqual(code, ops_status.EXIT_UNUSABLE)
        self.assertIn("https://b.example/api/ops/status: unreachable", stderr)

    def test_partial_coverage_never_reads_as_a_pass(self):
        # The one replica that answered is healthy: without the coverage rule
        # this run would exit 0 and hide the replica it never reached.
        stub = _Stub(
            {
                "https://a.example/api/ops/status": _Response(payload=CLEAN),
                "https://b.example/api/ops/status": RuntimeError("boom"),
            }
        )

        code, stdout, _ = _run(
            self._env("https://a.example,https://b.example"), stub
        )
        document = json.loads(stdout)
        by_origin = {result["origin"]: result for result in document["results"]}

        self.assertEqual(code, ops_status.EXIT_UNUSABLE)
        self.assertTrue(by_origin["https://a.example"]["ok"])
        self.assertFalse(by_origin["https://b.example"]["ok"])
        self.assertEqual(document["worst_exit"], ops_status.EXIT_UNUSABLE)

    def test_every_snapshot_is_labelled_with_its_origin(self):
        stub = _Stub(
            {
                "https://a.example/api/ops/status": _Response(payload=CLEAN),
                "https://b.example/api/ops/status": _Response(payload=CRITICAL),
            }
        )

        _, stdout, _ = _run(
            self._env("https://a.example,https://b.example"), stub
        )
        labels = [result["origin"] for result in json.loads(stdout)["results"]]

        self.assertEqual(labels, ["https://a.example", "https://b.example"])

    def test_two_clean_replicas_pass(self):
        stub = _Stub(
            {
                "https://a.example/api/ops/status": _Response(payload=CLEAN),
                "https://b.example/api/ops/status": _Response(payload=CLEAN),
            }
        )

        code, _, _ = _run(self._env("https://a.example,https://b.example"), stub)

        self.assertEqual(code, ops_status.EXIT_OK)

    def test_a_single_url_run_still_works(self):
        stub = _Stub({"https://only.example/api/ops/status": _Response(payload=CLEAN)})

        code, stdout, _ = _run(
            {"OPS_STATUS_TOKEN": "token", "OPS_STATUS_URLS": "", "OPS_STATUS_URL": "https://only.example"},
            stub,
        )

        self.assertEqual(code, ops_status.EXIT_OK)
        self.assertEqual(json.loads(stdout)["checked"], ["https://only.example"])

    def test_no_token_makes_no_request(self):
        stub = _Stub({})

        code, _, stderr = _run({"OPS_STATUS_TOKEN": "", "OPS_STATUS_URLS": ""}, stub)

        self.assertEqual(code, ops_status.EXIT_UNUSABLE)
        self.assertEqual(stub.calls, [])
        self.assertIn("OPS_STATUS_TOKEN is not set", stderr)

    def test_the_token_is_never_printed(self):
        stub = _Stub({"https://a.example/api/ops/status": _Response(payload=CLEAN)})
        secret = "s3cret-ops-value"

        _, stdout, stderr = _run(
            {**self._env("https://a.example"), "OPS_STATUS_TOKEN": secret}, stub
        )

        self.assertNotIn(secret, stdout)
        self.assertNotIn(secret, stderr)


if __name__ == "__main__":
    unittest.main()
