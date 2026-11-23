import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Strong references to fire-and-forget tasks so they are not garbage
# collected before they finish sending.
_pending_tasks: set[asyncio.Task] = set()


def _log_failed_send(task: asyncio.Task) -> None:
    """Release the task reference and log a failure nobody is awaiting.

    When `send_email` schedules the send because a loop is running, no caller
    can see the result. Without this callback an SMTP failure surfaced only as
    asyncio's garbage-collection warning and the email was lost silently;
    retrieving the exception here also marks it as observed, so asyncio stops
    warning about it. The message stays out of the log: recipients are personal
    data.
    """
    _pending_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error("background email send failed: %s", error)


def _email_settings():
    """Build the fastapi-mail connection config from the environment.

    Built lazily (not at import time) so importing this module never depends on
    MAIL_* being present. When credentials are absent the config is still
    valid, it just disables SMTP auth — sending will then fail at the server
    instead of at import.
    """
    from fastapi_mail import ConnectionConfig

    username = os.getenv("MAIL_USERNAME")
    password = os.getenv("MAIL_PASSWORD")
    return ConnectionConfig(
        MAIL_USERNAME=username or "",
        MAIL_PASSWORD=password or "",
        MAIL_FROM=os.getenv("MAIL_FROM", "noreply@example.com"),
        MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME", "SiteGPT"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        # fastapi-mail >=1.x renamed MAIL_TLS/MAIL_SSL to MAIL_STARTTLS/MAIL_SSL_TLS.
        MAIL_STARTTLS=os.getenv("MAIL_TLS", "true").lower() == "true",
        MAIL_SSL_TLS=os.getenv("MAIL_SSL", "false").lower() == "true",
        USE_CREDENTIALS=bool(username and password),
        VALIDATE_CERTS=True,
    )


def _build_message(
    recipient: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
):
    from fastapi_mail import MessageSchema

    # MessageSchema rejects cc/bcc=None, so only pass them when non-empty.
    extra: dict = {}
    if cc:
        extra["cc"] = cc
    if bcc:
        extra["bcc"] = bcc

    return MessageSchema(
        subject=subject,
        recipients=[recipient],
        body=body,
        subtype="html",
        **extra,
    )


async def send_email_async(
    recipient: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
):
    """Actually deliver an email.

    ``FastMail.send_message`` is a coroutine, so it must be awaited: calling it
    without ``await`` builds the coroutine and discards it, meaning nothing is
    ever sent. Async callers (worker jobs, digest, handoff) should use this
    function directly.
    """
    from fastapi_mail import FastMail

    fm = FastMail(_email_settings())
    message = _build_message(recipient, subject, body, cc=cc, bcc=bcc)
    await fm.send_message(message)


def send_email(
    recipient: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
):
    """Sync wrapper around :func:`send_email_async`.

    Kept for synchronous endpoints such as ``api/user.py::forgot_password``.
    Runs the coroutine to completion when no event loop is running; if one is
    (i.e. called from async code), schedules it as a background task instead of
    blocking the loop.
    """
    coro = send_email_async(
        recipient=recipient, subject=subject, body=body, cc=cc, bcc=bcc
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return

    task = loop.create_task(coro)
    _pending_tasks.add(task)
    task.add_done_callback(_log_failed_send)
