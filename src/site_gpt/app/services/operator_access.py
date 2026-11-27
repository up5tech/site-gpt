"""The operator console's network boundary (V6-11, D5 reopened 2026-11-27).

D5's approved control for the platform console is an operator network allowlist
(`OPERATOR_ALLOWED_NETWORKS`), enforced on every `/api/platform` request rather
than at one ingress hostname. That is what makes the boundary independent of
`Host`, `X-Forwarded-Host`, `Origin` or an alternate API origin: the check reads
the client address through `ratelimit.operator_client_ip`, which honours
`X-Forwarded-For` only when the direct peer is listed in `TRUSTED_PROXY_IPS`.
The limiter's wider rule — loopback and private peers may also forward — is
deliberately not reused here, because a process sharing that network could
otherwise claim a listed operator address with one header.

An empty allowlist means "not restricted" — a development posture that
`core.config.production_config_errors` refuses to combine with the console
switch in production. A request whose address cannot be resolved is refused.

This module deliberately holds no state and no secret: it answers one question,
so the dependency in `core.auth.require_platform_owner` stays a single line.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from site_gpt.app.core import config
from site_gpt.app.services.ratelimit import operator_client_ip


def is_allowed(request: Request, networks: Any = None) -> bool:
    """Whether this request's client address may reach the operator console."""
    return config.operator_network_allows(operator_client_ip(request), networks)
