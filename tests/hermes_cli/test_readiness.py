import argparse
import json

from hermes_cli import readiness


def test_readiness_report_overall_status_counts():
    report = readiness.ReadinessReport(
        checks=[
            readiness.ReadinessCheck("a", "PASS", "ok"),
            readiness.ReadinessCheck("b", "WARN", "attention", "do something"),
        ]
    )

    assert report.overall_status == "ATTENTION"
    assert report.ok_count == 1
    assert report.warn_count == 1
    assert report.fail_count == 0
    rendered = readiness.render_text(report)
    assert "Mutation policy: read-only" in rendered
    assert "[WARN] b: attention" in rendered
    assert "action: do something" in rendered


def test_readiness_report_fail_wins():
    report = readiness.ReadinessReport(
        checks=[
            readiness.ReadinessCheck("a", "WARN", "attention"),
            readiness.ReadinessCheck("b", "FAIL", "broken"),
        ]
    )

    assert report.overall_status == "FAIL"
    assert report.as_dict()["summary"] == {"pass": 0, "warn": 1, "fail": 1}


def test_run_readiness_json_exit_code(monkeypatch, capsys):
    report = readiness.ReadinessReport(
        checks=[readiness.ReadinessCheck("hermes-cli", "PASS", "ok")]
    )
    monkeypatch.setattr(readiness, "collect_readiness", lambda host, port: report)

    rc = readiness.run_readiness(argparse.Namespace(host="127.0.0.1", port=9119, json=True, strict_warnings=False))

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_status"] == "PASS"
    assert payload["checks"][0]["name"] == "hermes-cli"


def test_run_readiness_strict_warnings_exit_code(monkeypatch, capsys):
    report = readiness.ReadinessReport(
        checks=[readiness.ReadinessCheck("dashboard-process", "WARN", "not running")]
    )
    monkeypatch.setattr(readiness, "collect_readiness", lambda host, port: report)

    rc = readiness.run_readiness(argparse.Namespace(host="127.0.0.1", port=9119, json=False, strict_warnings=True))

    assert rc == 2
    assert "Hermes readiness: ATTENTION" in capsys.readouterr().out


def test_run_readiness_failure_exit_code(monkeypatch, capsys):
    report = readiness.ReadinessReport(
        checks=[readiness.ReadinessCheck("gateway-service", "FAIL", "not running")]
    )
    monkeypatch.setattr(readiness, "collect_readiness", lambda host, port: report)

    rc = readiness.run_readiness(argparse.Namespace(host="127.0.0.1", port=9119, json=False, strict_warnings=False))

    assert rc == 1
    assert "[FAIL] gateway-service: not running" in capsys.readouterr().out
