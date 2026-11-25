"""V6-31 prep: the doc link checker, and the fact that it covers security.md.

What is pinned here:

* a relative link is resolved from the linking document's own directory, so a
  moved target and a renamed heading both fail with the offending link;
* a fragment resolves against headings and explicit `<a name="…">` anchors, and
  a slug used twice is reported instead of silently landing on the first;
* the GitHub slug keeps the double hyphen an em dash surrounded by spaces
  produces, which is what the V6 appendix anchors rely on;
* one helper turns a link into a path for every check, and each document is
  parsed once however many checks read it;
* a document named in prose (`docs/platform.md`) is resolved from the repository
  root and must exist, while the same path used as a link target is not counted
  twice;
* a `docs/` page nothing links to and nothing names is a failure, a page linked
  from any scanned document passes even when that document is not itself linked
  from README, and a page only named in prose is a note naming that document;
* `docs/security.md` and `README.md` are checked documents — both because they
  are in `DOCUMENTS` and because a broken link in a copy of one is caught — so
  their links are no longer verified by eye;
* the scanned set is a glob, not a list: every top-level `docs/*.md` and every
  `plans/*.md` is in `DOCUMENTS`, and a new page under `docs/` is picked up (and
  its links checked) without editing the script;
* the record in this checkout passes, so the suite fails when a heading or a
  file is renamed without the links being updated.
"""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_v6_doc_links.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_v6_doc_links_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


links = _load_script()


class CheckerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class ResolutionTests(CheckerTestCase):
    def test_a_link_that_resolves_reports_nothing(self):
        self.write("docs/other.md", "# Other\n")
        self.write("docs/index.md", "See [other](other.md#other).\n")

        self.assertEqual(links.check(["docs/index.md"], self.root), [])

    def test_document_links_resolves_from_the_linking_directory(self):
        self.write("docs/a.md", "# A\n\n[x](sub/b.md#Head%20Two) [self](#top)\n")

        found = links.document_links(links.Document(self.root / "docs/a.md"))

        self.assertEqual([found_link for found_link, _, _ in found], [
            "sub/b.md#Head%20Two",
            "#top",
        ])
        self.assertEqual(found[0][1].resolve(), (self.root / "docs/sub/b.md").resolve())
        self.assertEqual(found[1][1].resolve(), (self.root / "docs/a.md").resolve())
        self.assertEqual(found[0][2], "Head Two")

    def test_each_document_is_parsed_once_across_the_checks(self):
        self.write("README.md", "# Readme\n\nSee [a](docs/a.md) and `docs/b.md`.\n")
        self.write("docs/a.md", "# A\n\nSee [b](b.md).\n")
        self.write("docs/b.md", "# B\n")
        files = ["README.md", "docs/a.md", "docs/b.md"]

        class CountingDocument(links.Document):
            reads: Counter = Counter()

            def __init__(self, path):
                CountingDocument.reads[path.name] += 1
                super().__init__(path)

        with mock.patch.object(links, "Document", CountingDocument):
            with contextlib.redirect_stdout(io.StringIO()):
                exit_status = links.report(files, self.root)

        self.assertEqual(exit_status, 0)
        self.assertEqual(
            dict(CountingDocument.reads),
            {"README.md": 1, "a.md": 1, "b.md": 1},
        )

    def test_a_missing_file_is_reported_with_the_link(self):
        self.write("docs/index.md", "See [gone](gone.md).\n")

        failures = links.check(["docs/index.md"], self.root)

        self.assertEqual(len(failures), 1)
        self.assertIn("gone.md", failures[0])
        self.assertIn("no such file", failures[0])

    def test_a_missing_fragment_is_reported(self):
        self.write("docs/other.md", "# Other\n")
        self.write("docs/index.md", "See [other](other.md#renamed).\n")

        failures = links.check(["docs/index.md"], self.root)

        self.assertEqual(len(failures), 1)
        self.assertIn("#renamed", failures[0])

    def test_an_explicit_anchor_resolves_a_table_row(self):
        self.write("docs/other.md", '| <a name="r13"></a>**R13** | row |\n')
        self.write("docs/index.md", "See [R13](other.md#r13).\n")

        self.assertEqual(links.check(["docs/index.md"], self.root), [])

    def test_a_repeated_heading_slug_is_ambiguous(self):
        self.write("docs/other.md", "# Notes\n\n# Notes\n")
        self.write("docs/index.md", "See [notes](other.md#notes).\n")

        failures = links.check(["docs/index.md"], self.root)

        self.assertEqual(len(failures), 1)
        self.assertIn("matches 2 headings", failures[0])

    def test_an_em_dash_space_produces_a_double_hyphen(self):
        # `## Appendix — D13 decision brief` must slug the way GitHub does,
        # otherwise every D-anchor in the record would be reported broken.
        self.assertEqual(
            links.github_slug("Appendix — D13 decision brief"),
            "appendix--d13-decision-brief",
        )


