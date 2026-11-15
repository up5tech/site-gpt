"""Unit tests for the Q&A training document (F4).

The rebuild path is the only place an admin-approved answer becomes retrievable,
so these tests pin three behaviours: an unknown website is an error, an empty
approval set removes the document (rejected pairs must stop being retrievable),
and a non-empty set re-embeds through the normal ingest path.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from site_gpt.app import models
from site_gpt.app.services import qa_training
from site_gpt.app.services.ingest import split_text


def _chain(**kwargs):
    """A query chain stub. `all_value=`/`first_value=`/`count_value=` set the
    terminal method's return value."""
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.join.return_value = chain
    chain.order_by.return_value = chain
    for name, value in kwargs.items():
        method = name[: -len("_value")] if name.endswith("_value") else name
        getattr(chain, method).return_value = value
    return chain


class RebuildQaDocumentTests(unittest.TestCase):
    def test_unknown_website_raises(self):
        db = MagicMock()
        db.query.return_value = _chain(first_value=None)
        with self.assertRaises(ValueError):
            qa_training.rebuild_qa_document(db, uuid4())

    def test_no_approved_pairs_deletes_the_document(self):
        document = models.ExtraDocument(
            name=qa_training.QA_DOCUMENT_NAME,
            content="Q: old\nA: stale\n\n",
            website_id=uuid4(),
            company_id=uuid4(),
        )
        db = MagicMock()
        db.query.side_effect = [
            _chain(first_value=SimpleNamespace(company_id=uuid4())),
            _chain(first_value=document),
        ]

        with patch.object(qa_training, "approved_pairs", return_value=[]):
            result = qa_training.rebuild_qa_document(db, uuid4())

        self.assertEqual(
            result, {"approved": 0, "chunks": 0, "extra_document_id": None}
        )
        db.delete.assert_called_once_with(document)
        db.commit.assert_called_once()

    def test_no_pairs_and_no_document_is_a_no_op(self):
        db = MagicMock()
        db.query.side_effect = [
            _chain(first_value=SimpleNamespace(company_id=uuid4())),
            _chain(first_value=None),
        ]

        with patch.object(qa_training, "approved_pairs", return_value=[]):
            result = qa_training.rebuild_qa_document(db, uuid4())

        self.assertEqual(result["approved"], 0)
        db.delete.assert_not_called()

    def test_approved_pairs_update_and_re_embed_the_document(self):
        website_id = uuid4()
        document = models.ExtraDocument(
            id=uuid4(),
            name=qa_training.QA_DOCUMENT_NAME,
            content="old",
            website_id=website_id,
            company_id=uuid4(),
        )
        db = MagicMock()
        db.query.side_effect = [
            _chain(first_value=SimpleNamespace(company_id=uuid4())),
            _chain(first_value=document),
        ]
        pairs = [("How much is it?", "Ten dollars."), ("Is it open?", "Yes.")]

        with patch.object(qa_training, "approved_pairs", return_value=pairs), patch.object(
            qa_training, "ingest_extra_document"
        ) as ingest:
            result = qa_training.rebuild_qa_document(db, website_id)

        expected_body = "Q: How much is it?\nA: Ten dollars.\n\nQ: Is it open?\nA: Yes.\n\n"
        self.assertEqual(document.content, expected_body)
        self.assertEqual(result["approved"], 2)
        self.assertEqual(result["chunks"], len(split_text(expected_body)))
        self.assertEqual(result["extra_document_id"], str(document.id))
        ingest.assert_called_once_with(db, document.id, expected_body)
        db.commit.assert_called_once()

    def test_new_document_is_created_when_none_exists(self):
        website_id = uuid4()
        db = MagicMock()
        db.query.side_effect = [
            _chain(first_value=SimpleNamespace(company_id=uuid4())),
            _chain(first_value=None),
        ]

        with patch.object(
            qa_training, "approved_pairs", return_value=[("q", "a")]
        ), patch.object(qa_training, "ingest_extra_document"):
            qa_training.rebuild_qa_document(db, website_id)

        created = db.add.call_args.args[0]
        self.assertIsInstance(created, models.ExtraDocument)
        self.assertEqual(created.website_id, website_id)
        self.assertEqual(created.name, qa_training.QA_DOCUMENT_NAME)
        self.assertEqual(created.content, "Q: q\nA: a\n\n")


class RenderPairsTests(unittest.TestCase):
    def test_format_matches_the_corpus(self):
        self.assertEqual(
            qa_training.render_pairs([("Q1", "A1"), ("Q2", "A2")]),
            "Q: Q1\nA: A1\n\nQ: Q2\nA: A2\n\n",
        )

    def test_empty_input_renders_nothing(self):
        self.assertEqual(qa_training.render_pairs([]), "")


if __name__ == "__main__":
    unittest.main()
