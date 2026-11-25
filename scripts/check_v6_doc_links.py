#!/usr/bin/env python
"""Check the internal links of the V6 decision and risk documents (V6-31 prep).

The checked set is every page under `docs/`, every plan under `plans/` and
`README.md` — Markdown that points at each other's sections and, in the risk
register, at individual table rows. Nothing renders them in CI, so a
reworded heading or a moved file breaks a link silently. This script resolves
every relative link those documents carry, and fails on:

* a link whose file does not exist, resolved from the linking document's own
  directory;
* a link whose `#fragment` matches no heading and no explicit
  `<a name="..."></a>` anchor in the target file;
* a fragment that matches a heading slug used more than once in the target, so
  the reader lands on whichever copy GitHub numbered first;
* a `docs/` page no scanned document links to, so nothing reaches it from
  README. A page reached only through a plain-text mention is reported as a
  note rather than a failure: the reader can still find it, but not by following
  a link. Reachability only means something for a complete scan, so it is
  skipped when README is not among the documents being checked;
* a plain-text reference to a repository document (`docs/platform.md`,
  `plans/PLAN_V4.md`, `README.md`) whose file does not exist. The record also
  names documents without a Markdown link — `docs/security.md` points at
  `docs/platform.md` and `docs/billing.md` that way — and those were invisible to
  a link-only check. These references are repo-relative by convention, so they
  resolve from the repository root, not from the linking document;
* a risk row in `docs/risk-register-v6.md` without its own `<a name="rN">`
  anchor, or with an anchor naming a different row — the rows are table rows,
  so their anchors are hand-written and can be dropped without any heading
  changing. The rows are read from the register itself, so a row added later is
  checked without this script being edited.

It also checks the decision-to-risk mapping the record keeps in three places,
and fails when they disagree: the risks an appendix actually references must be
exactly the risks its register cell lists, each of those risk rows must name the
decision back in its evidence cell, and the appendix's sign-off item must copy
the approval into every risk the cell names. A risk mention in an appendix only
counts as a reference when it links to the row or when its sentence introduces
it as this decision's risk row or a recorded residual, so an incidental "see R3
for the gate" cannot widen a cell. References written "V5 D10–D12" name V5's
decisions and are ignored.

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

# Every page under `docs/` and every plan under `plans/` is scanned, plus
# README. A hand-kept list had to be extended each time a document gained a link
# — the four that only ever appeared as link targets (`api-v1.md`, `billing.md`,
# `platform.md`, `worker-delivery.md`) went unchecked for exactly that reason.
# The older plans are scanned on the same terms as V6: their plain-text
# references are what a maintainer follows, historical or not. Only Markdown at
# the top of each directory is included: subdirectories would need a policy of
# their own. Order is for the report only.
def default_documents(root: Path) -> tuple[str, ...]:
    pages = sorted(
        path.relative_to(root).as_posix()
        for directory in (root / "docs", root / "plans")
        for path in directory.glob("*.md")
    )
    return (*pages, "README.md")


DOCUMENTS = default_documents(REPO_ROOT)

PREFLIGHT = "docs/preflight-v6.md"
RISK_REGISTER = "docs/risk-register-v6.md"
# A risk row is a table line whose ID cell is the bold `**RN**` label, with the
# row's anchor — when it has one — sitting in front of it.
RISK_ROW = re.compile(r'^\| (?:<a name="([^"]+)"></a>)?\*\*(R\d+)\*\* \|', re.MULTILINE)

# `[text](target)` and `[text](target "title")`, but not `![alt](image)`.
LINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
CUSTOM_ANCHOR = re.compile(r'<a name="([^"]+)"></a>')
# A repository document named in prose or backticks, not as a link target.
PLAIN_DOC = re.compile(
    r"(?<![\w/.-])((?:docs|plans)/[A-Za-z0-9._/-]+\.md|README\.md)"
)
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)

# The decision register's header, the appendix headings and the sign-off item
# that copies an approval into the risk rows.
REGISTER_HEADER = "| ID | Question | Status | Risk rows |"
APPENDIX_HEADING = re.compile(r"^## Appendix — (D\d+) decision brief", re.MULTILINE)
RISK = re.compile(r"\bR(\d+)\b")
DECISION = re.compile(r"\bD(\d+)\b")
COPY_LIST = "copied into"
# "V5 D10–D12" and "V5 D11" are V5's decision numbers, not this record's.
V5_DECISION = re.compile(r"V5 D\d+(?:\s*[–—-]\s*D\d+)?")
# A mention counts as a reference only as a link to the row, or in a sentence
# that introduces it as this decision's row or a residual recorded against it.
RISK_REFERENCE = re.compile(r"\[(?:risk )?R\d+\]\(risk-register-v6\.md#r\d+\)")
FRAMING = re.compile(
    r"risk rows?|the rows\b|residual|recorded against|accepted against", re.IGNORECASE
)
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


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


def by_number(name: str) -> int:
    """Sort key for D1..D13 / R1..R12, so 10 comes after 9."""
    return int(name[1:])


def plain_risks(text: str) -> set[str]:
    """Every risk ID in the text, however it is written."""
    return {f"R{number}" for number in RISK.findall(text)}


def referenced_risks(text: str) -> set[str]:
    """The risks an appendix refers to, ignoring incidental mentions.

    A sentence counts when it links to the row or frames the mention as this
    decision's risk row or a residual recorded against it; a passing "see R3
    for the gate" elsewhere in the section does not.
    """
    found: set[str] = set()
    for sentence in SENTENCE.split(text):
        if RISK_REFERENCE.search(sentence) or FRAMING.search(sentence):
            found |= plain_risks(sentence)
    return found


def v6_decisions(text: str) -> set[str]:
    return {f"D{number}" for number in DECISION.findall(V5_DECISION.sub("", text))}


def decision_register(text: str) -> dict[str, set[str]]:
    """Each register row as decision -> the risks its Risk rows cell names."""
    lines = text.splitlines()
    header = next(
        (index for index, line in enumerate(lines) if line.startswith(REGISTER_HEADER)),
        None,
    )
    if header is None:
        return {}
    rows: dict[str, set[str]] = {}
    for line in lines[header + 2 :]:
        if not line.startswith("|"):
            break
        cells = line.split("|")
        if len(cells) < 5:
            continue
        decision = v6_decisions(cells[1])
        if len(decision) != 1:
            continue
        rows[decision.pop()] = plain_risks(cells[4])
    return rows


def appendix_sections(text: str) -> dict[str, str]:
    """Each appendix body, keyed by its decision, without the heading itself."""
    matches = list(APPENDIX_HEADING.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end() : end]
    return sections


def risk_row_decisions(text: str) -> dict[str, set[str]]:
    """Each register row as risk -> the decisions its own row names."""
    rows: dict[str, set[str]] = {}
    for line in text.splitlines():
        match = RISK_ROW.match(line)
        if match:
            rows[match.group(2)] = v6_decisions(line)
    return rows


def mapping_failures(register_text: str, preflight_text: str) -> tuple[list[str], int]:
    """Return the disagreements between the register and the appendices."""
    cells = decision_register(preflight_text)
    sections = appendix_sections(preflight_text)
    backwards = risk_row_decisions(register_text)
    failures: list[str] = []

    if not cells:
        failures.append(f"{PREFLIGHT}: no decision register table found to check")
    if not sections:
        failures.append(f"{PREFLIGHT}: no appendix headings found to check")

    pairings = 0
    for decision in sorted(cells, key=by_number):
        risks = cells[decision]
        pairings += len(risks)
        section = sections.get(decision)
        if section is None:
            failures.append(f"{PREFLIGHT}: {decision} has a register row but no appendix")
            continue

        referenced = referenced_risks(section)
        unlisted = sorted(referenced - risks, key=by_number)
        unreferenced = sorted(risks - referenced, key=by_number)
        if unlisted:
            failures.append(
                f"{PREFLIGHT}: {decision}'s appendix names {', '.join(unlisted)}"
                " but its register cell does not"
            )
        if unreferenced:
            failures.append(
                f"{PREFLIGHT}: {decision}'s register cell names {', '.join(unreferenced)}"
                " but its appendix does not reference it"
            )

        for risk in sorted(risks, key=by_number):
            if decision not in backwards.get(risk, set()):
                failures.append(
                    f"{RISK_REGISTER}: {risk} does not name {decision} back in its row"
                )

        copies = [line for line in section.splitlines() if COPY_LIST in line]
        if not copies:
            failures.append(
                f"{PREFLIGHT}: {decision} has no sign-off item copying the approval"
                " into its risk rows"
            )
            continue
        omitted = sorted(risks - plain_risks("\n".join(copies)), key=by_number)
        if omitted:
            failures.append(
                f"{PREFLIGHT}: {decision}'s sign-off copy list omits {', '.join(omitted)}"
            )

    for decision in sorted(sections, key=by_number):
        if decision not in cells:
            failures.append(f"{PREFLIGHT}: {decision} has an appendix but no register row")

    for risk in sorted(backwards, key=by_number):
        for decision in sorted(backwards[risk], key=by_number):
            if risk not in cells.get(decision, set()):
                failures.append(
                    f"{RISK_REGISTER}: {risk} names {decision}, whose register cell"
                    f" does not list {risk}"
                )

    return failures, pairings


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


def plain_document_references(text: str) -> list[str]:
    """Every repo document named in prose, ignoring Markdown link targets."""
    without_links = LINK.sub("", text)
    return sorted(set(PLAIN_DOC.findall(without_links)))


def page_graph(name: str, root: Path) -> tuple[set[str], set[str]]:
    """A document's outgoing edges: Markdown links, and plain-text mentions."""
    source = root / name
    text = Document(source).text
    linked: set[str] = set()
    for link in LINK.findall(text):
        if not relative_target(link):
            continue
        path_part = link.partition("#")[0]
        if not path_part:
            continue
        try:
            linked.add(
                (source.parent / path_part)
                .resolve()
                .relative_to(root.resolve())
                .as_posix()
            )
        except ValueError:  # outside the repository, reported elsewhere
            continue
    return linked, set(plain_document_references(text))


