"""V6-31 prep: the doc link checker, and the fact that it covers security.md.

What is pinned here:

* a relative link is resolved from the linking document's own directory, so a
  moved target and a renamed heading both fail with the offending link;
* a fragment resolves against headings and explicit `<a name="…">` anchors, and
  a slug used twice is reported instead of silently landing on the first;
* the GitHub slug keeps the double hyphen an em dash surrounded by spaces
  produces, which is what the V6 appendix anchors rely on;
* `docs/security.md` and `README.md` are checked documents — both because they
  are in `DOCUMENTS` and because a broken link in a copy of one is caught — so
  their links are no longer verified by eye;
* the two documents that carry no relative link of their own (`docs/billing.md`,
  `docs/platform.md`) stay out of `DOCUMENTS` only while that is true: adding a
  link to one fails this module until it is scanned too;
* the record in this checkout passes, so the suite fails when a heading or a
  file is renamed without the links being updated.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

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

    def test_documents_without_relative_links_need_no_scanning(self):
        # Why they are not in DOCUMENTS: nothing to resolve. The day one gains a
        # link this fails, so the reason cannot quietly go stale.
        for name in ("docs/billing.md", "docs/platform.md"):
            path = REPO_ROOT / name
            self.assertTrue(path.is_file(), f"{name} is missing")
            text = path.read_text(encoding="utf-8")
            found = [
                link for link in links.LINK.findall(text) if links.relative_target(link)
            ]
            self.assertEqual(
                found,
                [],
                f"{name} now carries {found}; add it to DOCUMENTS and scan it",
            )

    def test_the_record_in_this_checkout_passes(self):
        # The whole record, including docs/security.md and README: a renamed
        # heading or a moved file fails the suite here rather than in a later
        # read-through.
        self.assertEqual(links.check(list(links.DOCUMENTS), REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
