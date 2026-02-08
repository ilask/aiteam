from __future__ import annotations

from types import SimpleNamespace

import tmux_ai_team.cli as cli
import tmux_ai_team.tmux as tmux


def test_paste_text_empty_input_sends_enter_only(monkeypatch) -> None:
    # Purpose: empty stdin/pipe should behave as "press Enter", not tmux buffer failure.
    calls: list[list[str]] = []

    def _fake_run(args, check=True, capture=True, text=True):  # noqa: ANN001
        calls.append(list(args))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(tmux, "_run_tmux", _fake_run)

    tmux.paste_text("%1", "", enter=True)

    assert calls == [["send-keys", "-t", "%1", "C-m"]]


def test_paste_text_empty_input_no_enter_is_noop(monkeypatch) -> None:
    # Purpose: empty text with --no-enter should be a clean no-op.
    calls: list[list[str]] = []

    def _fake_run(args, check=True, capture=True, text=True):  # noqa: ANN001
        calls.append(list(args))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(tmux, "_run_tmux", _fake_run)

    tmux.paste_text("%1", "", enter=False)

    assert calls == []


def test_cmd_send_multiline_to_codex_confirms_with_extra_enter(monkeypatch) -> None:
    # Purpose: multiline prompt to Codex should get an extra submit Enter for reliability.
    args = SimpleNamespace(
        session="demo",
        to="codex:1",
        text=None,
        file=None,
        stdin=False,
        no_enter=False,
    )
    pasted: list[tuple[str, str, bool]] = []
    keys: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(cli, "_find_pane", lambda _s, _to: "%9")
    monkeypatch.setattr(cli, "_read_text_input", lambda _a: "line1\nline2")
    monkeypatch.setattr(cli, "_is_codex_pane", lambda _s, _p: True)
    monkeypatch.setattr(cli, "paste_text", lambda pane, text, enter=True: pasted.append((pane, text, enter)))
    monkeypatch.setattr(cli, "send_keys", lambda pane, key_list: keys.append((pane, key_list)))
    monkeypatch.setattr(cli.time, "sleep", lambda _sec: None)

    rc = cli.cmd_send(args)

    assert rc == 0
    assert pasted == [("%9", "line1\nline2", True)]
    assert keys == [("%9", ["C-m"])]


def test_cmd_send_single_line_to_codex_does_not_send_extra_enter(monkeypatch) -> None:
    # Purpose: single-line messages should keep current behavior (one submit only).
    args = SimpleNamespace(
        session="demo",
        to="codex:1",
        text=None,
        file=None,
        stdin=False,
        no_enter=False,
    )
    keys: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(cli, "_find_pane", lambda _s, _to: "%9")
    monkeypatch.setattr(cli, "_read_text_input", lambda _a: "single line")
    monkeypatch.setattr(cli, "_is_codex_pane", lambda _s, _p: True)
    monkeypatch.setattr(cli, "paste_text", lambda _pane, _text, enter=True: None)
    monkeypatch.setattr(cli, "send_keys", lambda pane, key_list: keys.append((pane, key_list)))
    monkeypatch.setattr(cli.time, "sleep", lambda _sec: None)

    rc = cli.cmd_send(args)

    assert rc == 0
    assert keys == []


def test_cmd_send_multiline_to_non_codex_does_not_send_extra_enter(monkeypatch) -> None:
    # Purpose: extra submit Enter is Codex-only and should not affect other panes.
    args = SimpleNamespace(
        session="demo",
        to="worker",
        text=None,
        file=None,
        stdin=False,
        no_enter=False,
    )
    keys: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(cli, "_find_pane", lambda _s, _to: "%2")
    monkeypatch.setattr(cli, "_read_text_input", lambda _a: "line1\nline2")
    monkeypatch.setattr(cli, "_is_codex_pane", lambda _s, _p: False)
    monkeypatch.setattr(cli, "paste_text", lambda _pane, _text, enter=True: None)
    monkeypatch.setattr(cli, "send_keys", lambda pane, key_list: keys.append((pane, key_list)))
    monkeypatch.setattr(cli.time, "sleep", lambda _sec: None)

    rc = cli.cmd_send(args)

    assert rc == 0
    assert keys == []
