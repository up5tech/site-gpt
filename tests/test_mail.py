import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from site_gpt.app.services import mail


class BackgroundSendLoggingTests(unittest.TestCase):
    """A scheduled send is nobody's return value, so its failure must be logged.

    `send_email` creates a task when a loop is running; without the done
    callback a failed SMTP send surfaced only as asyncio's garbage-collection
    warning and the email was silently lost.
    """

    def _schedule(self):
        async def scenario():
            mail.send_email(recipient="owner@example.com", subject="Hi", body="Hello")
            for _ in range(3):
                await asyncio.sleep(0)

        return scenario

    def test_a_failed_background_send_is_logged_and_released(self):
        failure = RuntimeError("smtp down")

        with patch.object(mail, "send_email_async", new=AsyncMock(side_effect=failure)):
            with self.assertLogs("site_gpt.app.services.mail", level="ERROR") as logs:
                asyncio.run(self._schedule()())

        self.assertIn("smtp down", "\n".join(logs.output))
        self.assertEqual(mail._pending_tasks, set())

    def test_a_successful_background_send_logs_nothing_and_is_released(self):
        with patch.object(mail, "send_email_async", new=AsyncMock()):
            with self.assertNoLogs("site_gpt.app.services.mail", level="ERROR"):
                asyncio.run(self._schedule()())

        self.assertEqual(mail._pending_tasks, set())


class UnschedulableSendTests(unittest.TestCase):
    """A loop that refuses the task must not leave the coroutine un-awaited.

    `send_email` creates the coroutine before asking the loop for a task. When
    the loop is shutting down `create_task` raises; without this guard the
    coroutine was abandoned (asyncio's "never awaited" warning at shutdown) and
    the RuntimeError was raised into the caller that was already returning.
    """

    def test_a_refused_send_is_closed_and_logged(self):
        created: list = []
        ran: list = []

        async def fake_send(**kwargs):
            ran.append(kwargs)

        def factory(**kwargs):
            coro = fake_send(**kwargs)
            created.append(coro)
            return coro

        async def scenario():
            loop = asyncio.get_running_loop()
            with patch.object(
                loop, "create_task", side_effect=RuntimeError("Event loop is closed")
            ):
                mail.send_email(
                    recipient="owner@example.com", subject="Hi", body="Hello"
                )

        with patch.object(mail, "send_email_async", new=factory):
            with self.assertLogs("site_gpt.app.services.mail", level="ERROR") as logs:
                asyncio.run(scenario())

        text = "\n".join(logs.output)
        self.assertIn("could not be scheduled", text)
        self.assertIn("Event loop is closed", text)
        self.assertNotIn("owner@example.com", text)
        # The coroutine was closed, not run and not left pending.
        self.assertEqual(ran, [])
        self.assertEqual(len(created), 1)
        self.assertIsNone(created[0].cr_frame)
        self.assertEqual(mail._pending_tasks, set())


if __name__ == "__main__":
    unittest.main()
