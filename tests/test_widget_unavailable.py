import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "widget_unavailable.test.mjs"


class WidgetUnavailableTests(unittest.TestCase):
    """A disabled website must show a clear notice, not the 'Error!' bubble."""

    def test_disabled_site_shows_the_unavailable_notice(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; cannot execute the widget harness")

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