def _walk(start: str, graph: dict[str, set[str]]) -> set[str]:
    """Every node reachable from `start`, staying inside the graph's nodes."""
    seen = {start}
    stack = [start]
    while stack:
        for target in graph.get(stack.pop(), ()):
            if target in graph and target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def reachability(files: list[str], root: Path) -> tuple[set[str], set[str]]:
    """Pages reachable from README through links, and through links or mentions."""
    graph: dict[str, set[str]] = {}
    mentions: dict[str, set[str]] = {}
    for name in files:
        if (root / name).is_file():
            graph[name], mentions[name] = page_graph(name, root)
    if "README.md" not in graph:
        return set(), set()
    loose = {name: edges | mentions.get(name, set()) for name, edges in graph.items()}
    return _walk("README.md", graph), _walk("README.md", loose)


def plain_text_only_pages(files: list[str], root: Path) -> list[str]:
    """docs pages reached only because something names them in prose."""
    linked, loose = reachability(files, root)
    return [
        name
        for name in files
        if name.startswith("docs/") and name in loose and name not in linked
    ]


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
        # wherever they point, not only between the listed documents.
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
                # Reported once: the same text also matches PLAIN_DOC below, but
                # the link check already names the fragment precisely.
                failures.append(f"{name}: {link}: no anchor #{fragment} in {label}")
            elif target_doc.slugs[fragment] > 1:
                failures.append(
                    f"{name}: {link}: #{fragment} matches {target_doc.slugs[fragment]}"
                    f" headings in {label}, so it lands on the first"
                )

        for reference in plain_document_references(document(source).text):
            # A link target is checked above with its fragment; a bare mention
            # has nothing but its path, and an invented one reads as a file that
            # exists. Resolved from the root because that is how they are
            # written everywhere in the record.
            if not (root / reference).is_file():
                failures.append(f"{name}: {reference}: no such document")

    # Only a complete scan can say a page is unreachable; checking one file on
    # its own would report every other page as an orphan.
    linked, loose = reachability(files, root)
    if "README.md" in files:
        for name in files:
            if not name.startswith("docs/") or name in loose:
                continue
            failures.append(
                f"{name}: no scanned document links to it, so nothing reaches it"
                " from README"
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

    preflight = root / PREFLIGHT
    if preflight.is_file() and register.is_file():
        failures.extend(
            mapping_failures(document(register).text, document(preflight).text)[0]
        )

    return failures


def report(files: list[str], root: Path) -> int:
    documents = load(files, root)

    relative = fragments = external = plain = 0
    for doc in documents.values():
        for link in LINK.findall(doc.text):
            if relative_target(link):
                relative += 1
                fragments += bool(link.partition("#")[2])
            else:
                external += 1
        plain += len(plain_document_references(doc.text))

    failures = check(files, root)
    notes = plain_text_only_pages(files, root)
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
    preflight = documents.get(root / PREFLIGHT)
    cells = decision_register(preflight.text) if preflight else {}
    pairings = sum(len(risks) for risks in cells.values())
    print(
        f"\n{relative} relative links ({fragments} with a fragment), "
        f"{external} external links skipped, {plain} plain-text document "
        f"references, {rows} risk rows and "
        f"{len(cells)} decisions ({pairings} decision-risk pairings) checked"
    )
    for name in notes:
        print(
            f"note: {name} is reachable only through a plain-text mention, "
            "not a link"
        )
    if failures:
        print(f"\nFAILED — {len(failures)} problem(s):")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("OK — every link resolves and the decision-risk mapping agrees")
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
