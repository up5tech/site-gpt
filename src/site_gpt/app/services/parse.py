"""Extract plain text from uploaded files so they can be embedded into the RAG.

Text-like formats are handled with the standard library. PDF/DOCX/PPTX use
optional dependencies (pypdf, python-docx, python-pptx) that are declared in
pyproject.toml; if they are not installed the helper raises a clear error instead
of failing silently.
"""

import logging
import os

from site_gpt.app.core.logging import log_exception

TEXT_EXTENSIONS = {
    "txt",
    "text",
    "md",
    "markdown",
    "csv",
    "tsv",
    "json",
    "log",
    "yml",
    "yaml",
}


def extract_text_from_file(path: str, filename: str = "") -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    ext = (filename or os.path.basename(path)).lower().rsplit(".", 1)[-1]

    # --- Plain text formats (no extra deps) ---
    if ext in TEXT_EXTENSIONS:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    # --- HTML / XML -> strip tags ---
    if ext in ("html", "htm", "xml"):
        from bs4 import BeautifulSoup

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(separator="\n")

    # --- PDF ---
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception as e:
                log_exception("parse.pdf_page_failed", e, level=logging.WARNING)
        return "\n".join(parts)

    # --- Word ---
    if ext in ("docx", "doc"):
        from docx import Document as DocxDocument

        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text)

    # --- PowerPoint ---
    if ext == "pptx":
        # python-pptx (D2) is branch-local like pypdf/docx, so a deployment
        # without it answers an ImportError instead of breaking every import.
        from pptx import Presentation

        presentation = Presentation(path)
        slides: list[str] = []
        for slide in presentation.slides:
            # Every shape that carries text: title/body placeholders and any
            # added text box, in the slide's own order.
            parts = [
                shape.text_frame.text.strip()
                for shape in slide.shapes
                if shape.has_text_frame and shape.text_frame.text.strip()
            ]
            notes = _speaker_notes(slide)
            if notes:
                parts.append(notes)
            if parts:
                slides.append("\n".join(parts))

        if not slides:
            raise ValueError(
                "The presentation contains no readable text: add text to its "
                "slides or speaker notes and try again."
            )
        # One block per slide, so a chunk never mixes two decks' slides.
        return "\n\n".join(slides)

    raise ValueError(f"Unsupported file type: .{ext}")


def _speaker_notes(slide) -> str:
    """The slide's speaker notes, or "" when it has no notes slide.

    `slide.notes_slide` creates one on access, so the presence check matters:
    reading the notes of a deck without any must not mutate it.
    """
    if not slide.has_notes_slide:
        return ""
    notes_frame = slide.notes_slide.notes_text_frame
    if notes_frame is None:
        return ""
    return notes_frame.text.strip()
