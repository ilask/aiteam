from __future__ import annotations

import subprocess

import pytest

from tmux_ai_team import tmux


def test_run_tmux_adds_hint_for_window_target_confusion(monkeypatch) -> None:
    def _fake_run(cmd, check=True, capture_output=True, text=True):  # noqa: ANN001
        if cmd[:4] == ["tmux", "list-panes", "-t", "store_sales-2:0"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="0\n1\n5\n", stderr="")
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=cmd,
            output="",
            stderr="can't find window: 5",
        )

    monkeypatch.setattr(tmux.subprocess, "run", _fake_run)

    with pytest.raises(tmux.TmuxError) as excinfo:
        tmux._run_tmux(["capture-pane", "-t", "store_sales-2:5", "-p"])

    msg = str(excinfo.value)
    assert "can't find window: 5" in msg
    assert "Invalid target 'store_sales-2:5'." in msg
    assert "Did you mean 'store_sales-2:0.5'" in msg
    assert "codex:5" in msg


def test_run_tmux_does_not_add_hint_for_other_errors(monkeypatch) -> None:
    def _fake_run(cmd, check=True, capture_output=True, text=True):  # noqa: ANN001
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=cmd,
            output="",
            stderr="can't find pane: %99",
        )

    monkeypatch.setattr(tmux.subprocess, "run", _fake_run)

    with pytest.raises(tmux.TmuxError) as excinfo:
        tmux._run_tmux(["capture-pane", "-t", "%99", "-p"])

    msg = str(excinfo.value)
    assert "can't find pane: %99" in msg
    assert "\nhint:\n" not in msg

