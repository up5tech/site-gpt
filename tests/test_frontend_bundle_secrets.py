"""V6-1G box 4: the built SPA bundle must not carry a credential.

Where this runs: the plain `unittest` suite
(`uv run python -m unittest discover -s tests`), **after** `cd frontend &&
npm run build`, because it scans the artifact on disk rather than the sources —
only the built bundle proves what a browser actually downloads. Vite inlines
every `VITE_*` value at build time, so a secret-shaped `VITE_` name is a
credential waiting to be published and is failed here too.

A checkout without a build skips with an instruction instead of failing the
suite; the gate run sets `REQUIRE_FRONTEND_BUNDLE=1`, which turns that skip
into a failure so the evidence cannot silently disappear.

A bare server-side setting name is deliberately not a failure on its own:
Settings.tsx legitimately tells the admin that `OPENAI_API_KEY` must be set on
the server. Failure messages name the rule and the file, never the matched
value.
"""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
REQUIRE = os.environ.get("REQUIRE_FRONTEND_BUNDLE") == "1"

# (rule name, pattern, a sample that must match it)
RULES = (
    ("stripe secret key", r"\bsk_(live|test)_[A-Za-z0-9]{8,}", "sk_live_51H8abcDEF"),
    ("stripe restricted key", r"\brk_(live|test)_[A-Za-z0-9]{8,}", "rk_live_abcd1234"),
    ("stripe webhook secret", r"\bwhsec_[A-Za-z0-9]{8,}", "whsec_9fd8a7c1e2"),
    ("sk- style API key", r"\bsk-[A-Za-z0-9_-]{20,}", "sk-proj-abcdefghijklmnopqrstuvwx"),
    ("google API key", r"\bAIza[0-9A-Za-z_-]{30,}", "AIza" + "A" * 33),
    ("slack token", r"xox[baprs]-[A-Za-z0-9-]{10,}", "xoxb-1234567890-abcdefgh"),
    ("github token", r"gh[pousr]_[A-Za-z0-9]{30,}", "ghp_" + "A" * 36),
    ("aws access key", r"\bAKIA[0-9A-Z]{16}", "AKIA" + "ABCDEFGHIJKLMNOP"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "-----BEGIN RSA PRIVATE KEY-----"),
    (
        "credentials in a connection URL",
        r"(postgres(ql)?|mysql|redis|rediss)://[^\s\"'/@]+:[^\s\"'@]+@",
        "postgresql://user:hunter2@db.internal:5432/app",
    ),
    (
        "literal JWT",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlcGFydA",
    ),
    (
        "development JWT fallback",
        r"your-secret-key-change-this-in-production",
        "your-secret-key-change-this-in-production",
    ),
    (
        "secret-shaped VITE_ variable",
        r"VITE_[A-Z0-9_]*(SECRET|TOKEN|PASSWORD|PEPPER|API_KEY)[A-Z0-9_]*",
        "VITE_STRIPE_SECRET_KEY",
    ),
)

_COMPILED = tuple((name, re.compile(pattern)) for name, pattern, _ in RULES)


def find_credentials(text: str) -> list[str]:
    """The rules that match `text` (never the matched values)."""
    return [name for name, pattern in _COMPILED if pattern.search(text)]


def bundle_files() -> list[Path]:
    return sorted(p for p in DIST.rglob("*") if p.is_file())


class FrontendBundleSecretTests(unittest.TestCase):
    def setUp(self):
        if DIST.is_dir():
            return
        message = (
            "frontend/dist is missing: run `cd frontend && npm run build` and "
            "re-run, or set REQUIRE_FRONTEND_BUNDLE=1 to make this a failure "
            "(the gate run does)."
        )
        if REQUIRE:
            self.fail(message)
        self.skipTest(message)

    def test_the_scan_covers_the_entrypoint_and_its_assets(self):
        files = bundle_files()
        self.assertTrue(files, "frontend/dist is empty — rebuild the SPA")
        names = {path.relative_to(DIST).as_posix() for path in files}
        self.assertIn("index.html", names)
        self.assertTrue(
            any(name.startswith("assets/") and name.endswith(".js") for name in names),
            f"no JavaScript asset in frontend/dist: {sorted(names)}",
        )
        total = sum(path.stat().st_size for path in files)
        self.assertGreater(total, 1000, "frontend/dist looks truncated")

    def test_no_credential_is_in_the_built_bundle(self):
        found = []
        for path in bundle_files():
            text = path.read_text(errors="ignore")
            for rule in find_credentials(text):
                found.append((rule, path.relative_to(DIST).as_posix()))
        self.assertEqual(
            found,
            [],
            f"credential-shaped content in the built SPA bundle: {found}",
        )

    def test_the_detector_matches_each_rule(self):
        # A broken pattern must not pass quietly as "nothing found".
        for name, _pattern, sample in RULES:
            with self.subTest(rule=name):
                self.assertIn(name, find_credentials(sample))

    def test_plain_copy_is_not_flagged(self):
        # Settings.tsx names the server-side variable without a value; naming a
        # setting is not a leak, and VITE_ names must not be secret-shaped.
        self.assertEqual(
            find_credentials(
                "so OPENAI_API_KEY must be set on the server; "
                "VITE_BACKEND_URL and VITE_GOOGLE_DRIVE_CLIENT_ID are public"
            ),
            [],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
