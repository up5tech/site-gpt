"""Sanitised request-validation errors (V6-1G box 4).

FastAPI's default 422 handler echoes the offending input back in every error
(`input`, and sometimes `ctx`). When a body carries a per-request credential —
the Notion integration token, a Google Drive access token, a password — a
second, unrelated validation failure returns the whole object, so the
credential comes back in the response body and from there into browser
devtools, proxy logs and error trackers. The errors themselves are useful;
the submitted values are not, and the client already knows what it sent.

This handler keeps FastAPI's JSON shape (`detail` is a list of
`{type, loc, msg}`) and drops every field that can carry a submitted value.
"""

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# The only keys kept. `input` echoes the submitted value and `ctx` can hold an
# exception built from it, so neither may be passed through.
_SAFE_FIELDS = ("type", "loc", "msg")


def safe_error(error: dict) -> dict:
    """One validation error with the submitted value removed."""
    safe: dict = {}
    for key in _SAFE_FIELDS:
        value = error.get(key)
        if value is None:
            continue
        if key == "loc":
            value = [str(part) for part in value]
        safe[key] = value
    return safe or {"msg": "Invalid request"}


async def request_validation_error_response(
    request, exc: RequestValidationError
) -> JSONResponse:
    """Render a 422 naming where and why, never what was sent."""
    return JSONResponse(
        status_code=422,
        content={"detail": [safe_error(error) for error in exc.errors()]},
    )
