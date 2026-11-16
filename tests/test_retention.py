"""Retention purge tests (F9).

The property under test is the one that matters for a delete: a row older than
the policy goes, and a row that is not goes nowhere. These run against a real
SQLite database holding only the tables the purge touches, so the filter and the
`DELETE` are the ones production builds — not a mock's opinion of them.
"""

import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models
from site_gpt.app.db.base import Base
from site_gpt.app.services import retention

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
TABLES = [
    models.Company.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.ChatFeedback.__table__,
    models.HandoffRequest.__table__,
    models.Contact.__table__,
    models.DigestLog.__table__,
    models.Setting.__table__,
    # Uploads: the file bytes live on disk, so the row and the file go together.
    models.User.__table__,
    models.ExtraDocument.__table__,
    models.Attachment.__table__,
    models.Document.__table__,
    models.Embedding.__table__,
]


def _session():
    """An in-memory database with just the tables the purge touches."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    return engine, sessionmaker(bind=engine)()


def _company(db, name="Acme"):
    company = models.Company(name=name)
    db.add(company)
    db.commit()
    return company


def _website(db, company, name="site"):
    website = models.Website(
        company_id=company.id, name=name, url=f"https://{name}.test", site_map_url=""
    )
    db.add(website)
    db.commit()
    return website


def _seed(db, website, company, created_at, session_id="s1"):
    """One row in every purged table, all with the same `created_at`."""
    db.add_all(
        [
            models.ChatMessage(
                website_id=website.id,
                session_id=session_id,
                role="user",
                message="hi",
                created_at=created_at,
                updated_at=created_at,
            ),
            models.ChatFeedback(
                website_id=website.id,
                session_id=session_id,
                rating="up",
                created_at=created_at,
                updated_at=created_at,
            ),
            models.HandoffRequest(
                website_id=website.id,
                session_id=session_id,
                status="pending",
                created_at=created_at,
                updated_at=created_at,
            ),
            models.Contact(
                website_id=website.id,
                session_id=session_id,
                first_name="A",
                last_name="B",
                email="a@b.test",
                created_at=created_at,
                updated_at=created_at,
            ),
        ]
    )
    db.add(
        models.DigestLog(
            company_id=company.id,
            period_start=created_at,
            period_end=created_at + timedelta(days=7),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    db.commit()


def _counts(db):
    return {
        "chat_messages": db.query(models.ChatMessage).count(),
        "chat_feedback": db.query(models.ChatFeedback).count(),
        "handoff_requests": db.query(models.HandoffRequest).count(),
        "contacts": db.query(models.Contact).count(),
        "digest_log": db.query(models.DigestLog).count(),
    }


def _user(db, company, email="owner@acme.test"):
    user = models.User(
        company_id=company.id,
        email=email,
        password_hash="x",
        first_name="A",
        last_name="B",
    )
    db.add(user)
    db.commit()
    return user


def _upload(db, company, created_at, name="doc.txt", file_url=None, user=None):
    """An uploaded document plus the attachment row pointing at its file."""
    document = models.ExtraDocument(
        name=name,
        content="text",
        company_id=company.id,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(document)
    db.commit()
    attachment = models.Attachment(
        extra_document_id=None if user else document.id,
        user_id=None if user is None else user.id,
        filename=name,
        status="uploaded",
        file_url=file_url or f"{uuid4().hex}.txt",
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(attachment)
    db.commit()
    return attachment


class DeleteInBatchesTests(unittest.TestCase):
    """The shared helper both retention passes use must stay bounded."""

    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self.website = _website(self.db, self.company)
        for index in range(5):
            _seed(
                self.db,
                self.website,
                self.company,
                NOW - timedelta(days=10, minutes=index),
                session_id=f"b{index}",
            )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _filters(self):
        return [models.ChatMessage.created_at < NOW - timedelta(days=1)]

    def test_a_dry_run_counts_and_commits_nothing(self):
        commits = {"n": 0}
        real_commit = self.db.commit

        def commit():
            commits["n"] += 1
            real_commit()

        self.db.commit = commit
        counted = retention.delete_in_batches(
            self.db, models.ChatMessage, self._filters(), 2, dry_run=True
        )

        self.assertEqual(counted, 5)
        self.assertEqual(commits["n"], 0)
        self.assertEqual(self.db.query(models.ChatMessage).count(), 5)

    def test_each_batch_commits_before_the_next(self):
        commits = {"n": 0}
        real_commit = self.db.commit

        def commit():
            commits["n"] += 1
            real_commit()

        self.db.commit = commit
        deleted = retention.delete_in_batches(
            self.db, models.ChatMessage, self._filters(), 2
        )

        self.assertEqual(deleted, 5)
        # 2 + 2 + 1
        self.assertEqual(commits["n"], 3)
        self.assertEqual(self.db.query(models.ChatMessage).count(), 0)

    def test_nothing_to_do_costs_no_commit(self):
        commits = {"n": 0}
        real_commit = self.db.commit

        def commit():
            commits["n"] += 1
            real_commit()

        self.db.commit = commit
        deleted = retention.delete_in_batches(
            self.db,
            models.ChatMessage,
            [models.ChatMessage.created_at < NOW - timedelta(days=365)],
            2,
        )

        self.assertEqual(deleted, 0)
        self.assertEqual(commits["n"], 0)


class RetentionIndexTests(unittest.TestCase):
    """The purge's filters must stay backed by an index, not just work."""

    def test_attachments_created_at_is_indexed(self):
        # `purge_attachments` filters and orders by this column, so without the
        # index every batch reads the whole upload table.
        index = next(
            (
                item
                for item in models.Attachment.__table__.indexes
                if item.name == "idx_attachments_created_at"
            ),
            None,
        )

        self.assertIsNotNone(index, "Attachment must declare idx_attachments_created_at")
        self.assertEqual(
            [column.name for column in index.columns], ["created_at"]
        )

    def test_extra_documents_company_and_created_at_are_indexed(self):
        # `purge_documents` filters on both columns and orders by created_at, so
        # the single-column company_id index is not enough.
        index = next(
            (
                item
                for item in models.ExtraDocument.__table__.indexes
                if item.name == "idx_extra_documents_company_id_created_at"
            ),
            None,
        )

        self.assertIsNotNone(
            index, "ExtraDocument must declare idx_extra_documents_company_id_created_at"
        )
        self.assertEqual(
            [column.name for column in index.columns], ["company_id", "created_at"]
        )

    def test_document_expiry_probe_is_indexed(self):
        # `document_expiry` asks per document "any attachment at/after the cutoff?";
        # the composite lets that probe stay inside the index.
        index = next(
            (
                item
                for item in models.Attachment.__table__.indexes
                if item.name == "idx_attachments_extra_document_id_created_at"
            ),
            None,
        )

        self.assertIsNotNone(index, "Attachment must declare the expiry probe index")
        self.assertEqual(
            [column.name for column in index.columns],
            ["extra_document_id", "created_at"],
        )

    def test_the_expiry_probe_migration_builds_it_concurrently(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "e2a7c5d913f6_v2_document_attachments_index.py"
        )
        source = path.read_text(encoding="utf-8")

        self.assertIn("idx_attachments_extra_document_id_created_at", source)
        self.assertIn("postgresql_concurrently=True", source)
        self.assertIn("autocommit_block()", source)
        self.assertIn("down_revision: Union[str, Sequence[str], None] = 'd5b9c4e2a87f'", source)

    def test_the_covered_attachment_index_is_gone(self):
        names = {item.name for item in models.Attachment.__table__.indexes}

        self.assertNotIn("idx_attachments_extra_document_id", names)
        self.assertIn("idx_attachments_extra_document_id_created_at", names)

    def test_the_attachment_drop_migration_drops_it_concurrently(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "f7c1d84b2e39_v2_drop_covered_attachment_index.py"
        )
        source = path.read_text(encoding="utf-8")

        self.assertIn("drop_index", source)
        self.assertIn("'idx_attachments_extra_document_id'", source)
        self.assertIn("postgresql_concurrently=True", source)
        self.assertIn("autocommit_block()", source)
        self.assertIn("down_revision: Union[str, Sequence[str], None] = 'e2a7c5d913f6'", source)

    def test_the_covered_single_column_index_is_gone(self):
        # The composite's `company_id` prefix serves every lookup the old index
        # served, so keeping it would only add write cost.
        names = {item.name for item in models.ExtraDocument.__table__.indexes}

        self.assertNotIn("idx_extra_documents_company_id", names)
        self.assertIn("idx_extra_documents_company_id_created_at", names)

    def test_the_drop_migration_drops_it_concurrently(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "d5b9c4e2a87f_v2_drop_covered_document_index.py"
        )
        source = path.read_text(encoding="utf-8")

        self.assertIn("drop_index", source)
        self.assertIn("'idx_extra_documents_company_id'", source)
        self.assertIn("postgresql_concurrently=True", source)
        self.assertIn("autocommit_block()", source)
        self.assertIn("down_revision: Union[str, Sequence[str], None] = 'c3f8a2b91d47'", source)

    def test_the_document_index_migration_builds_it_concurrently(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "c3f8a2b91d47_v2_extra_documents_retention_index.py"
        )
        source = path.read_text(encoding="utf-8")

        self.assertIn("idx_extra_documents_company_id_created_at", source)
        self.assertIn("postgresql_concurrently=True", source)
        self.assertIn("autocommit_block()", source)
        self.assertIn("down_revision: Union[str, Sequence[str], None] = 'a4c1e9d7f320'", source)

    def test_the_index_migration_builds_it_concurrently(self):
        # A plain CREATE INDEX locks writes on the upload table for the whole
        # build; the retention indexes are all built CONCURRENTLY.
        path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "a4c1e9d7f320_v2_attachment_created_at_index.py"
        )
        source = path.read_text(encoding="utf-8")

        self.assertIn("idx_attachments_created_at", source)
        self.assertIn("postgresql_concurrently=True", source)
        self.assertIn("autocommit_block()", source)
        self.assertIn("down_revision: Union[str, Sequence[str], None] = 'e7b3c94a1d52'", source)


