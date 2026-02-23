from __future__ import annotations

from types import SimpleNamespace

import pytest

import tmux_ai_team.cli as cli


def _pane(pane_id: str, pane_index: int, title: str):
    return SimpleNamespace(pane_id=pane_id, pane_index=pane_index, pane_title=title)


def test_find_pane_resolves_unique_codex_label(monkeypatch) -> None:
    # Purpose: selector by Codex label (e.g., analyst1) should resolve without requiring codex:<id>.
    monkeypatch.setattr(
        cli,
        "list_panes",
        lambda _session: [
            _pane("%0", 0, "codex"),
            _pane("%1", 1, "codex#1:analyst1"),
            _pane("%2", 2, "codex#2:analyst2"),
        ],
    )

    assert cli._find_pane("demo", "analyst1") == "%1"


def test_find_pane_resolves_unique_codex_label_case_insensitive(monkeypatch) -> None:
    # Purpose: label matching should be resilient to capitalization differences.
    monkeypatch.setattr(
        cli,
        "list_panes",
        lambda _session: [
            _pane("%1", 1, "codex#1:AnalystA"),
            _pane("%2", 2, "codex#2:worker"),
        ],
    )

    assert cli._find_pane("demo", "analysta") == "%1"


def test_find_pane_rejects_ambiguous_codex_label(monkeypatch) -> None:
    # Purpose: duplicate labels should fail fast and ask for explicit codex:<id>.
    monkeypatch.setattr(
        cli,
        "list_panes",
        lambda _session: [
            _pane("%1", 1, "codex#1:worker"),
            _pane("%2", 2, "codex#2:worker"),
        ],
    )

    with pytest.raises(cli.TmuxError, match="Ambiguous Codex label 'worker'"):
        cli._find_pane("demo", "worker")
