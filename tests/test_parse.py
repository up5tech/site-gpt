import os
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_legacy_ppt_is_rejected_as_unsupported(self):
        path = self._write("old.ppt", "binary")
        with self.assertRaises(ValueError) as caught:
            extract_text_from_file(path)
        self.assertIn(".ppt", str(caught.exception))


class PptxExtractionTests(unittest.TestCase):
    """V4-30: slide text plus speaker notes, one block per slide."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _deck(self, slides) -> str:
        from pptx import Presentation
        from pptx.util import Inches

        prs = Presentation()
        for title, body, notes in slides:
            # Blank layout, then an explicit text box: the shape text is what
            # the extractor must read, not the layout's placeholders.
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(2))
            box.text_frame.text = title
            if body:
                box.text_frame.add_paragraph().text = body
            if notes:
                slide.notes_slide.notes_text_frame.text = notes
        path = os.path.join(self.tmp.name, "deck.pptx")
        prs.save(path)
        return path

    def test_a_two_slide_deck_extracts_both_slides_and_their_notes(self):
        path = self._deck(
            [
                ("Quarterly roadmap", "Ship the beta in Q1", "Greet the team first"),
                ("Next steps", "Collect feedback", "Keep it under five minutes"),
            ]
        )

        text = extract_text_from_file(path)

        for expected in (
            "Quarterly roadmap",
            "Ship the beta in Q1",
            "Greet the team first",
            "Next steps",
            "Collect feedback",
            "Keep it under five minutes",
        ):
            self.assertIn(expected, text)
        # The slides keep their order, and each slide's notes follow its text.
        self.assertLess(text.index("Quarterly roadmap"), text.index("Greet the team first"))
        self.assertLess(text.index("Greet the team first"), text.index("Next steps"))
        self.assertLess(text.index("Collect feedback"), text.index("Keep it under five minutes"))

    def test_a_deck_without_any_text_raises_a_clear_error(self):
        from pptx import Presentation

        prs = Presentation()  # no slides at all
        path = os.path.join(self.tmp.name, "empty.pptx")
        prs.save(path)

        with self.assertRaises(ValueError) as caught:
            extract_text_from_file(path)

        self.assertIn("no readable text", str(caught.exception))

    def test_a_deck_with_only_speaker_notes_still_extracts_them(self):
        path = self._deck([("", "", "Only the notes carry the message")])

        self.assertIn(
            "Only the notes carry the message", extract_text_from_file(path)
        )

    def test_missing_python_pptx_raises_import_error(self):
        path = self._deck([("Slide", "Body", "")])

        # `None` in sys.modules is how a missing optional dependency behaves.
        with patch.dict(sys.modules, {"pptx": None}):
            with self.assertRaises(ImportError):
                extract_text_from_file(path)


if __name__ == "__main__":
    unittest.main()
