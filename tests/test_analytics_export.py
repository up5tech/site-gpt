"""Aggregate CSV export tests (V4-11).

The export renders the V4-10 aggregates, so what is worth pinning is the file
itself: the three sections and their exact headers, the filename carrying the
window dates, a question that looks like a spreadsheet formula coming out
neutralized, the absence of the PII surfaces `/api/privacy/export` owns, and the
company scope of a manager from another tenant.

The fixture is placed relative to "now" because the route always exports a
rolling window ending at request time. A real (in-memory SQLite) database is
used for the queries; no provider is called.
"""

import csv
import io
import unittest
from datetime import UTC, datetime, time, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import analytics as analytics_api
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import analytics

NOW = datetime.now(UTC)
START = NOW - timedelta(days=7)
END = NOW
TODAY = NOW.date()

# `normalize_question` lowercases and strips the trailing punctuation, so the
# exported cell is the normalized text — with a leading `'` added by `csv_cell`.
FORMULA_QUESTION = '=HYPERLINK("http://x.test","click")'
FORMULA_CELL = '\'=hyperlink("http://x.test","click'
AT_SUM_QUESTION = "@SUM(A1:A9)"
AT_SUM_CELL = "'@sum(a1:a9"
EMAIL_CANARY = "pii-canary@acme.test"

TREND_HEADER = [
    "date",
    "conversations",
    "messages",
    "visitor_messages",
    "new_contacts",
    "feedback_up",
    "feedback_down",
    "unanswered",
]
FUNNEL_HEADER = ["stage", "sessions"]
QUESTION_HEADER = ["question", "count"]

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Conversation.__table__,
    models.Contact.__table__,
    models.HandoffRequest.__table__,
    models.ChatFeedback.__table__,
    models.Setting.__table__,
]


def _at(days_ago: int, hour: int = 9) -> datetime:
    """A moment inside the rolling window, at a fixed hour that day."""
    return datetime.combine(TODAY - timedelta(days=days_ago), time(hour, tzinfo=UTC))


def _rows(body: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body)))


def _sections(body: str) -> list[list[list[str]]]:
    """The file's non-empty blocks, in order (blank rows separate them)."""
    sections: list[list[list[str]]] = []
    current: list[list[str]] = []
    for row in _rows(body):
        if row:
            current.append(row)
        elif current:
            sections.append(current)
            current = []
    if current:
        sections.append(current)
    return sections


