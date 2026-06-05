"""Shared gateway restart constants, guardrails, and parsing helpers."""

import os

from hermes_cli.config import DEFAULT_CONFIG

# EX_TEMPFAIL from sysexits.h — used to ask the service manager to restart
# the gateway after a graceful drain/reload path completes.
GATEWAY_SERVICE_RESTART_EXIT_CODE = 75

GATEWAY_RESTART_APPROVAL_ENV = "HERMES_GATEWAY_RESTART_APPROVED"
GATEWAY_RESTART_APPROVAL_VALUES = {"1", "true", "yes", "approved", "dave-approved"}
GATEWAY_RESTART_GUARD_MARKER = "restart-required-but-not-applied"

DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT = float(
    DEFAULT_CONFIG["agent"]["restart_drain_timeout"]
)


def parse_restart_drain_timeout(raw: object) -> float:
    """Parse a configured drain timeout, falling back to the shared default."""
    try:
        value = float(raw) if str(raw or "").strip() else DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT
    except (TypeError, ValueError):
        return DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT
    return max(0.0, value)


def gateway_restart_approved(*, approved: bool = False, env: dict[str, str] | None = None) -> bool:
    """Return True only when a gateway restart has explicit operator approval."""
    if approved:
        return True
    source = os.environ if env is None else env
    raw = str(source.get(GATEWAY_RESTART_APPROVAL_ENV, "")).strip().lower()
    return raw in GATEWAY_RESTART_APPROVAL_VALUES


def gateway_restart_guard_message(*, action: str = "gateway restart", approval_hint: str = "re-run with --approved") -> str:
    """Operator-facing dry-run message for restart/reload actions that were not applied."""
    return (
        f"{GATEWAY_RESTART_GUARD_MARKER}: {action} requires explicit Dave approval "
        f"before applying. No gateway restart/reload was performed. After approval, {approval_hint}."
    )
