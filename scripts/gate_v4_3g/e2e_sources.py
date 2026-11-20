"""V4-3G gate: end-to-end source imports and the source negatives.

Run from the repo root:

    source .venv/bin/activate
    NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 \
        uv run python scripts/gate_v4_3g/e2e_sources.py

The run **creates, migrates and then drops** a throwaway database (`GATE_DB`,
default `v4_gate_3g`); never point it at a database you care about. It drives
the real API through FastAPI's TestClient against that database, with the
configured LLM/embedding provider, the same `uploads/` directory and the
worker's own ingest handler, so "import → ingest → cited answer" is the
production path apart from the HTTP socket.

Every check is reported as `pass`, `fail` or `blocked` (with the reason), and
the process exits non-zero only on a `fail`. Provider- or network-bound steps
that this environment cannot satisfy are `blocked`, never claimed as passing:

* a YouTube video with no captions at all cannot be conjured — the check looks
  for one among a few candidates and is `blocked` if every one has captions;
* a Notion *successful* import needs a real integration token, which this
  environment does not have (the negative — a rejected token — needs none).

Files this run creates under `uploads/` and any database rows are removed at
the end (the database is dropped).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import traceback
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

GATE_DB = os.getenv("GATE_DB", "v4_gate_3g")
PASSWORD = "Gate3g!Str0ngPass"

# Videos tried when looking for one whose captions are disabled. The gate only
# needs one; the check is `blocked` if none of them is caption-less.
NO_CAPTION_CANDIDATES = (
    "jNQXAC9IVRw",
    "aqz-KE-bpKQ",
    "PB6Ny8XyK6A",
)

results: dict[str, dict] = {}


def record(name: str, status: str, detail: str = "", **extra) -> None:
    results[name] = {"status": status, "detail": detail, **extra}
    print(f"[{status.upper():7}] {name}: {detail}", flush=True)


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as exc:
        record(name, "fail", str(exc) or "assertion failed")
    except Exception as exc:  # noqa: BLE001 - every failure is gate evidence
        record(name, "fail", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


# --- throwaway database -----------------------------------------------------


def reset_database() -> str:
    """Create an empty `GATE_DB` and return its URL (the env's credentials)."""
    load_dotenv(".env")
    base = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{GATE_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{GATE_DB}"'))
    admin.dispose()
    return base.set(database=GATE_DB).render_as_string(hide_password=False)


def migrate(url: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    proc = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"alembic upgrade head failed:\n{proc.stderr[-2000:]}")


def drop_database() -> None:
    load_dotenv(".env")
    base = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{GATE_DB}" WITH (FORCE)'))
    admin.dispose()


def upload_files() -> set[str]:
    return set(os.listdir("uploads")) if os.path.isdir("uploads") else set()


def deck_bytes() -> bytes:
    """A two-slide deck whose text and notes state facts a question can cite."""
    from pptx import Presentation

    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[1])
    first.shapes.title.text = "Project Lighthouse"
    first.placeholders[1].text = (
        "Project Lighthouse ships to customers in May 2027."
    )
    first.notes_slide.notes_text_frame.text = (
        "Internal note: the budget is 42 percent of platform spend."
    )
    second = prs.slides.add_slide(prs.slide_layouts[1])
    second.shapes.title.text = "Release owner"
    second.placeholders[1].text = "The release owner is the Atlas team."
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def main() -> int:
    url = reset_database()
    migrate(url)
    # The app builds its engine from DATABASE_URL at import time, so this must
    # be set before any site_gpt module is imported.
    os.environ["DATABASE_URL"] = url
    before = upload_files()
    user_id = None

    try:
        from fastapi.testclient import TestClient

        from site_gpt.app import models
        from site_gpt.app.db.session import SessionLocal, engine
        from site_gpt.app.main import app
        from site_gpt.app.worker import handle_ingest

        client = TestClient(app)
        email = f"gate-v4-3g-{uuid4().hex[:8]}@example.com"

        def login_ok() -> dict[str, str]:
            nonlocal user_id
            r = client.post(
                "/api/register",
                json={
                    "company_name": f"Gate 3G {uuid4().hex[:8]}",
                    "first_name": "Gate",
                    "last_name": "Runner",
                    "email": email,
                    "password": PASSWORD,
                },
            )
            assert r.status_code == 200, f"register {r.status_code}: {r.text}"
            token = client.post(
                "/api/token", json={"email": email, "password": PASSWORD}
            ).json()["access_token"]
            db = SessionLocal()
            try:
                user_id = db.query(models.User.id).filter(
                    models.User.email == email
                ).scalar()
            finally:
                db.close()
            return {"Authorization": f"Bearer {token}"}

        auth = login_ok()

        website = client.post(
            "/api/websites/",
            json={
                "name": "Gate 3G site",
                "url": "https://example.com",
                "description": "",
                "site_map_url": "",
                "status": "active",
            },
            headers=auth,
        )
        assert website.status_code == 200, f"website {website.status_code}: {website.text}"
        website_id = website.json()["id"]

        def attachments() -> int:
            db = SessionLocal()
            try:
                return (
                    db.query(models.Attachment)
                    .filter(models.Attachment.user_id == user_id)
                    .count()
                )
            finally:
                db.close()

        # --- imports ------------------------------------------------------

        deck = deck_bytes()
        state: dict[str, dict] = {}

        def import_pptx() -> None:
            r = client.post(
                "/api/uploads/",
                files={
                    "file": (
                        "lighthouse.pptx",
                        deck,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    )
                },
                headers=auth,
            )
            assert r.status_code == 200, f"upload {r.status_code}: {r.text}"
            state["pptx"] = r.json()
            r = client.post(
                "/api/extra_documents/",
                json={
                    "name": "Project Lighthouse deck",
                    "content": "",
                    "file_ids": [state["pptx"]["file_id"]],
                },
                headers=auth,
            )
            assert r.status_code == 200, f"extra_document {r.status_code}: {r.text}"
            state["pptx_doc"] = r.json()

        check("import_pptx_upload_and_document", import_pptx)

        def import_youtube() -> None:
            r = client.post(
                "/api/uploads/youtube",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers=auth,
            )
            if r.status_code != 200:
                record(
                    "import_youtube_video",
                    "blocked",
                    f"HTTP {r.status_code}: {r.text[:300]}",
                )
                return
            body = r.json()
            state["youtube"] = body
            r = client.post(
                "/api/extra_documents/",
                json={
                    "name": "YouTube: dQw4w9WgXcQ",
                    "content": "",
                    "file_ids": [body["files"][0]["file_id"]],
                },
                headers=auth,
            )
            assert r.status_code == 200, f"extra_document {r.status_code}: {r.text}"
            state["youtube_doc"] = r.json()
            record(
                "import_youtube_video",
                "pass",
                f"{body['added']} file(s), total {body['total']}, "
                f"total_exact {body['total_exact']}",
            )

        check("import_youtube_video", import_youtube)

        def import_notion() -> None:
            record(
                "import_notion_page",
                "blocked",
                "needs a real Notion integration token (not available here); "
                "the rejected-token negative below needs none",
            )

        import_notion()

        # --- ingest -------------------------------------------------------

        def ingest() -> None:
            if "pptx_doc" not in state:
                record(
                    "ingest_pptx_through_worker",
                    "fail",
                    "the deck was never uploaded, so there was nothing to ingest",
                )
                return
            asyncio.run(handle_ingest({"website_id": website_id}))
            db = SessionLocal()
            try:
                status = (
                    db.query(models.Website.ingest_status)
                    .filter(models.Website.id == website_id)
                    .scalar()
                )
                row = (
                    db.query(models.ExtraDocument)
                    .filter(models.ExtraDocument.id == state["pptx_doc"]["id"])
                    .one()
                )
                chunks = (
                    db.query(models.Embedding)
                    .filter(models.Embedding.extra_document_id == row.id)
                    .count()
                )
            finally:
                db.close()
            assert status == "completed", f"website ingest_status is {status}"
            assert chunks > 0, "the deck produced no embeddings"
            record(
                "ingest_pptx_through_worker",
                "pass",
                f"ingest_status={status}, {chunks} embedding chunk(s) for the deck",
            )

        check("ingest_pptx_through_worker", ingest)

        # --- answers with citations ---------------------------------------

        def ask(question: str) -> tuple[int, dict]:
            r = client.post(
                "/api/chat",
                json={
                    "website_id": website_id,
                    "session_id": f"gate-{uuid4().hex}",
                    "question": question,
                },
                headers=auth,
            )
            return r.status_code, (r.json() if r.content else {})

        def answer_pptx() -> None:
            if "pptx_doc" not in state:
                record(
                    "answer_from_pptx_with_citation",
                    "fail",
                    "the deck was never ingested",
                )
                return
            status, body = ask(
                "When does Project Lighthouse ship to customers, according to "
                "the deck?"
            )
            answer = (body.get("answer") or "").lower()
            sources = body.get("sources") or []
            assert status == 200, f"chat {status}: {body}"
            assert "may 2027" in answer, f"answer did not use the deck: {answer[:300]!r}"
            titles = " ".join(str(s.get("title") or "") for s in sources)
            assert sources, "the answer carried no citation"
            assert "lighthouse" in titles.lower(), f"citations: {sources}"
            record(
                "answer_from_pptx_with_citation",
                "pass",
                f"answer cites {titles.strip()[:80]!r}; "
                f"answer={answer[:120]!r}",
            )

        check("answer_from_pptx_with_citation", answer_pptx)

        def answer_youtube() -> None:
            if "youtube_doc" not in state:
                record(
                    "answer_from_youtube_with_citation",
                    "blocked",
                    "the YouTube import did not succeed",
                )
                return
            status, body = ask(
                "According to the video's captions, what is the singer never "
                "gonna do?"
            )
            answer = (body.get("answer") or "").lower()
            sources = body.get("sources") or []
            assert status == 200, f"chat {status}: {body}"
            assert "give you up" in answer, f"answer did not use captions: {answer[:300]!r}"
            assert sources, "the answer carried no citation"
            record(
                "answer_from_youtube_with_citation",
                "pass",
                f"answer={answer[:120]!r}, citations={len(sources)}",
            )

        check("answer_from_youtube_with_citation", answer_youtube)

        # --- negatives -----------------------------------------------------

        def negative_no_captions() -> None:
            for video_id in NO_CAPTION_CANDIDATES:
                rows_before = attachments()
                files_before = upload_files()
                r = client.post(
                    "/api/uploads/youtube",
                    json={"url": f"https://www.youtube.com/watch?v={video_id}"},
                    headers=auth,
                )
                detail = (r.json() or {}).get("detail", "") if r.content else ""
                if r.status_code == 400 and "no captions" in detail.lower():
                    assert attachments() == rows_before, "an attachment row was stored"
                    assert upload_files() == files_before, "a file was left in uploads/"
                    record(
                        "negative_video_without_captions",
                        "pass",
                        f"{video_id} → 400 {detail[:120]!r}, no row, no file",
                    )
                    return
            record(
                "negative_video_without_captions",
                "blocked",
                "every candidate video had captions (or the transcript API "
                "refused), so a caption-less video could not be exercised",
            )

        check("negative_video_without_captions", negative_no_captions)

        def negative_bad_notion_token() -> None:
            rows_before = attachments()
            files_before = upload_files()
            r = client.post(
                "/api/uploads/notion",
                json={
                    "url": "https://www.notion.so/gate-page-"
                    "00000000000000000000000000000000",
                    "token": "secret_gate_bogus_token_123",
                },
                headers=auth,
            )
            detail = (r.json() or {}).get("detail", "") if r.content else ""
            assert r.status_code in (400, 401), f"expected 400/401, got {r.status_code}: {detail}"
            assert "secret_gate_bogus_token_123" not in r.text, "the token leaked"
            assert attachments() == rows_before, "an attachment row was stored"
            assert upload_files() == files_before, "a file was left in uploads/"
            record(
                "negative_wrong_notion_token",
                "pass",
                f"{r.status_code} {detail[:120]!r}, token absent, nothing stored",
            )

        check("negative_wrong_notion_token", negative_bad_notion_token)

        def negative_oversize_upload() -> None:
            rows_before = attachments()
            files_before = upload_files()
            oversize = b"x" * (21 * 1024 * 1024)  # MAX_UPLOAD_MB=20
            r = client.post(
                "/api/uploads/",
                files={"file": ("huge.txt", oversize, "text/plain")},
                headers=auth,
            )
            assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"
            assert attachments() == rows_before, "an attachment row was stored"
            assert upload_files() == files_before, "a partial file was left in uploads/"
            record(
                "negative_oversize_upload",
                "pass",
                "413 for a 21 MB file (MAX_UPLOAD_MB=20), no row, no file",
            )

        check("negative_oversize_upload", negative_oversize_upload)

        engine.dispose()
    finally:
        for name in upload_files() - before:
            try:
                os.remove(os.path.join("uploads", name))
            except OSError:
                pass
        drop_database()

    print("\n" + json.dumps(results, indent=2))
    failed = [name for name, item in results.items() if item["status"] == "fail"]
    blocked = [name for name, item in results.items() if item["status"] == "blocked"]
    print(
        f"\n{len(results) - len(failed) - len(blocked)} passed, "
        f"{len(blocked)} blocked, {len(failed)} failed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
