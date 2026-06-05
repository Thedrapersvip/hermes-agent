"""Non-mutating readiness checks for Hermes dashboard/cockpit operations.

This module backs ``hermes readiness``: a fast operator-facing command that
answers "is this Atlas/Hermes surface safe and ready to use?" without starting,
stopping, restarting, reloading, or otherwise mutating the live gateway.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    message: str
    action: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessReport:
    checks: list[ReadinessCheck] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "PASS")

    @property
    def warn_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "WARN")

    @property
    def fail_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "FAIL")

    @property
    def overall_status(self) -> str:
        if self.fail_count:
            return "FAIL"
        if self.warn_count:
            return "ATTENTION"
        return "PASS"

    def as_dict(self) -> dict[str, object]:
        return {
            "overall_status": self.overall_status,
            "summary": {
                "pass": self.ok_count,
                "warn": self.warn_count,
                "fail": self.fail_count,
            },
            "checks": [check.as_dict() for check in self.checks],
        }


def _check(name: str, status: str, message: str, action: str | None = None) -> ReadinessCheck:
    return ReadinessCheck(name=name, status=status, message=message, action=action)


def _is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _http_status(url: str, timeout: float = 2.0) -> tuple[int | None, str | None]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "hermes-readiness/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator localhost probe
            return int(response.status), None
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc)
    except Exception as exc:  # network probes should be best-effort, not crash readiness
        return None, str(exc)


def _format_gateway_pids(pids: Iterable[int]) -> str:
    values = [str(pid) for pid in pids if pid]
    return ", ".join(values) if values else "none"


def collect_readiness(*, host: str = "127.0.0.1", port: int = 9119) -> ReadinessReport:
    """Collect dashboard/cockpit readiness without mutating live state.

    The checks intentionally avoid ``gateway start/stop/restart``, dashboard
    launch/stop, launchctl kickstart/bootstrap/bootout, and any config writes.
    Restart-required conditions are reported as WARN/FAIL actions only.
    """

    checks: list[ReadinessCheck] = []

    # Core CLI import/runtime.
    try:
        from hermes_cli import __release_date__, __version__
        from hermes_cli.config import get_hermes_home, load_config

        hermes_home = Path(get_hermes_home()).expanduser()
        checks.append(
            _check(
                "hermes-cli",
                "PASS",
                f"Hermes Agent v{__version__} ({__release_date__}); home {hermes_home}",
            )
        )
        try:
            load_config()
            checks.append(_check("config", "PASS", "config.yaml loaded successfully"))
        except Exception as exc:
            checks.append(
                _check(
                    "config",
                    "FAIL",
                    f"config.yaml could not be loaded: {exc}",
                    "Run `hermes config check` or `hermes doctor`; do not restart the gateway until config is valid.",
                )
            )
    except Exception as exc:
        checks.append(
            _check(
                "hermes-cli",
                "FAIL",
                f"Hermes CLI import failed: {exc}",
                "Repair the install before launching dashboard/cockpit surfaces.",
            )
        )

    # Dashboard prerequisites and current availability.
    if _is_loopback_host(host):
        checks.append(_check("dashboard-bind", "PASS", f"dashboard target is loopback-only ({host}:{port})"))
    else:
        checks.append(
            _check(
                "dashboard-bind",
                "WARN",
                f"dashboard target is non-loopback ({host}:{port})",
                "Use `--host 127.0.0.1` unless this is an explicitly approved secure remote bind.",
            )
        )

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401

        checks.append(_check("dashboard-deps", "PASS", "FastAPI and Uvicorn are importable"))
    except Exception as exc:
        checks.append(
            _check(
                "dashboard-deps",
                "FAIL",
                f"dashboard server dependencies are missing: {exc}",
                "Install/repair the Hermes environment before launching `hermes dashboard`.",
            )
        )

    dist_index = Path(os.environ.get("HERMES_WEB_DIST", "")) / "index.html" if os.environ.get("HERMES_WEB_DIST") else Path(__file__).resolve().parent / "web_dist" / "index.html"
    if dist_index.exists():
        checks.append(_check("dashboard-assets", "PASS", f"web dist exists at {dist_index}"))
    else:
        checks.append(
            _check(
                "dashboard-assets",
                "WARN",
                f"web dist not found at {dist_index}",
                "Run `hermes dashboard` without --skip-build or build the web UI before using --skip-build.",
            )
        )

    try:
        from hermes_cli.main import _find_stale_dashboard_pids

        dashboard_pids = _find_stale_dashboard_pids()
    except Exception:
        dashboard_pids = []
    if dashboard_pids:
        checks.append(_check("dashboard-process", "PASS", f"dashboard process running: PID(s) {_format_gateway_pids(dashboard_pids)}"))
    else:
        checks.append(
            _check(
                "dashboard-process",
                "WARN",
                "no dashboard process is currently running",
                f"Start when needed with `hermes dashboard --host {host} --port {port} --no-open`; this readiness command did not start it.",
            )
        )

    if _tcp_reachable(host, port):
        status, error = _http_status(f"http://{host}:{port}/")
        if status and 200 <= status < 500:
            checks.append(_check("dashboard-http", "PASS", f"http://{host}:{port}/ responded with HTTP {status}"))
        else:
            checks.append(
                _check(
                    "dashboard-http",
                    "WARN",
                    f"TCP {host}:{port} is open but HTTP probe failed: {error or status}",
                    "Check the dashboard process logs; do not restart the gateway for a dashboard-only issue.",
                )
            )
    else:
        checks.append(
            _check(
                "dashboard-http",
                "WARN",
                f"nothing is listening on {host}:{port}",
                "Dashboard is unavailable until explicitly started; no live gateway action was taken.",
            )
        )

    # Live gateway/service state: read-only snapshot only.
    try:
        from hermes_cli.gateway import get_gateway_runtime_snapshot, _runtime_health_lines

        snapshot = get_gateway_runtime_snapshot()
        if snapshot.running:
            checks.append(
                _check(
                    "gateway-service",
                    "PASS",
                    f"gateway running via {snapshot.manager}; service_running={snapshot.service_running}; pid(s) {_format_gateway_pids(snapshot.gateway_pids)}",
                )
            )
        elif snapshot.service_installed:
            checks.append(
                _check(
                    "gateway-service",
                    "FAIL",
                    f"gateway service is installed under {snapshot.manager} but not running",
                    "Gateway restart/start is required but was NOT applied by readiness. Run `hermes gateway status` then start/restart only after approval.",
                )
            )
        else:
            checks.append(
                _check(
                    "gateway-service",
                    "WARN",
                    f"no running gateway detected under {snapshot.manager}",
                    "If messaging, webhooks, or cron are expected, install/start the gateway after approval.",
                )
            )
        if snapshot.has_process_service_mismatch:
            checks.append(
                _check(
                    "gateway-process-mismatch",
                    "WARN",
                    "gateway process exists but the service manager does not report it active",
                    "Investigate manual/tmux/nohup gateway process before any restart; readiness did not kill it.",
                )
            )
        runtime_lines = _runtime_health_lines()
        if runtime_lines:
            checks.append(
                _check(
                    "gateway-runtime",
                    "WARN",
                    "; ".join(runtime_lines),
                    "Inspect `hermes gateway status` and logs; restart-required conditions are reported only, not applied.",
                )
            )
        else:
            checks.append(_check("gateway-runtime", "PASS", "no fatal persisted gateway runtime warnings found"))
    except Exception as exc:
        checks.append(
            _check(
                "gateway-service",
                "WARN",
                f"gateway status could not be inspected: {exc}",
                "Run `hermes gateway status`; readiness did not mutate service state.",
            )
        )

    # Automation/watchdog surface: cron DB/job inspection is read-only.
    try:
        from cron.jobs import list_jobs

        jobs = list_jobs(include_disabled=False)
        active_count = len(jobs) if isinstance(jobs, list) else 0
        no_agent_count = sum(1 for job in jobs if isinstance(job, dict) and job.get("no_agent")) if isinstance(jobs, list) else 0
        if active_count:
            checks.append(_check("cron-watchdogs", "PASS", f"{active_count} active cron job(s); {no_agent_count} script-only watchdog(s)"))
        else:
            checks.append(
                _check(
                    "cron-watchdogs",
                    "WARN",
                    "no active cron jobs/watchdogs found for this profile",
                    "If watchdog alerts are expected, review `hermes cron list` without changing gateway state.",
                )
            )
    except Exception as exc:
        checks.append(
            _check(
                "cron-watchdogs",
                "WARN",
                f"cron jobs could not be inspected: {exc}",
                "Run `hermes cron list`; readiness did not mutate jobs.",
            )
        )

    # Cockpit prerequisites: best-effort local checks for Dave's Herdr/Atlas cockpit.
    herdr_bin = Path.home() / ".local" / "bin" / "herdr"
    cockpit_dir = Path.home() / "Developer" / "atlas-herdr-cockpit"
    if herdr_bin.exists() and os.access(herdr_bin, os.X_OK):
        checks.append(_check("cockpit-herdr", "PASS", f"Herdr binary is executable at {herdr_bin}"))
    elif herdr_bin.exists():
        checks.append(
            _check(
                "cockpit-herdr",
                "WARN",
                f"Herdr binary exists but is not executable: {herdr_bin}",
                "Fix permissions before relying on cockpit commands.",
            )
        )
    else:
        checks.append(
            _check(
                "cockpit-herdr",
                "WARN",
                f"Herdr binary not found at {herdr_bin}",
                "Install/verify Herdr only if terminal cockpit use is expected.",
            )
        )
    if cockpit_dir.exists():
        checks.append(_check("cockpit-workspace", "PASS", f"Atlas cockpit workspace exists at {cockpit_dir}"))
    else:
        checks.append(
            _check(
                "cockpit-workspace",
                "WARN",
                f"Atlas cockpit workspace not found at {cockpit_dir}",
                "Create/restore the cockpit workspace only if Herdr cockpit use is expected.",
            )
        )

    return ReadinessReport(checks=checks)


def render_text(report: ReadinessReport) -> str:
    lines = [
        f"Hermes readiness: {report.overall_status} ({report.ok_count} pass, {report.warn_count} warn, {report.fail_count} fail)",
        "Mutation policy: read-only; no gateway/dashboard start, stop, restart, reload, or config write was performed.",
        "",
    ]
    for check in report.checks:
        lines.append(f"[{check.status}] {check.name}: {check.message}")
        if check.action:
            lines.append(f"       action: {check.action}")
    return "\n".join(lines)


def run_readiness(args) -> int:
    report = collect_readiness(host=getattr(args, "host", "127.0.0.1"), port=getattr(args, "port", 9119))
    if getattr(args, "json", False):
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(render_text(report))
    if report.fail_count:
        return 1
    if report.warn_count and getattr(args, "strict_warnings", False):
        return 2
    return 0


__all__ = [
    "ReadinessCheck",
    "ReadinessReport",
    "collect_readiness",
    "render_text",
    "run_readiness",
]