class ReachabilityTests(CheckerTestCase):
    def test_an_orphan_page_is_a_failure(self):
        self.write("README.md", "# Readme\n")
        self.write("docs/orphan.md", "# Orphan\n")

        failures = links.check(["README.md", "docs/orphan.md"], self.root)

        self.assertEqual(len(failures), 1)
        self.assertIn("docs/orphan.md", failures[0])
        self.assertIn("no scanned document links to it", failures[0])

    def test_a_page_linked_from_an_unreachable_document_is_reachable(self):
        # The rule is "some scanned document links it", not "README can reach
        # it": a plan nothing links to still counts as an entry point.
        self.write("README.md", "# Readme\n")
        self.write("plans/PLAN_V9.md", "# Plan\n\nSee [target](../docs/target.md).\n")
        self.write("docs/target.md", "# Target\n")

        files = ["README.md", "plans/PLAN_V9.md", "docs/target.md"]

        self.assertEqual(links.check(files, self.root), [])
        self.assertEqual(links.prose_only_notes(files, self.root), [])

    def test_a_page_reached_through_another_page_passes(self):
        self.write("README.md", "# Readme\n\nSee [a](docs/a.md).\n")
        self.write("docs/a.md", "# A\n\nSee [b](b.md).\n")
        self.write("docs/b.md", "# B\n")

        files = ["README.md", "docs/a.md", "docs/b.md"]

        self.assertEqual(links.check(files, self.root), [])
        self.assertEqual(links.prose_only_notes(files, self.root), [])

    def test_a_page_named_only_in_prose_is_a_note_not_a_failure(self):
        self.write("README.md", "# Readme\n\nSee `docs/notes.md` for details.\n")
        self.write("docs/notes.md", "# Notes\n")

        files = ["README.md", "docs/notes.md"]

        self.assertEqual(links.check(files, self.root), [])
        notes = links.prose_only_notes(files, self.root)
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("docs/notes.md"), notes[0])
        self.assertIn("README.md", notes[0])

    def test_reachability_is_skipped_when_readme_is_not_scanned(self):
        # A single-file run cannot judge reachability; it must not report the
        # one page it was given as an orphan.
        self.write("docs/alone.md", "# Alone\n")

        self.assertEqual(links.check(["docs/alone.md"], self.root), [])
        self.assertEqual(links.prose_only_notes(["docs/alone.md"], self.root), [])


class PlainReferenceTests(CheckerTestCase):
    def test_a_missing_plain_reference_is_caught(self):
        self.write("docs/index.md", "See docs/gone.md for the runbook.\n")

        failures = links.check(["docs/index.md"], self.root)

        self.assertEqual(len(failures), 1)
        self.assertIn("docs/gone.md", failures[0])
        self.assertIn("no such document", failures[0])

    def test_a_plain_reference_resolves_from_the_repository_root(self):
        # `docs/index.md` naming `docs/other.md` must find docs/other.md; a
        # linking-directory resolution would look for docs/docs/other.md.
        self.write("docs/other.md", "# Other\n")
        self.write("docs/index.md", "See `docs/other.md`.\n")

        self.assertEqual(links.check(["docs/index.md"], self.root), [])

    def test_a_link_target_is_not_counted_as_a_plain_reference(self):
        self.write("docs/other.md", "# Other\n")
        text = "See [other](docs/other.md) and `README.md`.\n"

        self.assertEqual(
            links.plain_document_references(text), ["README.md"]
        )


class SecurityDocumentTests(CheckerTestCase):
    def test_security_md_is_one_of_the_checked_documents(self):
        self.assertIn("docs/security.md", links.DOCUMENTS)

    def test_a_broken_link_in_a_security_copy_is_caught(self):
        self.write(
            "docs/security.md",
            "# Security\n\n## 5. Residuals\n\nSee [R13](risk-register-v6.md#r13).\n",
        )

        failures = links.check(["docs/security.md"], self.root)

        self.assertEqual(len(failures), 1)
        self.assertIn("risk-register-v6.md", failures[0])
        self.assertIn("no such file", failures[0])

    def test_readme_is_one_of_the_checked_documents(self):
        self.assertIn("README.md", links.DOCUMENTS)

    def test_a_broken_fragment_in_a_readme_copy_is_caught(self):
        self.write(
            "README.md",
            "# Readme\n\nSee [billing](docs/billing.md#no-such-section).\n",
        )
        self.write("docs/billing.md", "# Billing\n")

        failures = links.check(["README.md"], self.root)

        self.assertEqual(len(failures), 1)
        self.assertIn("#no-such-section", failures[0])

    def test_every_docs_page_is_scanned(self):
        pages = sorted(path.name for path in (REPO_ROOT / "docs").glob("*.md"))
        self.assertGreater(len(pages), 5)
        for name in pages:
            self.assertIn(f"docs/{name}", links.DOCUMENTS)

    def test_every_plan_is_scanned(self):
        plans = sorted(path.name for path in (REPO_ROOT / "plans").glob("*.md"))
        self.assertGreater(len(plans), 3)
        for name in plans:
            self.assertIn(f"plans/{name}", links.DOCUMENTS)

    def test_a_new_docs_page_is_picked_up_by_default(self):
        self.write("docs/other.md", "# Other\n")
        self.write("docs/notes.md", "See [gone](other.md#no-such-heading).\n")

        scanned = links.default_documents(self.root)

        self.assertIn("docs/notes.md", scanned)
        failures = links.check(list(scanned), self.root)
        self.assertTrue(
            any("docs/notes.md" in failure for failure in failures),
            f"a new docs page was not checked: {failures}",
        )

    def test_the_record_in_this_checkout_passes(self):
        # The whole record, including docs/security.md and README: a renamed
        # heading or a moved file fails the suite here rather than in a later
        # read-through.
        self.assertEqual(links.check(list(links.DOCUMENTS), REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
