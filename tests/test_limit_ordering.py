"""V3-12: limiter / quota / API-key composition, pinned as actual behaviour.

Ordering (verified against the route definitions, not assumed):

- Public widget chat: the per-IP limiter is a FastAPI dependency, so it
  runs *before* the handler body — which is where the per-session cap
  (`consume_session_message`, V4-20) and then the daily quota
  (`consume_message`) are checked. The limiter is the burst guard, the
  session cap bounds one visitor, and the quota is the spend ceiling.
- `/api/v1`: API-key authentication (`get_api_key`) is the only gate
  before the handler; there is deliberately no per-IP or per-key rate
  limiter on `/api/v1` (per-key limiting is deferred — see PLAN_V3
  V3-12). The daily quota still applies inside the v1 chat handler.
"""

import inspect
import unittest

from site_gpt.app.api import routes as widget_routes
from site_gpt.app.api import v1 as v1_routes
from site_gpt.app.services.ratelimit import RATE_LIMIT_POLICIES


def _find_route(router, method, path):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in (
            getattr(route, "methods", None) or set()
        ):
            return route
    raise AssertionError(f"route {method} {path} not found")


def _has_limiter_dependency(route) -> bool:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    return any(
        getattr(dep.call, "__name__", "") == "dependency"
        for dep in dependant.dependencies
    )


class LimitOrderingTests(unittest.TestCase):
    def test_widget_chat_limiter_runs_before_handler_quota(self):
        route = _find_route(widget_routes.router, "POST", "/api/chat")
        # Limiter is a dependency (runs first); quota is inside the handler.
        self.assertTrue(_has_limiter_dependency(route))
        self.assertIn("consume_message", inspect.getsource(route.endpoint))

    def test_v1_routes_have_no_ip_rate_limiter(self):
        # Pins the deferred decision: /api/v1 is key-authenticated only.
        for route in v1_routes.router.routes:
            self.assertFalse(
                _has_limiter_dependency(route),
                f"{getattr(route, 'path', route)} must not gain an IP limiter "
                "without updating this test and the V3-12 docs",
            )

    def test_v1_chat_still_enforces_daily_quota_and_key_auth(self):
        route = _find_route(v1_routes.router, "POST", "/chat")
        self.assertIn("consume_message", inspect.getsource(route.endpoint))
        dependant = getattr(route, "dependant", None)
        calls = [getattr(dep.call, "__name__", "") for dep in dependant.dependencies]
        self.assertIn("get_api_key", calls)

    def test_v1_policy_row_is_reserved_not_wired(self):
        self.assertIn("v1", RATE_LIMIT_POLICIES)  # reserved for a follow-up

    def test_session_cap_runs_before_the_daily_quota_in_every_chat_handler(self):
        # V4-20 extends this file rather than duplicating it: every handler that
        # spends the daily budget must check the session cap first.
        for router, path in (
            (widget_routes.router, "/api/chat"),
            (widget_routes.router, "/api/chat/stream"),
            (v1_routes.router, "/chat"),
        ):
            source = inspect.getsource(
                _find_route(router, "POST", path).endpoint
            )
            self.assertIn("consume_session_message", source, path)
            self.assertLess(
                source.index("consume_session_message"),
                source.index("consume_message"),
                f"{path} must check the session cap before the daily quota",
            )


if __name__ == "__main__":
    unittest.main()
