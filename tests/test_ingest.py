import unittest

from site_gpt.app.services.ingest import split_text


class SplitTextTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(split_text("hello world"), ["hello world"])

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(split_text(""), [])

    def test_long_text_is_split_into_chunks_of_at_most_1000_chars(self):
        text = " ".join(f"word{i}" for i in range(600))
        chunks = split_text(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1000)

    def test_chunks_cover_all_content(self):
        words = [f"token{i}" for i in range(400)]
        chunks = split_text(" ".join(words))
        joined = " ".join(chunks)
        for word in (words[0], words[-1]):
            self.assertIn(word, joined)


if __name__ == "__main__":
    unittest.main()
