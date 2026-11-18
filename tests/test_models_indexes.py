"""Schema tests for `embed_tokens` (V3 M7, F4).

Two guarantees are not expressible in a dataclass and are the whole point of the
table: one *active* token per website, and a hash that is unique table-wide. Both
are database constraints, and the first one is a **partial** unique index, which
is easy to get subtly wrong (a plain unique index on `website_id` would block the
revoked history that rotation depends on). So these tests pin the model
declaration, the compiled PostgreSQL DDL, and the migration that ships it —
including that the revision is still the single head chained from `c9d3e5a71b28`.
"""

import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from site_gpt.app import models

ROOT = Path(__file__).resolve().parent.parent
M7_REVISION = "76f46b510350"
M7_PATH = ROOT / "alembic" / "versions" / f"{M7_REVISION}_v3_m7_embed_tokens.py"
M7_PARENT = "c9d3e5a71b28"
ACTIVE_INDEX = "uq_embed_tokens_website_id_active"


def _index(name: str):
    return next(
        (item for item in models.EmbedToken.__table__.indexes if item.name == name),
        None,
    )


class EmbedTokenModelTests(unittest.TestCase):
    def test_table_and_columns(self):
        table = models.EmbedToken.__table__

        self.assertEqual(table.name, "embed_tokens")
        self.assertEqual(table.columns["token_prefix"].type.length, 12)
        self.assertEqual(table.columns["token_hash"].type.length, 64)

    def test_website_fk_cascades(self):
        # Deleting a website must not leave tokens that could still be presented.
        column = models.EmbedToken.__table__.columns["website_id"]
        foreign_key = next(iter(column.foreign_keys))

        self.assertEqual(foreign_key.column.table.name, "websites")
        self.assertEqual(foreign_key.ondelete, "CASCADE")
        self.assertFalse(column.nullable)

    def test_hash_is_unique(self):
        uniques = {
            tuple(sorted(column.name for column in constraint.columns))
            for constraint in models.EmbedToken.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }

        self.assertIn(("token_hash",), uniques)

    def test_only_active_tokens_are_unique_per_website(self):
        # Revoked rows must be allowed to coexist, so this has to be partial.
        index = _index(ACTIVE_INDEX)

        self.assertIsNotNone(index, f"EmbedToken must declare {ACTIVE_INDEX}")
        self.assertTrue(index.unique)
        self.assertEqual([column.name for column in index.columns], ["website_id"])
        self.assertEqual(
            str(index.dialect_options["postgresql"]["where"]),
            "revoked_at IS NULL",
        )
        # The test suite runs on SQLite; the same predicate there keeps
        # `test_embed_tokens` able to prove that rotation may keep revoked rows.
        self.assertEqual(
            str(index.dialect_options["sqlite"]["where"]),
            "revoked_at IS NULL",
        )

    def test_compiled_ddl_is_a_partial_unique_index(self):
        ddl = str(
            CreateIndex(_index(ACTIVE_INDEX)).compile(dialect=postgresql.dialect())
        )

        self.assertIn("CREATE UNIQUE INDEX", ddl)
        self.assertIn("WHERE revoked_at IS NULL", ddl)

    def test_revoked_and_last_used_are_timezone_aware(self):
        # SessionToken set the precedent; naive columns here would make
        # `last_used_at` throttling compare a naive value with an aware one.
        for name in ("revoked_at", "last_used_at"):
            column = models.EmbedToken.__table__.columns[name]
            self.assertTrue(column.nullable)
            self.assertTrue(column.type.timezone, f"{name} must be timezone-aware")

    def test_website_owns_its_tokens(self):
        relationship = models.Website.__mapper__.relationships["embed_tokens"]

        self.assertEqual(relationship.mapper.class_.__name__, "EmbedToken")
        self.assertTrue(relationship.passive_deletes)


class EmbedTokenMigrationTests(unittest.TestCase):
    def setUp(self):
        self.source = M7_PATH.read_text(encoding="utf-8")

    def test_migration_exists_and_chains_from_the_v2_head(self):
        self.assertTrue(M7_PATH.exists(), f"missing migration {M7_PATH.name}")
        self.assertIn(
            "down_revision: Union[str, Sequence[str], None] = 'c9d3e5a71b28'",
            self.source,
        )

    def test_migration_creates_the_same_table(self):
        for column in (
            "website_id",
            "token_prefix",
            "token_hash",
            "revoked_at",
            "last_used_at",
        ):
            self.assertIn(f"'{column}'", self.source)
        self.assertIn("sa.UniqueConstraint('token_hash')", self.source)
        self.assertIn("ondelete='CASCADE'", self.source)

    def test_migration_creates_the_partial_unique_index(self):
        self.assertIn(ACTIVE_INDEX, self.source)
        self.assertIn("unique=True", self.source)
        self.assertIn("postgresql_where=sa.text('revoked_at IS NULL')", self.source)

    def test_new_table_indexes_are_built_transactionally(self):
        # `embed_tokens` has no traffic yet, so the CONCURRENTLY dance (and its
        # non-atomic risk) is neither needed nor wanted.
        self.assertNotIn("autocommit_block()", self.source)
        self.assertNotIn("postgresql_concurrently=True", self.source)

    def test_downgrade_removes_table_and_index(self):
        downgrade = self.source.split("def downgrade()", 1)[1]

        self.assertIn("drop_index", downgrade)
        self.assertIn(ACTIVE_INDEX, downgrade)
        self.assertIn("drop_table('embed_tokens')", downgrade)

    def test_revision_is_the_single_head(self):
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)

        self.assertEqual(script.get_heads(), [M7_REVISION])
        self.assertEqual(script.get_revision(M7_REVISION).down_revision, M7_PARENT)


if __name__ == "__main__":
    unittest.main()