class UploadRetentionTests(unittest.TestCase):
    """An expired upload must lose both its row and its bytes."""

    def setUp(self):
        self.engine, self.db = _session()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        patcher = patch.object(retention, "UPLOAD_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.company = _company(self.db)
        self.website = _website(self.db, self.company)
        self.other = _company(self.db, "Other")
        self.old = NOW - timedelta(days=10)
        self.fresh = NOW - timedelta(hours=1)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _write(self, file_url, content="bytes"):
        path = os.path.join(self.root, file_url)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def test_dry_run_counts_uploads_without_deleting_anything(self):
        attachment = _upload(self.db, self.company, self.old)
        path = self._write(attachment.file_url)

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=True, now=NOW
        )

        self.assertEqual(result["deleted"]["attachments"], 1)
        self.assertEqual(result["deleted"]["extra_documents"], 1)
        # A dry run removes nothing, files included.
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.db.query(models.Attachment).count(), 1)

    def test_purge_deletes_the_expired_row_and_its_file(self):
        old = _upload(self.db, self.company, self.old)
        old_path = self._write(old.file_url)
        fresh = _upload(self.db, self.company, self.fresh, name="new.txt")
        fresh_path = self._write(fresh.file_url, "new")

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["attachments"], 1)
        self.assertFalse(os.path.exists(old_path))
        self.assertEqual(
            [row.id for row in self.db.query(models.Attachment).all()], [fresh.id]
        )
        self.assertTrue(os.path.exists(fresh_path))

    def test_another_companys_upload_is_untouched(self):
        theirs = _upload(self.db, self.other, self.old)
        their_path = self._write(theirs.file_url)

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["attachments"], 0)
        self.assertTrue(os.path.exists(their_path))
        self.assertEqual(self.db.query(models.Attachment).count(), 1)

    def test_an_upload_never_attached_to_a_document_is_scoped_by_its_uploader(self):
        mine = _upload(self.db, self.company, self.old, user=_user(self.db, self.company))
        path = self._write(mine.file_url)

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        # The row has no `extra_document_id`; the uploader's company is what makes
        # it ours (and deletable) rather than orphaned.
        self.assertEqual(result["deleted"]["attachments"], 1)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.db.query(models.Attachment).count(), 0)

    def test_the_document_text_and_its_embeddings_go_with_the_upload(self):
        attachment = _upload(self.db, self.company, self.old)
        document_id = attachment.extra_document_id
        self.db.add(
            models.Embedding(
                extra_document_id=document_id,
                content="the document's text",
                created_at=self.old,
                updated_at=self.old,
            )
        )
        self.db.commit()

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["extra_documents"], 1)
        # The text is gone, so the assistant cannot keep answering from it…
        self.assertEqual(
            self.db.query(models.ExtraDocument).filter_by(id=document_id).count(), 0
        )
        # …and neither can the embeddings built from it.
        self.assertEqual(
            self.db.query(models.Embedding)
            .filter(models.Embedding.extra_document_id == document_id)
            .count(),
            0,
        )

    def test_a_text_only_document_expires_too(self):
        # No attachment and no file: the text is the document, so it must go.
        document = models.ExtraDocument(
            name="notes",
            content="pasted text",
            company_id=self.company.id,
            created_at=self.old,
            updated_at=self.old,
        )
        self.db.add(document)
        self.db.commit()

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["extra_documents"], 1)
        self.assertEqual(self.db.query(models.ExtraDocument).count(), 0)

    def test_a_fresh_upload_keeps_an_old_document_alive(self):
        # Imported 40 days ago, used today: the new file is current use, and
        # deleting the document with it would throw away fresh text and embeddings.
        document = self._old_text_document()
        document_id = document.id
        # The document already had an old file; the new upload must not cost it.
        old = _upload(self.db, self.company, self.old, name="week1.txt")
        fresh = _upload(self.db, self.company, self.fresh, name="today.txt")
        # Re-point both at the old document; drop the documents `_upload` made.
        orphans = [old.extra_document_id, fresh.extra_document_id]
        old.extra_document_id = document_id
        fresh.extra_document_id = document_id
        self.db.query(models.ExtraDocument).filter(
            models.ExtraDocument.id.in_(orphans)
        ).delete(synchronize_session=False)
        self.db.commit()
        old_id, fresh_id = old.id, fresh.id
        old_path = self._write(old.file_url, "week one")
        fresh_path = self._write(fresh.file_url, "today")

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["extra_documents"], 0)
        self.assertEqual(result["deleted"]["attachments"], 0)
        self.assertEqual(
            self.db.query(models.ExtraDocument).filter_by(id=document_id).count(), 1
        )
        self.assertEqual(
            self.db.query(models.Attachment).filter_by(id=fresh_id).count(), 1
        )
        self.assertTrue(os.path.exists(fresh_path))
        # The document is in use, so its earlier files stay with it.
        self.assertEqual(
            self.db.query(models.Attachment).filter_by(id=old_id).count(), 1
        )
        self.assertTrue(os.path.exists(old_path))

    def test_an_old_document_still_expires_when_its_attachments_are_old(self):
        # The guard must not turn into "never delete a document with a file".
        document = self._old_text_document()
        document_id = document.id
        attachment = _upload(self.db, self.company, self.old)
        attachment.extra_document_id = document_id
        self.db.commit()

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["extra_documents"], 2)  # ours + helper's
        self.assertEqual(
            self.db.query(models.ExtraDocument).filter_by(id=document_id).count(), 0
        )

    def _old_text_document(self):
        document = models.ExtraDocument(
            name="old-notes",
            content="pasted text",
            company_id=self.company.id,
            created_at=self.old,
            updated_at=self.old,
        )
        self.db.add(document)
        self.db.commit()
        return document

    def test_a_fresh_document_survives_and_another_company_is_untouched(self):
        fresh = _upload(self.db, self.company, self.fresh, name="new.txt")
        theirs = _upload(self.db, self.other, self.old, name="their.txt")

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["extra_documents"], 0)
        remaining = {
            row.id for row in self.db.query(models.ExtraDocument).all()
        }
        self.assertEqual(
            remaining, {fresh.extra_document_id, theirs.extra_document_id}
        )

    def test_a_missing_file_does_not_stop_the_purge(self):
        attachment = _upload(self.db, self.company, self.old)

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["attachments"], 1)
        self.assertEqual(self.db.query(models.Attachment).count(), 0)

    def test_a_file_url_cannot_delete_outside_the_upload_directory(self):
        outside = os.path.join(os.path.dirname(self.root), "not-ours.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("keep me")
        self.addCleanup(os.remove, outside)
        _upload(self.db, self.company, self.old, file_url="../not-ours.txt")

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW
        )

        # The row goes (it is expired data); the file outside uploads/ stays.
        self.assertEqual(result["deleted"]["attachments"], 1)
        self.assertTrue(os.path.exists(outside))
        self.assertEqual(self.db.query(models.Attachment).count(), 0)


