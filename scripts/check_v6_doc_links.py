#!/usr/bin/env python
"""Check the internal links of the V6 decision and risk documents (V6-31 prep).

The V6 record is four Markdown files that point at each other's sections and, in
the risk register, at individual table rows. Nothing renders them in CI, so a
reworded heading or a moved file breaks a link silently. This script resolves
every relative link the four documents carry, and fails on:

* a link whose file does not exist, resolved from the linking document's own
  directory;
* a link whose `#fragment` matches no heading and no explicit
  `<a name="..."></a>` anchor in the target file;
* a fragment that matches a heading slug used more than once in the target, so
  the reader lands on whichever copy GitHub numbered first;
* a risk row in `docs/risk-register-v6.md` without its own `<a name="rN">`
  anchor, or with an anchor naming a different row — the rows are table rows,
  so their anchors are hand-written and can be dropped without any heading
  changing. The rows are read from the register itself, so a row added later is
  checked without this script being edited.

External links (`http:`, `https:`, `mailto:`) are counted and skipped: this is
an offline check with no network access.

Usage (from anywhere; paths resolve against this file):

    uv run python scripts/check_v6_doc_links.py
    python3 scripts/check_v6_doc_links.py docs/preflight-v6.md   # extra files

Exit status is 0 when every link resolves and 1 when any check fails, so it can
be wired into a CI step as-is. It writes nothing and needs no dependencies
beyond the standard library.
"""

from __future__ import annotations

import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The V6 record: the two documents that hold the decisions and the risks, and
# the two that index and gate them. Order is for the report only.
DOCUMENTS = (
    "docs/preflight-v6.md",
    "docs/risk-register-v6.md",
    "plans/PLAN_V6.md",
    "docs/release-v5.md",
)

RISK_REGISTER = "docs/risk-register-v6.md"
# A risk row is a table line whose ID cell is the bold `**RN**` label, with the
# row's anchor — when it has one — sitting in front of it.
RISK_ROW = re.compile(r'^\| (?:<a name="([^"]+)"></a>)?\*\*(R\d+)\*\* \|', re.MULTILINE)

# `[text](target)` and `[text](target "title")`, but not `![alt](image)`.
LINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
CUSTOM_ANCHOR = re.compile(r'<a name="([^"]+)"></a>')
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)


def github_slug(heading: str) -> str:
    """The slug GitHub derives from a heading's text.

    Punctuation is dropped, runs of whitespace are *not* collapsed, and every
    remaining space becomes one hyphen — so an em dash surrounded by spaces
    yields the double hyphen the V6 appendix anchors rely on.
    """
    return re.sub(r"[^\w\s-]", "", heading.strip().lower()).replace(" ", "-")


def heading_slugs(text: str) -> Counter[str]:
    """Every heading slug in a document, counted (duplicates are ambiguous)."""
    slugs: Counter[str] = Counter()
    for line in text.splitlines():
        if line.startswith("#"):
            slugs[github_slug(line.lstrip("#").strip())] += 1
    return slugs


def custom_anchors(text: str) -> set[str]:
    return set(CUSTOM_ANCHOR.findall(text))


def risk_rows(text: str) -> list[tuple[str, str | None]]:
    """Each risk row in the register as (row name, anchor found in its ID cell)."""
    return [(match.group(2), match.group(1)) for match in RISK_ROW.finditer(text)]


class Document:
    """One Markdown file: its resolved anchors and the links it carries."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = path.read_text(encoding="utf-8")
        self.slugs = heading_slugs(self.text)
        self.anchors = custom_anchors(self.text)

    def resolves(self, fragment: str) -> bool:
        return fragment in self.anchors or fragment in self.slugs


def relative_target(link: str) -> bool:
    return not EXTERNAL.match(link)


def load(files: list[str], root: Path) -> dict[Path, Document]:
    """Parse each named document once; paths that do not exist are skipped."""
    documents: dict[Path, Document] = {}
    for name in files:
        path = root / name
        if path.is_file():
            documents[path] = Document(path)
    return documents


def check(files: list[str], root: Path) -> list[str]:
    """Return one message per broken link or missing risk anchor."""
    documents = load(files, root)
    failures: list[str] = []

    def document(path: Path) -> Document:
        # A target outside `files` is parsed on demand: links are resolved
        # wherever they point, not only between the four documents.
        if path not in documents:
            documents[path] = Document(path)
        return documents[path]

    for name in files:
        source = root / name
        if not source.exists():
            failures.append(f"{name}: file does not exist")
            continue
        for link in LINK.findall(document(source).text):
            if not relative_target(link):
                continue
            path_part, _, fragment = link.partition("#")
            target = source if not path_part else (source.parent / path_part).resolve()
            try:
                label = target.relative_to(root.resolve()).as_posix()
            except ValueError:
                failures.append(f"{name}: {link}: target leaves the repository")
                continue
            if not target.is_file():
                failures.append(f"{name}: {link}: no such file ({label})")
                continue
            fragment = urllib.parse.unquote(fragment)
            if not fragment:
                continue
            target_doc = document(target)
            if not target_doc.resolves(fragment):
                failures.append(f"{name}: {link}: no anchor #{fragment} in {label}")
            elif target_doc.slugs[fragment] > 1:
                failures.append(
                    f"{name}: {link}: #{fragment} matches {target_doc.slugs[fragment]}"
                    f" headings in {label}, so it lands on the first"
                )

    register = root / RISK_REGISTER
    if register.is_file():
        rows = risk_rows(document(register).text)
        if not rows:
            failures.append(f"{RISK_REGISTER}: no risk rows found to check")
        for name, anchor in rows:
            expected = name.lower()
            if anchor != expected:
                failures.append(
                    f"{RISK_REGISTER}: row {name} has {'no' if anchor is None else repr(anchor)}"
                    f' anchor in its ID cell, expected <a name="{expected}"></a>'
                )

    return failures


def report(files: list[str], root: Path) -> int:
    documents = load(files, root)

    relative = fragments = external = 0
    for doc in documents.values():
        for link in LINK.findall(doc.text):
            if relative_target(link):
                relative += 1
                fragments += bool(link.partition("#")[2])
            else:
                external += 1

    failures = check(files, root)
    for name in files:
        path = root / name
        if path not in documents:
            print(f"{name}: MISSING")
            continue
        doc = documents[path]
        links = [link for link in LINK.findall(doc.text) if relative_target(link)]
        print(
            f"{name}: {len(links)} relative links, "
            f"{len(doc.slugs)} heading slugs, {len(doc.anchors)} explicit anchors"
        )

    register = documents.get(root / RISK_REGISTER)
    rows = len(risk_rows(register.text)) if register else 0
    print(
        f"\n{relative} relative links ({fragments} with a fragment), "
        f"{external} external links skipped, {rows} risk rows checked"
    )
    if failures:
        print(f"\nFAILED — {len(failures)} problem(s):")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("OK — every relative link and fragment resolves")
    return 0


def main(argv: list[str]) -> int:
    if any(argument in {"-h", "--help"} for argument in argv[1:]):
        print(__doc__)
        return 0
    extra = [argument for argument in argv[1:] if not argument.startswith("-")]
    files = list(DOCUMENTS) + [name for name in extra if name not in DOCUMENTS]
    return report(files, REPO_ROOT)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
