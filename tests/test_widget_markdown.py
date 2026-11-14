import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "widget_sanitize.test.mjs"


class WidgetMarkdownTests(unittest.TestCase):
    """Runs the shipped widget markdown renderer against XSS payloads.

    The renderer lives in the plain browser script `widget.js`, so the actual
    assertions are in a small node harness; this test wires it into the Python
    suite so `unittest discover` fails if sanitising regresses.
    """

    def test_malicious_payloads_are_neutralised(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; cannot execute widget.js helpers")

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
