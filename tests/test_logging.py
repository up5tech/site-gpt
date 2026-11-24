"""V6-22 (D8): structured logs, correlation ids and centralized redaction.

What is pinned here:

* `redact` / `scrub_text` remove secrets and email addresses at any depth,
  including values pasted into a free-text message;
* `log_event` / `log_exception` emit a JSON line whose fields are redacted and
  whose exception carries a type, a small category and a scrubbed message —
  never a traceback, a token or user text;
* `RequestContextMiddleware` reuses a well-formed inbound `X-Request-ID`,
  mints one for anything malformed (no header injection), binds it for the
  handler and echoes it on the response;
* the access event is DEBUG for success, WARNING for 4xx and ERROR for 5xx,
  which is the surface D8's alerts read;
* a background job can bind its own correlation id.
"""

import json
import logging
import unittest
import uuid
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.core.logging import (
    REDACTED,
    JsonFormatter,
    RequestContextMiddleware,
    bind_request_id,
    configure_logging,
    current_request_id,
    error_category,
    log_event,
    log_exception,
    redact,
    request_id_from_header,
    safe_exception,
    scrub_text,
)

LOG_NAME = "site_gpt.app"


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def captured():
    """Collect the records this module writes, at DEBUG and above."""
    handler = _Capture()
    logger = logging.getLogger(LOG_NAME)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _line(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


class RedactionTests(unittest.TestCase):
    def test_sensitive_keys_are_redacted_at_every_depth(self):
        cleaned = redact(
            {
                "website_id": str(uuid.uuid4()),
                "password": "hunter2",
                "api_key": "sk_live_abc123",
                "nested": {"access_token": "tok", "attempt": 2},
                "rows": [{"email": "visitor@example.com", "status": "ok"}],
                "Authorization": "Bearer abc",
            }
        )

        self.assertEqual(cleaned["password"], REDACTED)
        self.assertEqual(cleaned["api_key"], REDACTED)
        self.assertEqual(cleaned["Authorization"], REDACTED)
        self.assertEqual(cleaned["nested"]["access_token"], REDACTED)
        self.assertEqual(cleaned["nested"]["attempt"], 2)
        self.assertEqual(cleaned["rows"][0]["email"], REDACTED)
        self.assertEqual(cleaned["rows"][0]["status"], "ok")
        self.assertIn("website_id", cleaned)

    def test_secret_shaped_text_is_scrubbed(self):
        text = scrub_text(
            "failed for visitor@example.com with Bearer abc.def.ghi and "
            "sk_live_51H8xQ and whsec_9fd8a7c1e2 and password=hunter2"
        )

        for leaked in (
            "visitor@example.com",
            "abc.def.ghi",
            "sk_live_51H8xQ",
            "whsec_9fd8a7c1e2",
            "hunter2",
        ):
            self.assertNotIn(leaked, text)
        self.assertIn(REDACTED, text)

    def test_long_text_is_bounded(self):
        text = scrub_text("a" * 900)

        self.assertLess(len(text), 400)
        self.assertIn("chars)", text)

    def test_unknown_objects_do_not_leak_their_repr(self):
        class Secretish:
            def __repr__(self) -> str:  # pragma: no cover - must not be used
                return "sk_live_repr_leak"

        self.assertEqual(redact(Secretish()), "<Secretish>")
        self.assertEqual(redact(b"raw-bytes"), REDACTED)

    def test_safe_exception_keeps_type_and_category_not_payload(self):
        payload = safe_exception(ValueError("bad email visitor@example.com"))

        self.assertEqual(payload["error_type"], "ValueError")
        self.assertEqual(payload["error_category"], "validation")
        self.assertNotIn("visitor@example.com", payload["error_message"])

    def test_error_categories(self):
        self.assertEqual(error_category(TimeoutError("slow")), "timeout")
        self.assertEqual(error_category(ConnectionError("down")), "connection")
        self.assertEqual(error_category(PermissionError("no")), "permission")
        self.assertEqual(error_category(RuntimeError("odd")), "unexpected")


class EventTests(unittest.TestCase):
    def test_log_event_is_one_json_line_with_redacted_fields(self):
        with captured() as records:
            log_event(
                "ingest.completed",
                website_id="w-1",
                token="abc",
                question="my private question",
                rows=3,
            )

        self.assertEqual(len(records), 1)
        line = _line(records[0])
        self.assertEqual(line["event"], "ingest.completed")
        self.assertEqual(line["level"], "INFO")
        self.assertEqual(line["website_id"], "w-1")
        self.assertEqual(line["token"], REDACTED)
        self.assertEqual(line["question"], REDACTED)
        self.assertEqual(line["rows"], 3)
        self.assertIn("ts", line)

    def test_a_secret_pasted_into_a_field_is_scrubbed(self):
        with captured() as records:
            log_event("auth.failed", reason="bad key sk_live_abcdef123456")

        line = _line(records[0])
        self.assertNotIn("sk_live_abcdef123456", json.dumps(line))
        self.assertIn(REDACTED, line["reason"])

    def test_log_exception_has_no_traceback_at_error_level(self):
        with captured() as records:
            log_exception("worker.job.failed", TimeoutError("redis timeout"), job_type="ingest")

        line = _line(records[0])
        self.assertEqual(line["level"], "ERROR")
        self.assertEqual(line["error_type"], "TimeoutError")
        self.assertEqual(line["error_category"], "timeout")
        self.assertEqual(line["job_type"], "ingest")
        self.assertNotIn("Traceback", json.dumps(line))
        self.assertIsNone(records[0].exc_info[0])

    def test_request_id_from_header_only_accepts_safe_values(self):
        self.assertEqual(request_id_from_header("abc-123_x"), "abc-123_x")
        for bad in ("", "   ", "bad id", "a" * 80, "line\nbreak"):
            with self.subTest(bad=bad):
                generated = request_id_from_header(bad)
                self.assertNotEqual(generated, bad)
                self.assertEqual(len(generated), 32)

    def test_jobs_can_bind_their_own_correlation_id(self):
        self.assertIsNone(current_request_id())
        with bind_request_id("job-42") as request_id:
            self.assertEqual(request_id, "job-42")
            self.assertEqual(current_request_id(), "job-42")
        self.assertIsNone(current_request_id())


class MiddlewareTests(unittest.TestCase):
    def _client(self):
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/ok")
        def ok():
            return {"request_id": current_request_id()}

        @app.get("/boom")
        def boom():
            raise RuntimeError("kaboom")

        return TestClient(app, raise_server_exceptions=False)

    def test_inbound_request_id_is_reused_and_echoed(self):
        client = self._client()

        with captured() as records:
            response = client.get("/ok", headers={"X-Request-ID": "support-1234"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "support-1234")
        self.assertEqual(response.json()["request_id"], "support-1234")
        access = [r for r in records if r.getMessage() == "http.request"]
        self.assertEqual(len(access), 1)
        self.assertEqual(getattr(access[0], "request_id"), "support-1234")
        self.assertEqual(access[0].levelno, logging.DEBUG)
        self.assertEqual(access[0].fields["path"], "/ok")

    def test_malformed_request_id_header_is_replaced(self):
        client = self._client()

        response = client.get("/ok", headers={"X-Request-ID": "bad id\tvalue"})

        echoed = response.headers["X-Request-ID"]
        self.assertNotIn(" ", echoed)
        self.assertEqual(len(echoed), 32)
        self.assertEqual(response.json()["request_id"], echoed)

    def test_a_5xx_is_logged_at_error_with_the_path(self):
        client = self._client()

        with captured() as records:
            response = client.get("/boom")

        self.assertEqual(response.status_code, 500)
        failed = [r for r in records if r.getMessage() == "http.request"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].levelno, logging.ERROR)
        self.assertEqual(failed[0].fields["status_code"], 500)
        self.assertEqual(failed[0].fields["path"], "/boom")
        # The server's error middleware answers outside this wrapper, so the
        # response may not carry the header; the log line still carries the id.
        self.assertTrue(getattr(failed[0], "request_id"))


class ConfigurationTests(unittest.TestCase):
    def test_configure_logging_installs_one_json_handler(self):
        root = logging.getLogger()
        before = list(root.handlers)
        try:
            configure_logging("INFO")
            configure_logging("INFO")
            ours = [
                handler
                for handler in root.handlers
                if getattr(handler, "_sitegpt_structured", False)
            ]
            self.assertEqual(len(ours), 1)
            self.assertIsInstance(ours[0].formatter, JsonFormatter)
        finally:
            for handler in list(root.handlers):
                if handler not in before:
                    root.removeHandler(handler)

    def test_unstructured_records_still_serialize_and_redact(self):
        record = logging.getLogger("uvicorn.error").makeRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "connect failed for admin@example.com",
            None,
            None,
        )

        line = _line(record)

        self.assertEqual(line["level"], "ERROR")
        self.assertNotIn("admin@example.com", line["event"])


if __name__ == "__main__":
    unittest.main()
