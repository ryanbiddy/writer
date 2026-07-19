from __future__ import annotations

import json

from writer import doctor


ABSENT_PEER = {
    "ok": True,
    "contract": "ryan.suite.peer",
    "version": 1,
    "peer": "uoink",
    "state": "absent",
    "capabilities": [],
}


def test_doctor_json_reports_required_and_optional_truth(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path / "writer-data"))
    monkeypatch.delenv("WRITER_UOINK_TOKEN", raising=False)
    monkeypatch.setattr(
        doctor, "probe_uoink", lambda **kwargs: ABSENT_PEER)

    assert doctor.run(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    checks = {check["name"]: check for check in payload["checks"]}

    assert payload["ok"] is True
    assert checks["database"]["required"] is True
    assert checks["database"]["status"] == "ready"
    assert checks["packaged_data"]["status"] == "ready"
    assert checks["uoink"]["required"] is False
    assert checks["uoink"]["status"] == "absent"
    assert checks["uoink"]["result"] == ABSENT_PEER
    assert payload["summary"]["required_ready"] == 2
    assert payload["summary"]["required_total"] == 2


def test_doctor_human_output_leads_with_verdict(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WRITER_DATA_DIR", str(tmp_path / "writer-data"))
    monkeypatch.delenv("WRITER_UOINK_TOKEN", raising=False)
    monkeypatch.setattr(
        doctor, "probe_uoink", lambda **kwargs: ABSENT_PEER)

    assert doctor.run([]) == 0
    lines = capsys.readouterr().out.splitlines()

    assert lines[:2] == ["Writer doctor", "READY for local writing"]
    assert any(
        line.startswith("[optional] uoink: absent")
        for line in lines
    )


def test_doctor_required_failure_exits_nonzero(monkeypatch, capsys):
    failed = doctor.Check(
        "database", True, False, "failed", "read only", "choose a folder")
    optional = doctor.Check(
        "mcp", False, False, "not_installed", "manual mode remains")
    monkeypatch.setattr(
        doctor, "run_checks", lambda: [failed, optional])

    assert doctor.run(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["summary"]["required_ready"] == 0


def test_doctor_rejects_unknown_arguments(capsys):
    assert doctor.run(["--fix"]) == 2
    assert capsys.readouterr().out.strip() == (
        "usage: writer doctor [--json]")
