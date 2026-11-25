"""V6-16 (D13): no customer-facing copy may claim a second factor or SSO.

D13 deferred tenant MFA/SSO, so the claim "we have MFA" would be a security
statement the login path cannot back, and a login page is where a customer
decides how much an account is worth protecting. This module pins the absence
in code rather than in a note: it scans the SPA's sources, `frontend/index.html`
(its title and meta copy are customer-facing but live outside `src/`) and
`README.md` for the words a claim would be made of, and fails with file/line so
the next author sees the rule.

Deliberately strict — it does not try to tell a negation ("no MFA yet") from a
claim. If a doc or page ever needs to mention the words, that is a copy decision
worth making in the open, not a regex to widen quietly; add the file and an
allowance here in the same change that names the reviewer.
"""

import re
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
FRONTEND_INDEX = REPO_ROOT / "frontend" / "index.html"
README = REPO_ROOT / "README.md"

# File types the SPA actually renders or ships as text. Images and fonts are
# skipped by suffix rather than by sniffing, so a new asset cannot make the
# test read megabytes.
SCANNED_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".less", ".css", ".html", ".json"}

# The vocabulary a second-factor or federation claim is built from. Hyphens and
# spaces are both accepted because both get written.
CLAIM_PATTERNS = (
    re.compile(r"\bMFA\b", re.IGNORECASE),
    re.compile(r"\b2FA\b", re.IGNORECASE),
    re.compile(r"\btwo[\s-]?factor\b", re.IGNORECASE),
    re.compile(r"\bmulti[\s-]?factor\b", re.IGNORECASE),
    re.compile(r"\bSSO\b", re.IGNORECASE),
    re.compile(r"\bSAML\b", re.IGNORECASE),
    re.compile(r"\bsingle[\s-]sign[\s-]on\b", re.IGNORECASE),
)


def _frontend_sources() -> list[Path]:
    if not FRONTEND_SRC.is_dir():  # pragma: no cover - a broken checkout
        return []
    return sorted(
        path
        for path in FRONTEND_SRC.rglob("*")
        if path.is_file() and path.suffix.lower() in SCANNED_SUFFIXES
    )


def _claims_in(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:  # pragma: no cover - not expected under src/
        return []
    try:
        label = str(path.relative_to(REPO_ROOT))
    except ValueError:  # a path outside the checkout, e.g. a fixture in /tmp
        label = str(path)
    hits: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if any(pattern.search(line) for pattern in CLAIM_PATTERNS):
            hits.append(f"{label}:{number}: {line.strip()}")
    return hits


class NoIdentityClaimInCopyTests(unittest.TestCase):
    def test_the_detector_matches_a_claim_and_not_a_plain_sentence(self):
        # Guards the test itself: if the patterns ever stop matching, every
        # scan below passes for the wrong reason. A count of scanned files
        # cannot catch that; a known claim can.
        with tempfile.TemporaryDirectory() as tmp:
            claim = Path(tmp) / "Claim.tsx"
            claim.write_text(
                "export const button = 'Sign in with SSO';\n", encoding="utf-8"
            )
            plain = Path(tmp) / "Plain.tsx"
            plain.write_text(
                "export const button = 'Sign in with your email and password';\n",
                encoding="utf-8",
            )

            self.assertEqual(len(_claims_in(claim)), 1)
            self.assertEqual(_claims_in(plain), [])

    def test_the_spa_makes_no_second_factor_or_federation_claim(self):
        hits: list[str] = []
        for path in [*_frontend_sources(), FRONTEND_INDEX]:
            hits.extend(_claims_in(path))

        self.assertEqual(
            hits,
            [],
            "D13 defers tenant MFA/SSO (see docs/risk-register-v6.md#r13), so no "
            "page may claim a factor or a federated login the login path does "
            "not have:\n" + "\n".join(hits),
        )

    def test_the_readme_makes_no_second_factor_or_federation_claim(self):
        hits = _claims_in(README)

        self.assertEqual(
            hits,
            [],
            "README must not advertise tenant MFA/SSO while D13 defers it "
            "(docs/risk-register-v6.md#r13):\n" + "\n".join(hits),
        )


if __name__ == "__main__":
    unittest.main()