class ParseTests(unittest.TestCase):
    def test_zero_and_junk_mean_keep_for_ever(self):
        for raw in (None, "", "0", "-5", "abc", "30 days"):
            self.assertEqual(retention.parse_retention_days(raw), 0, raw)

    def test_positive_values_are_read_and_clamped(self):
        self.assertEqual(retention.parse_retention_days("30"), 30)
        self.assertEqual(retention.parse_retention_days(" 7 "), 7)
        self.assertEqual(retention.parse_retention_days(14), 14)
        self.assertEqual(
            retention.parse_retention_days("999999"), retention.MAX_RETENTION_DAYS
        )

    def test_cutoff_matches_the_policy(self):
        self.assertIsNone(retention.cutoff_for(0, NOW))
        self.assertEqual(retention.cutoff_for(30, NOW), NOW - timedelta(days=30))

    def test_naive_now_is_treated_as_utc(self):
        cutoff = retention.cutoff_for(1, datetime(2026, 11, 15, 12, 0))
        self.assertEqual(cutoff, datetime(2026, 11, 14, 12, 0, tzinfo=UTC))


class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self.website = _website(self.db, self.company)
        self.other = _company(self.db, "Other")
        self.other_site = _website(self.db, self.other, "other")

        # 10 days old, 30 days old, and one row exactly at the cutoff.
        self.old = NOW - timedelta(days=10)
        self.older = NOW - timedelta(days=30)
        self.fresh = NOW - timedelta(hours=1)
        _seed(self.db, self.website, self.company, self.old)
        _seed(self.db, self.website, self.company, self.older, session_id="s2")
        _seed(self.db, self.website, self.company, self.fresh, session_id="s3")
        # Another tenant, same age: must never be touched.
        _seed(self.db, self.other_site, self.other, self.older)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_dry_run_counts_without_deleting(self):
        result = retention.purge_company(self.db, self.company.id, days=7, dry_run=True, now=NOW)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["retention_days"], 7)
        self.assertEqual(result["cutoff"], NOW - timedelta(days=7))
        self.assertEqual(
            result["deleted"],
            {
                "chat_messages": 2,
                "chat_feedback": 2,
                "handoff_requests": 2,
                "contacts": 2,
                "digest_log": 2,
                "attachments": 0,
                "extra_documents": 0,
            },
        )
        self.assertEqual(result["total"], 10)
        # Nothing was removed: 3 of ours (2 old + 1 fresh) still there.
        self.assertEqual(_counts(self.db)["chat_messages"], 4)

    def test_purge_deletes_only_rows_past_the_cutoff(self):
        result = retention.purge_company(self.db, self.company.id, days=7, dry_run=False, now=NOW)

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["total"], 10)
        self.assertEqual(
            _counts(self.db),
            {
                # one fresh message of ours + the other tenant's row
                "chat_messages": 2,
                "chat_feedback": 2,
                "handoff_requests": 2,
                "contacts": 2,
                "digest_log": 2,
            },
        )
        remaining = {
            row.session_id
            for row in self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.website.id)
            .all()
        }
        self.assertEqual(remaining, {"s3"})

    def test_the_cutoff_row_itself_survives(self):
        # A row created exactly at the cutoff is not older than it.
        _seed(self.db, self.website, self.company, NOW - timedelta(days=7), session_id="edge")
        retention.purge_company(self.db, self.company.id, days=7, dry_run=False, now=NOW)

        survivors = {
            row.session_id
            for row in self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.website.id)
            .all()
        }
        self.assertEqual(survivors, {"s3", "edge"})

    def test_zero_days_is_a_no_op(self):
        result = retention.purge_company(self.db, self.company.id, days=0, dry_run=False, now=NOW)
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["cutoff"])
        self.assertEqual(_counts(self.db)["chat_messages"], 4)

    def test_other_companies_are_never_deleted(self):
        retention.purge_company(self.db, self.other.id, days=7, dry_run=False, now=NOW)
        self.assertEqual(
            self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.website.id)
            .count(),
            3,
        )
        self.assertEqual(
            self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.other_site.id)
            .count(),
            0,
        )

    def test_company_without_websites_reports_zeroes(self):
        lonely = _company(self.db, "Lonely")
        result = retention.purge_company(self.db, lonely.id, days=7, dry_run=False, now=NOW)
        self.assertEqual(result["total"], 0)

    def test_policy_is_read_from_the_setting(self):
        self.db.add(
            models.Setting(company_id=self.company.id, key="retention_days", value="7")
        )
        self.db.commit()

        result = retention.purge_company(self.db, self.company.id, dry_run=True, now=NOW)
        self.assertEqual(result["retention_days"], 7)
        self.assertEqual(result["total"], 10)

    def _count_commits(self):
        """Count commits so batching is observable, not just "it worked"."""
        counter = {"n": 0}
        real_commit = self.db.commit

        def commit():
            counter["n"] += 1
            real_commit()

        self.db.commit = commit
        return counter

    def test_deletes_run_in_bounded_batches(self):
        # Two more expired rows per table (four in total), then one row per
        # commit: a large tenant must never do one unbounded DELETE.
        for index, tag in enumerate(("s4", "s5"), start=1):
            # A slightly different timestamp per seed: `digest_log` is unique on
            # (company_id, period_start) and these rows must all stay expired.
            _seed(
                self.db,
                self.website,
                self.company,
                self.old - timedelta(minutes=index),
                session_id=tag,
            )
        commits = self._count_commits()

        result = retention.purge_company(
            self.db,
            self.company.id,
            days=7,
            dry_run=False,
            now=NOW,
            batch_size=1,
        )

        self.assertEqual(result["deleted"]["chat_messages"], 4)
        self.assertEqual(result["total"], 20)
        # five tables x four rows, one commit each
        self.assertEqual(commits["n"], 20)
        # everything expired went, the fresh and the other tenant's rows stayed
        self.assertEqual(_counts(self.db)["chat_messages"], 2)

    def test_a_larger_batch_takes_fewer_commits_and_deletes_the_same_rows(self):
        commits = self._count_commits()

        result = retention.purge_company(
            self.db,
            self.company.id,
            days=7,
            dry_run=False,
            now=NOW,
            batch_size=100,
        )

        self.assertEqual(result["total"], 10)
        # one batch per table: fewer than the batch size was returned
        self.assertEqual(commits["n"], 5)

    def test_a_zero_batch_size_falls_back_to_one_row(self):
        commits = self._count_commits()

        result = retention.purge_company(
            self.db, self.company.id, days=7, dry_run=False, now=NOW, batch_size=0
        )

        self.assertEqual(result["total"], 10)
        self.assertEqual(commits["n"], 10)

    def test_dry_run_never_commits(self):
        commits = self._count_commits()

        retention.purge_company(
            self.db, self.company.id, days=7, dry_run=True, now=NOW, batch_size=1
        )

        self.assertEqual(commits["n"], 0)
        self.assertEqual(_counts(self.db)["chat_messages"], 4)

    def test_only_companies_with_a_policy_are_scheduled(self):
        self.db.add_all(
            [
                models.Setting(company_id=self.company.id, key="retention_days", value="30"),
                models.Setting(company_id=self.other.id, key="retention_days", value="0"),
            ]
        )
        self.db.commit()

        self.assertEqual(retention.companies_with_policy(self.db), [self.company.id])


if __name__ == "__main__":
    unittest.main()