class ExportTestCase(unittest.TestCase):
    def setUp(self):
        # One shared in-memory connection: the route tests go through TestClient,
        # which runs the sync endpoint in a worker thread.
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = self._company("Acme")
        self.other = self._company("Globex")
        self.site_a = self._website(self.company, "site-a")
        self.site_b = self._website(self.company, "site-b")
        self.site_x = self._website(self.other, "site-x")

        # s1 — a question that is a spreadsheet formula, answered.
        self._message(self.site_a, "s1", "user", FORMULA_QUESTION, _at(2, 9))
        self._message(self.site_a, "s1", "assistant", "Click it.", _at(2, 9), True)
        # s2 — an ordinary question the bot could not answer.
        self._message(self.site_a, "s2", "user", "How much does it cost?", _at(2, 10))
        self._message(self.site_a, "s2", "assistant", "No idea.", _at(2, 10), False)
        # s3 — another formula-shaped question, a lead, handed to a human.
        self._message(self.site_b, "s3", "user", AT_SUM_QUESTION, _at(1, 9))
        self._message(self.site_b, "s3", "assistant", "Hm.", _at(1, 9), False)
        self._contact(self.site_b, "s3", _at(1, 9))
        self._handoff(self.site_b, "s3", _at(1, 9))
        self._conversation(self.site_b, "s3", "human", _at(1, 9), _at(1, 9))

        # Globex, same window: only their own session must appear in their file.
        self._message(self.site_x, "sx", "user", "Where is my invoice?", _at(1, 12))
        self._message(self.site_x, "sx", "assistant", "Unknown.", _at(1, 12), False)

        self.user = self._manager(self.company, "manager@acme.test")
        self.other_user = self._manager(self.other, "manager@globex.test")

        app = FastAPI()
        app.include_router(analytics_api.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_manager_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # -- fixtures ---------------------------------------------------------

    def _company(self, name):
        company = models.Company(name=name)
        self.db.add(company)
        self.db.commit()
        return company

    def _website(self, company, name):
        website = models.Website(
            company_id=company.id,
            name=name,
            url=f"https://{name}.test",
            site_map_url="",
            status="active",
        )
        self.db.add(website)
        self.db.commit()
        return website

    def _manager(self, company, email):
        user = models.User(
            company_id=company.id,
            email=email,
            password_hash="x",
            first_name="M",
            last_name="Manager",
            role="manager",
            status="active",
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _message(self, website, session, role, text, at, answered=None):
        row = models.ChatMessage(
            website_id=website.id,
            session_id=session,
            role=role,
            message=text,
            answered=answered,
            created_at=at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _contact(self, website, session, at):
        row = models.Contact(
            website_id=website.id,
            session_id=session,
            first_name="Ada",
            last_name="Lovelace",
            email=EMAIL_CANARY,
            created_at=at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _handoff(self, website, session, at):
        row = models.HandoffRequest(
            website_id=website.id,
            session_id=session,
            status="pending",
            created_at=at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _conversation(self, website, session, state, last_message_at, claimed_at=None):
        row = models.Conversation(
            website_id=website.id,
            session_id=session,
            state=state,
            claimed_at=claimed_at,
            last_message_at=last_message_at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    # -- helpers ----------------------------------------------------------

    def download(self, path="/api/analytics/export.csv", params=None):
        response = self.client.get(path, params=params or {"days": 7})
        self.assertEqual(response.status_code, 200)
        return response


class ExportRouteTests(ExportTestCase):
    def test_the_response_is_a_csv_attachment_named_for_the_window(self):
        response = self.download()

        self.assertTrue(response.headers["content-type"].startswith("text/csv"))
        disposition = response.headers["content-disposition"]
        self.assertTrue(disposition.startswith("attachment; "))
        self.assertRegex(
            disposition,
            r'filename="analytics-\d{4}-\d\d-\d\d_\d{4}-\d\d-\d\d\.csv"$',
        )

    def test_the_file_has_three_sections_with_their_headers(self):
        sections = _sections(self.download().text)
        self.assertEqual(len(sections), 3)
        self.assertEqual(sections[0][0], TREND_HEADER)
        self.assertEqual(sections[1][0], FUNNEL_HEADER)
        self.assertEqual(sections[2][0], QUESTION_HEADER)

    def test_the_trend_section_is_one_row_per_day_and_per_metric(self):
        trend = _sections(self.download().text)[0]
        body = trend[1:]
        # A rolling 7×24h window touches seven whole days plus today's partial
        # one, unless the request lands exactly at midnight.
        self.assertIn(len(body), (7, 8))
        self.assertTrue(all(len(row) == len(TREND_HEADER) for row in body))
        self.assertEqual(
            [row[0] for row in body],
            sorted({row[0] for row in body}),
        )

        by_date = {row[0]: dict(zip(TREND_HEADER, row)) for row in body}
        two_days_ago = by_date[(TODAY - timedelta(days=2)).isoformat()]
        self.assertEqual(two_days_ago["conversations"], "2")
        self.assertEqual(two_days_ago["messages"], "4")
        self.assertEqual(two_days_ago["visitor_messages"], "2")
        self.assertEqual(two_days_ago["unanswered"], "1")

        yesterday = by_date[(TODAY - timedelta(days=1)).isoformat()]
        self.assertEqual(yesterday["conversations"], "1")
        self.assertEqual(yesterday["messages"], "2")
        self.assertEqual(yesterday["new_contacts"], "1")
        self.assertEqual(yesterday["unanswered"], "1")

    def test_the_funnel_section_is_the_five_stages(self):
        funnel = _sections(self.download().text)[1]
        self.assertEqual(
            funnel[1:],
            [
                ["started", "3"],
                ["answered", "3"],
                ["lead", "1"],
                ["handoff", "1"],
                ["human", "1"],
            ],
        )

    def test_the_questions_section_is_the_ranked_top_questions(self):
        questions = _sections(self.download().text)[2]
        self.assertEqual(
            questions[1:],
            [
                [FORMULA_CELL, "1"],
                ["how much does it cost", "1"],
                [AT_SUM_CELL, "1"],
            ],
        )

    def test_a_formula_question_comes_out_neutralized(self):
        body = self.download().text
        cells = [cell for row in _rows(body) for cell in row]

        self.assertIn(FORMULA_CELL, cells)
        # The raw formula never appears as a cell of its own, and no cell can
        # still be executed by a spreadsheet (the `'` prefix is always present).
        self.assertNotIn('=hyperlink("http://x.test","click', cells)
        for cell in cells:
            self.assertFalse(
                cell.startswith(analytics.CSV_FORMULA_PREFIXES),
                f"unneutralized cell: {cell!r}",
            )

    def test_the_file_carries_no_pii(self):
        body = self.download().text
        self.assertNotIn(EMAIL_CANARY, body)
        self.assertNotIn("Ada", body)
        self.assertNotIn("s1", body)
        self.assertNotIn("s3", body)
        for header in _sections(body):
            for name in ("session", "email", "website_id", "message_text"):
                self.assertNotIn(name, header)

    def test_a_manager_of_another_company_only_gets_their_own_data(self):
        self.client.app.dependency_overrides[get_manager_user] = lambda: self.other_user
        try:
            body = self.download().text
        finally:
            self.client.app.dependency_overrides[get_manager_user] = lambda: self.user

        sections = _sections(body)
        self.assertEqual(
            sections[1][1:],
            [
                ["started", "1"],
                ["answered", "1"],
                ["lead", "0"],
                ["handoff", "0"],
                ["human", "0"],
            ],
        )
        self.assertEqual(sections[2][1:], [["where is my invoice", "1"]])
        # Nothing of Acme's leaked into the other tenant's file.
        self.assertNotIn("how much does it cost", body)
        self.assertNotIn(FORMULA_CELL, body)
        self.assertNotIn(EMAIL_CANARY, body)

    def test_a_signed_out_caller_cannot_download_the_file(self):
        app = FastAPI()
        app.include_router(analytics_api.router)
        app.dependency_overrides[get_db] = lambda: self.db
        response = TestClient(app).get("/api/analytics/export.csv")
        self.assertIn(response.status_code, (401, 403))


class ExportHelperTests(ExportTestCase):
    def test_the_filename_spans_the_window(self):
        self.assertEqual(
            analytics.export_filename(
                datetime(2026, 11, 10, 12, tzinfo=UTC),
                datetime(2026, 11, 17, 12, tzinfo=UTC),
            ),
            "analytics-2026-11-10_2026-11-17.csv",
        )

    def test_every_formula_prefix_is_neutralized(self):
        for raw in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
            self.assertEqual(analytics.csv_cell(raw), f"'{raw}")

    def test_ordinary_cells_are_untouched(self):
        self.assertEqual(analytics.csv_cell("how much does it cost"), "how much does it cost")
        self.assertEqual(analytics.csv_cell(7), "7")
        self.assertEqual(analytics.csv_cell(None), "")

    def test_the_export_reuses_the_summary_aggregates(self):
        trend = analytics.daily_trend(self.db, self.company.id, START, END)
        funnel = analytics.engagement_funnel(self.db, self.company.id, START, END)
        questions = analytics.top_questions(
            self.db, self.company.id, START, END
        )

        sections = _sections(
            analytics.export_csv(self.db, self.company.id, START, END)
        )
        self.assertEqual(
            sections[0][1:],
            [[str(point[column]) for column in analytics.TREND_COLUMNS] for point in trend],
        )
        self.assertEqual(
            sections[1][1:],
            [[item["stage"], str(item["sessions"])] for item in funnel],
        )
        self.assertEqual(
            sections[2][1:],
            [[analytics.csv_cell(item["question"]), str(item["count"])] for item in questions],
        )


if __name__ == "__main__":
    unittest.main()
