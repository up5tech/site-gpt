import os
import tempfile
import unittest

from site_gpt.app.services.parse import extract_text_from_file


class ExtractTextFromFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name: str, content: str) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_reads_plain_text_formats(self):
        path = self._write("notes.md", "# Title\n\nSome body text")
        self.assertIn("Some body text", extract_text_from_file(path))

    def test_uses_filename_argument_for_extension(self):
        path = self._write("upload.bin", "a,b,c")
        self.assertEqual(extract_text_from_file(path, "data.csv"), "a,b,c")

    def test_html_strips_tags_scripts_and_styles(self):
        path = self._write(
            "page.html",
            "<html><body><h1>Heading</h1><script>alert('x')</script>"
            "<style>.a{color:red}</style><p>Paragraph</p></body></html>",
        )
        text = extract_text_from_file(path)
        self.assertIn("Heading", text)
        self.assertIn("Paragraph", text)
        self.assertNotIn("alert('x')", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("<h1>", text)

    def test_unsupported_extension_raises_value_error(self):
        path = self._write("archive.zip", "data")
        with self.assertRaises(ValueError):
            extract_text_from_file(path)

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            extract_text_from_file(os.path.join(self.tmp.name, "missing.txt"))


if __name__ == "__main__":
    unittest.main()
