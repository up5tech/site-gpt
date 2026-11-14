import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "widget_snippet.test.mjs"


class WidgetSnippetTests(unittest.TestCase):
    """The Settings page install snippet must always carry a ?v= token."""

    def test_snippet_never_drops_the_version_query(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; cannot execute the snippet harness")

        result = subprocess.run(
            [node, str(HARNESS)],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=60,
        )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
