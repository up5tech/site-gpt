"""V6-23: explicit database pool sizing and the deployment's connection ceiling.

What is pinned here:

* a networked database (Postgres) gets the configured pool, its overflow, the
  wait timeout and the recycle age, plus a pre-ping so a connection killed by a
  proxy or failover is replaced instead of failing the request that got it;
* SQLite keeps its default pool, so tests and local runs are unchanged;
* the ceiling helper multiplies one process's worst case by the process count,
  which is the number an operator compares with the database's `max_connections`.
"""

import unittest

from site_gpt.app.core import config
from site_gpt.app.db import session


class EngineOptionsTests(unittest.TestCase):
    def test_a_networked_database_gets_the_configured_pool(self):
        options = session.engine_options(
            "postgresql+psycopg://user:pw@db:5432/site",
            pool_size=7,
            max_overflow=3,
            pool_timeout=12,
            pool_recycle=900,
        )

        self.assertEqual(options["pool_size"], 7)
        self.assertEqual(options["max_overflow"], 3)
        self.assertEqual(options["pool_timeout"], 12)
        self.assertEqual(options["pool_recycle"], 900)
        self.assertTrue(options["pool_pre_ping"])
        self.assertEqual(options["echo"], config.SQL_ECHO)

    def test_sqlite_keeps_its_default_pool(self):
        # The suite's in-memory databases share one connection; sizing them would
        # change test behaviour without protecting anything server-side.
        for url in ("sqlite://", "sqlite+pysqlite:///:memory:"):
            with self.subTest(url=url):
                options = session.engine_options(url, pool_size=99)

                self.assertNotIn("pool_size", options)
                self.assertNotIn("pool_pre_ping", options)
                self.assertEqual(options, {"echo": config.SQL_ECHO})

    def test_the_defaults_come_from_configuration(self):
        options = session.engine_options("postgresql://db/site")

        self.assertEqual(options["pool_size"], config.DB_POOL_SIZE)
        self.assertEqual(options["max_overflow"], config.DB_MAX_OVERFLOW)
        self.assertEqual(options["pool_timeout"], config.DB_POOL_TIMEOUT_SECONDS)
        self.assertEqual(options["pool_recycle"], config.DB_POOL_RECYCLE_SECONDS)

    def test_a_pool_can_never_be_asked_for_a_negative_wait(self):
        # The values are passed through untouched; bounding them is the
        # deployment's job (SQLAlchemy rejects what it cannot build).
        options = session.engine_options("postgresql://db/site", pool_timeout=0)

        self.assertEqual(options["pool_timeout"], 0)


class PoolCeilingTests(unittest.TestCase):
    def test_one_process_holds_its_pool_plus_overflow(self):
        self.assertEqual(session.pool_ceiling(1, pool_size=5, max_overflow=5), 10)

    def test_the_deployment_multiplies_by_processes(self):
        # Two API replicas and one worker at the defaults: the number to compare
        # with the database's max_connections.
        self.assertEqual(session.pool_ceiling(3), 3 * (config.DB_POOL_SIZE + config.DB_MAX_OVERFLOW))

    def test_no_process_opens_nothing(self):
        self.assertEqual(session.pool_ceiling(0), 0)

    def test_a_negative_process_count_is_refused(self):
        with self.assertRaises(ValueError):
            session.pool_ceiling(-1)


class EngineWiringTests(unittest.TestCase):
    def test_the_module_engine_was_built_with_its_options(self):
        # Guards against configuring a pool and forgetting to pass it to the
        # engine the whole app actually uses.
        url = str(session.engine.url)
        if url.startswith("sqlite"):
            self.assertFalse(session.engine.pool._pre_ping)
        else:
            self.assertEqual(session.engine.pool.size(), config.DB_POOL_SIZE)
            self.assertEqual(
                session.engine.pool._max_overflow, config.DB_MAX_OVERFLOW
            )


if __name__ == "__main__":
    unittest.main()
