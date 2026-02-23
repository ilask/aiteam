from __future__ import annotations

from types import SimpleNamespace

import tmux_ai_team.cli as cli


def test_relay_already_visible_relays_initial_match_once(monkeypatch) -> None:
    pasted: list[tuple[str, str, bool]] = []
    slept: list[float] = []

    args = SimpleNamespace(
        session="demo",
        from_pane="src",
        to_pane="dst",
        lines=2000,
        interval=1.0,
        dedupe_ttl=600.0,
        include_existing=True,
        once=True,
        max_sends=0,
        no_enter=False,
        header=None,
        prefix=None,
        dry_run=False,
        verbose=False,
        pattern=None,
        group=None,
        begin="[PUSH]",
        end="[/PUSH]",
        keep_markers=False,
    )

    monkeypatch.setattr(cli, "_find_pane", lambda _s, pane: "%1" if pane == "src" else "%2")
    monkeypatch.setattr(cli, "capture_pane", lambda _pane, lines=200: "[PUSH]\nhello\n[/PUSH]\n")
    monkeypatch.setattr(cli, "paste_text", lambda pane, text, enter=True: pasted.append((pane, text, enter)))
    monkeypatch.setattr(cli.time, "sleep", lambda sec: slept.append(sec))

    rc = cli.cmd_relay(args)

    assert rc == 0
    assert pasted == [("%2", "hello", True)]
    assert slept == []


def test_selftest_runs_relay_with_already_visible(monkeypatch, tmp_path) -> None:
    relay_args_seen: list[SimpleNamespace] = []
    killed: list[str] = []
    tempdir = tmp_path / "selftest_tmp"
    tempdir.mkdir()

    args = SimpleNamespace(session="selftest-s", cwd="/tmp/work", keep=False, attach=False, verbose=False)

    monkeypatch.setattr(cli.tempfile, "mkdtemp", lambda prefix="": str(tempdir))
    monkeypatch.setattr(cli, "new_session", lambda _s, cwd=None, force=False: None)
    monkeypatch.setattr(cli, "split_window", lambda _s, cwd=None, vertical=True: None)
    monkeypatch.setattr(
        cli,
        "list_panes",
        lambda _s: [SimpleNamespace(pane_id="%1"), SimpleNamespace(pane_id="%2")],
    )
    monkeypatch.setattr(cli, "set_pane_title", lambda _p, _t: None)
    monkeypatch.setattr(cli, "paste_text", lambda _p, _t, enter=True: None)
    monkeypatch.setattr(cli.time, "sleep", lambda _sec: None)
    monkeypatch.setattr(cli, "cmd_relay", lambda relay_args: relay_args_seen.append(relay_args) or 0)
    monkeypatch.setattr(cli, "capture_pane", lambda _p, lines=200: "pong\n")
    monkeypatch.setattr(cli, "kill_session", lambda s: killed.append(s))

    rc = cli.cmd_selftest(args)

    assert rc == 0
    assert len(relay_args_seen) == 1
    assert relay_args_seen[0].include_existing is True
    assert relay_args_seen[0].once is True
    assert killed == ["selftest-s"]
