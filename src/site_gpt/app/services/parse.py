"""Extract plain text from uploaded files so they can be embedded into the RAG.

Text-like formats are handled with the standard library. PDF/DOCX use optional
dependencies (pypdf, python-docx) that are declared in pyproject.toml; if they are
not installed the helper raises a clear error instead of failing silently.
"""

import os

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
                print(f"[parse] pdf page extract error: {e}")
        return "\n".join(parts)

    # --- Word ---
    if ext in ("docx", "doc"):
        from docx import Document as DocxDocument

        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text)

    raise ValueError(f"Unsupported file type: .{ext}")
