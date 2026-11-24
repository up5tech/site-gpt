"""Structured, redacted logging (V6-22, D8).

One JSON object per line, one event name per record, and a process-wide rule for
what may never reach a log: passwords, bearer tokens, API keys, integration
tokens, card data, raw webhook bodies, full transcripts and other user text.

Everything that logs goes through `log_event` / `log_exception`; neither writes
`str(exc)` raw, and both pass every field through `redact`, so a caller cannot
leak a secret by naming a field `token` or pasting a key into a message.

The request id is a `contextvar` set by `RequestContextMiddleware` (an inbound
`X-Request-ID` is reused when it is well formed, otherwise a new one is minted)
and echoed on the response, so one support report resolves to one set of lines.
A background job binds its own id with `bind_request_id`.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from site_gpt.app.core.config import LOG_LEVEL
from site_gpt.app.core.telemetry import record_request

REDACTED = "[redacted]"

#: Longest string any single field may contribute to a line.
MAX_FIELD_CHARS = 300

#: Field names (normalised to lower case, no separators) whose value is never
#: logged. Suffix matching catches `stripe_secret_key`, `X-API-Key`, and so on.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "passwordhash",
        "secret",
        "token",
        "accesstoken",
        "refreshtoken",
        "sessiontoken",
        "embedtoken",
        "apikey",
        "authorization",
        "cookie",
        "setcookie",
        "credential",
        "credentials",
        "card",
        "cardnumber",
        "cvv",
        "cvc",
        "pan",
        "email",
        "phone",
        "transcript",
        "prompt",
        "completion",
        "payload",
        "body",
        "content",
        "question",
        "answer",
    }
)

SENSITIVE_SUFFIXES = (
    "password",
    "secret",
    "token",
    "apikey",
    "credential",
    "authorization",
    "cookie",
    "email",
    "phone",
    "cardnumber",
    "cvv",
)

_SCRUB_PATTERNS = (
    # Authorization headers and anything shaped like a bearer credential.
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{6,}"), r"\1 " + REDACTED),
    # Stripe, webhook, Slack, Resend and JWT-shaped secrets.
    (re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{6,}\b"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), REDACTED),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{6,}\b"), REDACTED),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{6,}\b"), REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), REDACTED),
    # `password=...`, `api_key: ...` and friends, keeping the field name.
    (re.compile(r"(?i)\b(pass(?:word|wd)?|secret|token|api[_-]?key)\s*([=:])\s*\S+"), r"\1\2" + REDACTED),
    # Email addresses are personal data even when they are not a credential.
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), REDACTED),
)

_CATEGORY_HINTS = (
    ("timeout", ("timeout", "timedout")),
    ("connection", ("connection", "network", "socket", "redis", "httpx", "requests")),
    ("permission", ("permission", "unauthorized", "forbidden", "auth", "integrity")),
    ("validation", ("validation", "value", "type", "parse", "json", "key")),
    ("not_found", ("notfound", "not_found", "lookup")),
)

_REQUEST_ID: ContextVar[str | None] = ContextVar("sitegpt_request_id", default=None)
_REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_logger = logging.getLogger("site_gpt.app")
_CONFIGURED_ATTR = "_sitegpt_structured"


def _normalise_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_sensitive_key(key: Any) -> bool:
    normalised = _normalise_key(key)
    if not normalised:
        return False
    if normalised in SENSITIVE_KEYS:
        return True
    return any(normalised.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def scrub_text(value: str, *, limit: int = MAX_FIELD_CHARS) -> str:
    """Mask secrets and email addresses in free text, then bound its length."""
    scrubbed = value
    for pattern, replacement in _SCRUB_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    if len(scrubbed) > limit:
        scrubbed = scrubbed[:limit] + f"… (+{len(scrubbed) - limit} chars)"
    return scrubbed


def redact(value: Any) -> Any:
    """Return `value` with sensitive keys and secret-shaped text removed.

    Recurses through mappings and sequences so a nested provider payload or a
    request dict cannot leak by depth. Unknown objects become their type name,
    never their `repr`.
    """
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray)):
        return REDACTED
    return f"<{type(value).__name__}>"


def redact_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    """Redact a flat field mapping (the shape every log event uses)."""
    if not fields:
        return {}
    return {str(key): REDACTED if _is_sensitive_key(key) else redact(value) for key, value in fields.items()}


def error_category(exc: BaseException) -> str:
    """A small, stable category so alerts and queries never parse prose."""
    name = type(exc).__name__.lower()
    for category, hints in _CATEGORY_HINTS:
        if any(hint in name for hint in hints):
            return category
    return "unexpected"


def safe_exception(exc: BaseException) -> dict[str, Any]:
    """The safe part of an exception: type, category and a scrubbed message.

    Deliberately no traceback object and no `repr`: exception text routinely
    carries a URL, a header or a fragment of user input.
    """
    return {
        "error_type": type(exc).__name__,
        "error_category": error_category(exc),
        "error_message": scrub_text(str(exc)) if str(exc) else "",
    }


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


@contextmanager
def bind_request_id(request_id: str | None = None) -> Iterator[str]:
    """Bind a correlation id for the duration of a block (jobs, scripts)."""
    rid = request_id or uuid.uuid4().hex
    token = _REQUEST_ID.set(rid)
    try:
        yield rid
    finally:
        _REQUEST_ID.reset(token)


def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger: logging.Logger | None = None,
    **fields: Any,
) -> None:
    """Emit one structured event. Never raises on odd field values."""
    target = logger or _logger
    if not target.isEnabledFor(level):
        return
    target.log(
        level,
        event,
        extra={
            "event": event,
            "fields": redact_fields(fields),
            "request_id": current_request_id(),
        },
    )


def log_exception(
    event: str,
    exc: BaseException,
    *,
    level: int = logging.ERROR,
    logger: logging.Logger | None = None,
    **fields: Any,
) -> None:
    """Log a failure with its category, never its raw payload or traceback."""
    target = logger or _logger
    payload = {**fields, **safe_exception(exc)}
    if not target.isEnabledFor(level):
        return
    # A traceback is useful only while debugging; it can embed exception text,
    # so it is emitted at DEBUG and never at INFO/WARNING/ERROR.
    target.log(
        level,
        event,
        extra={
            "event": event,
            "fields": redact_fields(payload),
            "request_id": current_request_id(),
        },
        exc_info=target.isEnabledFor(logging.DEBUG),
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per line; `event` is the message for structured calls."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", None) or scrub_text(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None) or current_request_id()
        if request_id:
            payload["request_id"] = request_id
        payload.update(redact_fields(getattr(record, "fields", None)))
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int | str | None = None) -> logging.Logger:
    """Install the JSON handler once. Safe to call from the API and the worker."""
    if isinstance(level, str):
        resolved = getattr(logging, level.upper(), logging.INFO)
    elif level is None:
        resolved = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    else:
        resolved = level

    root = logging.getLogger()
    root.setLevel(resolved)
    for handler in root.handlers:
        if getattr(handler, _CONFIGURED_ATTR, False):
            handler.setLevel(resolved)
            return _logger

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(resolved)
    setattr(handler, _CONFIGURED_ATTR, True)
    root.addHandler(handler)
    return _logger


def request_id_from_header(value: str | None) -> str:
    """Reuse a well-formed inbound id; otherwise mint one (no header injection)."""
    candidate = (value or "").strip()
    if candidate and _VALID_REQUEST_ID.match(candidate):
        return candidate
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Bind a request id and emit one access event per request.

    Pure ASGI rather than `BaseHTTPMiddleware` so streaming routes (chat SSE,
    inbox events) are passed through untouched. Successful requests log at
    DEBUG; 4xx at WARNING and 5xx at ERROR, which is the D8 alert surface.
    """

    def __init__(self, app: ASGIApp, header: str = _REQUEST_ID_HEADER) -> None:
        self.app = app
        self.header = header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = request_id_from_header(headers.get(self.header))
        method = scope.get("method", "")
        path = scope.get("path", "")
        started = time.perf_counter()
        status: dict[str, int] = {"code": 0}
        token = _REQUEST_ID.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
                MutableHeaders(scope=message)[self.header] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:  # noqa: BLE001 - log, then let the server answer
            # The server's own error middleware answers outside this wrapper, so
            # record the status here: an escaped exception is a 500 for alerts.
            status["code"] = 500
            log_exception("http.request.failed", exc, method=method, path=path)
            raise
        finally:
            code = status["code"]
            if code >= 500:
                level = logging.ERROR
            elif code >= 400:
                level = logging.WARNING
            else:
                level = logging.DEBUG
            log_event(
                "http.request",
                level=level,
                method=method,
                path=path,
                status_code=code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            # V6-21: the same status the access event just reported feeds the
            # in-process 5xx window `GET /api/ops/status` alerts on.
            record_request(code)
            _REQUEST_ID.reset(token)
