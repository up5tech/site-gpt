"""The gate record and `scripts/gate_v3_4g/` must list the same steps.

Pure text checks on purpose — no database, no Redis, no import of the app — so
they run in the normal suite. `PLAN_V3.md`'s gate and the scripts README drifted
twice (a step added to one and not the other); this fails the moment it happens
again.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "PLAN_V3.md"
GATE_DIR = ROOT / "scripts" / "gate_v3_4g"
README = GATE_DIR / "README.md"
RUN_ALL = GATE_DIR / "run_all.sh"

# `00_migrations.sh`, `01_db_checks.py`, … — a step, not the helper or the runner.
STEP_PATTERN = re.compile(r"\b(0\d_[a-z0-9_]+\.(?:py|sh))\b")


def gate_section() -> str:
    """The text of the `#### Gate V3-4G` section, up to the next heading."""
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("#### Gate V3-4G")
    rest = text[start + len("#### Gate V3-4G") :]
    end = re.search(r"\n#{2,4} ", rest)
    return rest[: end.start()] if end else rest


def plan_steps() -> set[str]:
    return set(STEP_PATTERN.findall(gate_section()))


def directory_steps() -> set[str]:
    return {
        path.name
        for path in GATE_DIR.iterdir()
        if path.is_file() and STEP_PATTERN.fullmatch(path.name)
    }


def readme_steps() -> set[str]:
    return set(STEP_PATTERN.findall(README.read_text(encoding="utf-8")))


class GateScriptInventoryTests(unittest.TestCase):
    def test_directory_has_steps(self):
        names = sorted(path.name for path in GATE_DIR.iterdir() if path.is_file())
        self.assertIn("run_all.sh", names)
        self.assertGreaterEqual(len([n for n in names if STEP_PATTERN.fullmatch(n)]), 1)

    def test_plan_and_directory_list_the_same_steps(self):
        self.assertEqual(
            plan_steps(),
            directory_steps(),
            "PLAN_V3.md's Gate V3-4G and scripts/gate_v3_4g/ disagree: "
            f"only in the plan {sorted(plan_steps() - directory_steps())}, "
            f"only in the directory {sorted(directory_steps() - plan_steps())}",
        )

    def test_readme_lists_the_same_steps(self):
        self.assertEqual(
            readme_steps(),
            directory_steps(),
            "scripts/gate_v3_4g/README.md and the directory disagree: "
            f"only in the README {sorted(readme_steps() - directory_steps())}, "
            f"only in the directory {sorted(directory_steps() - readme_steps())}",
        )

    def test_run_all_invokes_every_step(self):
        runner = RUN_ALL.read_text(encoding="utf-8")
        missing = sorted(step for step in directory_steps() if step not in runner)
        self.assertEqual(missing, [], f"run_all.sh never runs {missing}")


V5_GATE = ROOT / "scripts" / "gate_v5_5g"
V5_PLAN = ROOT / "plans" / "PLAN_V5.md"


class V5GateScriptTests(unittest.TestCase):
    """The V5 gate must never be able to target a real database."""

    def test_the_gate_refuses_a_non_gate_database_name(self):
        source = (V5_GATE / "gate.py").read_text(encoding="utf-8")

        self.assertIn('name.startswith("v5_gate_5g")', source)
        self.assertIn("refusing a database name", source)

    def test_the_gate_documents_its_blocked_externals(self):
        readme = (V5_GATE / "README.md").read_text(encoding="utf-8")

        self.assertIn("Blocked, not skipped", readme)
        self.assertIn("Live Stripe test-mode", readme)
        self.assertIn("Browser journey", readme)

    def test_the_plan_names_the_runnable_gate(self):
        plan = V5_PLAN.read_text(encoding="utf-8")

        self.assertIn("scripts/gate_v5_5g/run_all.sh", plan)
        self.assertIn("72/72", plan)


if __name__ == "__main__":
    unittest.main()
