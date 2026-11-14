import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from site_gpt.app.services import rag
from site_gpt.app.services.rag import NO_CONTEXT_ANSWER


def make_db(rows):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        company_id=uuid4()
    )
    db.execute.return_value.mappings.return_value.all.return_value = rows
    return db


def row(content, distance, title="Doc", url=None, source_type="document"):
    return {
        "content": content,
        "title": title,
        "url": url,
        "source_type": source_type,
        "distance": distance,
    }


def execute_sql(db):
    return str(db.execute.call_args.args[0])


class SearchDistanceTests(unittest.TestCase):
    def test_distance_is_selected_for_every_chunk(self):
        rows = [row("a", 0.11), row("b", 0.42)]
        db = make_db(rows)

        results = rag.search(db, [0.1, 0.2], uuid4(), max_distance=0.5)

        self.assertIn("AS distance", execute_sql(db))
        self.assertEqual([r["distance"] for r in results], [0.11, 0.42])

    def test_chunks_above_threshold_are_dropped(self):
        db = make_db([row("good", 0.2), row("meh", 0.61), row("junk", 0.95)])

        results = rag.search(db, [0.1], uuid4(), max_distance=0.5)

        self.assertEqual([r["content"] for r in results], ["good"])

    def test_all_chunks_above_threshold_returns_empty(self):
        db = make_db([row("junk1", 0.8), row("junk2", 0.9)])

        self.assertEqual(rag.search(db, [0.1], uuid4(), max_distance=0.5), [])

    def test_row_without_distance_is_dropped(self):
        db = make_db([{"content": "x", "title": "t", "url": None,
                       "source_type": "document", "distance": None}])

        self.assertEqual(rag.search(db, [0.1], uuid4(), max_distance=0.5), [])

    def test_negative_threshold_disables_filtering(self):
        db = make_db([row("far", 1.9)])

        results = rag.search(db, [0.1], uuid4(), max_distance=-1)

        self.assertEqual(len(results), 1)

    def test_default_threshold_comes_from_config(self):
        db = make_db([row("close", 0.1), row("far", 0.4)])

        with patch.object(rag, "RAG_MAX_DISTANCE", 0.2):
            results = rag.search(db, [0.1], uuid4())

        self.assertEqual([r["content"] for r in results], ["close"])

    def test_limit_is_still_passed_through(self):
        db = make_db([])

        rag.search(db, [0.1], uuid4(), limit=3)

        self.assertEqual(db.execute.call_args.args[1]["limit"], 3)


class NoContextShortcutTests(unittest.TestCase):
    def setUp(self):
        self.website_id = uuid4()

    def test_ask_returns_canned_answer_without_calling_the_llm(self):
        with patch.object(rag, "embed_texts", return_value=[[0.1, 0.2]]), patch.object(
            rag, "search", return_value=[]
        ), patch.object(rag, "save_message") as save, patch.object(
            rag, "get_llm"
        ) as get_llm:
            result = rag.ask(MagicMock(), self.website_id, "sess", "who won?")

        self.assertEqual(result, {"answer": NO_CONTEXT_ANSWER, "sources": []})
        get_llm.assert_not_called()
        self.assertEqual(
            [call.args[3] for call in save.call_args_list], ["user", "assistant"]
        )
        self.assertEqual(save.call_args_list[1].args[4], NO_CONTEXT_ANSWER)

    def test_ask_stream_emits_canned_answer_without_calling_the_llm(self):
        async def collect():
            return [
                event
                async for event in rag.ask_stream(
                    MagicMock(), self.website_id, "sess", "who won?"
                )
            ]

        with patch.object(rag, "embed_texts", return_value=[[0.1, 0.2]]), patch.object(
            rag, "search", return_value=[]
        ), patch.object(rag, "save_message"), patch.object(rag, "get_llm") as get_llm:
            events = asyncio.run(collect())

        get_llm.assert_not_called()
        self.assertEqual(len(events), 2)
        first = json.loads(events[0].removeprefix("data: ").strip())
        last = json.loads(events[1].removeprefix("data: ").strip())
        self.assertEqual(first, {"chunk": NO_CONTEXT_ANSWER})
        self.assertEqual(last, {"done": True, "sources": []})

    def test_ask_stream_done_event_after_normal_answer_carries_sources(self):
        chunk = SimpleNamespace(content="hello")

        async def fake_astream(messages):  # assigned to an instance, no `self`
            yield chunk

        llm = MagicMock()
        llm.astream = fake_astream
        results = [row("ctx", 0.1, url="https://example.com/page", source_type="page")]

        async def collect():
            return [
                event
                async for event in rag.ask_stream(
                    MagicMock(), self.website_id, "sess", "hi"
                )
            ]

        with patch.object(rag, "embed_texts", return_value=[[0.1]]), patch.object(
            rag, "search", return_value=results
        ), patch.object(rag, "get_chat_history", return_value=[]), patch.object(
            rag, "save_message"
        ), patch.object(rag, "get_llm", return_value=llm):
            events = asyncio.run(collect())

        last = json.loads(events[-1].removeprefix("data: ").strip())
        self.assertEqual(last["sources"][0]["url"], "https://example.com/page")


if __name__ == "__main__":
    unittest.main()
