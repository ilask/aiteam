from __future__ import annotations

from types import SimpleNamespace

import tmux_ai_team.cli as cli


def _args(**overrides):
    base = {
        "session": "demo",
        "from_pane": "codex:1",
        "lines": 200,
        "marker": None,
        "wait_seconds": 0.0,
        "interval_seconds": 1.0,
        "output": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_cmd_capture_waits_for_marker_and_succeeds(monkeypatch, capsys) -> None:
    args = _args(marker="[DONE]", wait_seconds=2.0, interval_seconds=0.0)
    frames = iter(["working", "working", "answer\n[DONE]\n"])

    monkeypatch.setattr(cli, "_resolve_session", lambda _s: "demo")
    monkeypatch.setattr(cli, "_find_pane", lambda _s, _from: "%9")
    monkeypatch.setattr(cli, "capture_pane", lambda _pid, lines=200: next(frames))
    monkeypatch.setattr(cli.time, "sleep", lambda _sec: None)

    rc = cli.cmd_capture(args)

    out = capsys.readouterr()
    assert rc == 0
    assert "[DONE]" in out.out
    assert "Capture incomplete" not in out.err


def test_cmd_capture_incomplete_codex_prints_wait_hint(monkeypatch, capsys) -> None:
    args = _args(marker="[DONE]", wait_seconds=0.0)

    monkeypatch.setattr(cli, "_resolve_session", lambda _s: "demo")
    monkeypatch.setattr(cli, "_find_pane", lambda _s, _from: "%9")
    monkeypatch.setattr(cli, "capture_pane", lambda _pid, lines=200: "still working\n")
    monkeypatch.setattr(cli, "_is_codex_pane", lambda _s, _pid: True)

    rc = cli.cmd_capture(args)

    out = capsys.readouterr()
    assert rc == 3
    assert "still working" in out.out
    assert "Codex may still be processing; wait and retry." in out.err


def test_cmd_capture_incomplete_non_codex_has_generic_hint(monkeypatch, capsys) -> None:
    args = _args(from_pane="worker", marker="[DONE]", wait_seconds=0.0)

    monkeypatch.setattr(cli, "_resolve_session", lambda _s: "demo")
    monkeypatch.setattr(cli, "_find_pane", lambda _s, _from: "%2")
    monkeypatch.setattr(cli, "capture_pane", lambda _pid, lines=200: "still working\n")
    monkeypatch.setattr(cli, "_is_codex_pane", lambda _s, _pid: False)

    rc = cli.cmd_capture(args)

    out = capsys.readouterr()
    assert rc == 3
    assert "still working" in out.out
    assert "Capture incomplete: marker '[DONE]' not found yet." in out.err

