import unittest
from types import SimpleNamespace

from site_gpt.app.services.rag import collect_sources, format_history


class CollectSourcesTests(unittest.TestCase):
    def test_dedupes_by_url_and_keeps_first_seen(self):
        results = [
            {"content": "a", "title": "Page A", "url": "https://a", "source_type": "page"},
            {"content": "b", "title": "Page A", "url": "https://a", "source_type": "page"},
            {"content": "c", "title": "Manual", "url": None, "source_type": "document"},
        ]
        self.assertEqual(
            collect_sources(results),
            [
                {"title": "Page A", "url": "https://a", "source_type": "page"},
                {"title": "Manual", "url": None, "source_type": "document"},
            ],
        )

    def test_rows_without_title_or_url_are_skipped(self):
        self.assertEqual(
            collect_sources(
                [{"content": "x", "title": None, "url": None, "source_type": "document"}]
            ),
            [],
        )

    def test_empty_results(self):
        self.assertEqual(collect_sources([]), [])


class FormatHistoryTests(unittest.TestCase):
    def test_renders_roles_in_order(self):
        messages = [
            SimpleNamespace(role="user", message="hi"),
            SimpleNamespace(role="assistant", message="hello"),
        ]
        self.assertEqual(format_history(messages), "User: hi\nAssistant: hello\n")

    def test_empty_history_is_empty_string(self):
        self.assertEqual(format_history([]), "")

    def test_non_user_roles_render_as_assistant(self):
        messages = [SimpleNamespace(role="system", message="context")]
        self.assertEqual(format_history(messages), "Assistant: context\n")


if __name__ == "__main__":
    unittest.main()
