from __future__ import annotations

from types import SimpleNamespace

import tmux_ai_team.cli as cli


def test_is_codex_command_accepts_codex_forms() -> None:
    assert cli._is_codex_command("codex")
    assert cli._is_codex_command("AITEAM_X=1 codex -p aiteam")
    assert cli._is_codex_command("/usr/local/bin/codex --help")


def test_is_codex_command_rejects_non_codex() -> None:
    assert not cli._is_codex_command("")
    assert not cli._is_codex_command("agent")
    assert not cli._is_codex_command("AITEAM_X=1")


def test_install_session_briefing_sets_option_and_hook(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_set_session_option(session: str, option: str, value: str) -> None:
        calls.append(("option", session, option, value))

    def fake_set_hook(session: str, hook: str, command: str) -> None:
        calls.append(("hook", session, hook, command))

    monkeypatch.setattr(cli, "set_session_option", fake_set_session_option)
    monkeypatch.setattr(cli, "set_hook", fake_set_hook)

    cli._install_session_briefing("demo", "/tmp/briefing with space.md")

    assert calls[0] == ("option", "demo", cli._BRIEFING_OPTION, "/tmp/briefing with space.md")
    assert calls[1][0:3] == ("hook", "demo", "session-closed")
    assert "run-shell" in calls[1][3]
    assert "rm -f --" in calls[1][3]
    assert "briefing with space.md" in calls[1][3]


def test_load_session_briefing_text_reads_and_strips(monkeypatch, tmp_path) -> None:
    path = tmp_path / "briefing.md"
    path.write_text("  hello\n\n", encoding="utf-8")
    monkeypatch.setattr(cli, "get_session_option", lambda _s, _o: str(path))
    assert cli._load_session_briefing_text("demo") == "hello"


def test_load_session_briefing_text_returns_none_when_unset(monkeypatch) -> None:
    monkeypatch.setattr(cli, "get_session_option", lambda _s, _o: None)
    assert cli._load_session_briefing_text("demo") is None


def test_maybe_paste_briefing_pastes_for_codex(monkeypatch) -> None:
    pasted: list[tuple[str, str, bool]] = []
    sleeps: list[float] = []

    monkeypatch.setattr(cli, "_load_session_briefing_text", lambda _s: "briefing text")
    monkeypatch.setattr(cli.time, "sleep", lambda sec: sleeps.append(sec))
    monkeypatch.setattr(cli, "paste_text", lambda pane, txt, enter=True: pasted.append((pane, txt, enter)))

    cli._maybe_paste_briefing(session="demo", pane_id="%1", command="codex -p aiteam")

    assert sleeps == [0.8]
    assert pasted == [("%1", "briefing text", True)]


def test_maybe_paste_briefing_applies_to_all_agents(monkeypatch) -> None:
    pasted: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(cli, "_load_session_briefing_text", lambda _s: "briefing text")
    monkeypatch.setattr(cli, "paste_text", lambda pane, txt, enter=True: pasted.append((pane, txt, enter)))

    cli._maybe_paste_briefing(session="demo", pane_id="%1", command="claude")

    assert pasted == [("%1", "briefing text", True)]


def test_cmd_start_with_briefing_installs_session_briefing(monkeypatch) -> None:
    pane = SimpleNamespace(pane_id="%1")
    calls: list[tuple[str, ...]] = []

    args = SimpleNamespace(
        main="codex",
        command=None,
        title=None,
        cwd="/tmp/work",
        session="myproj",
        briefing=True,
        force=False,
        attach=False,
    )

    monkeypatch.setattr(cli, "_resolve_new_session_name", lambda **_k: ("myproj", False))
    monkeypatch.setattr(cli, "_create_briefing_file", lambda **_k: "/tmp/briefing.md")
    monkeypatch.setattr(cli, "_edit_file", lambda path: calls.append(("edit", path)))
    monkeypatch.setattr(cli, "_install_session_briefing", lambda session, path: calls.append(("install", session, path)))
    monkeypatch.setattr(cli, "tmux_version", lambda: "tmux 3.3")
    monkeypatch.setattr(cli, "new_session", lambda *a, **k: None)
    monkeypatch.setattr(cli, "list_panes", lambda _s: [pane])
    monkeypatch.setattr(cli, "set_pane_title", lambda _p, _t: None)
    monkeypatch.setattr(cli, "paste_text", lambda _p, _t, enter=True: None)
    monkeypatch.setattr(
        cli,
        "_maybe_paste_briefing",
        lambda session, pane_id, command: calls.append(("paste", session, pane_id, command)),
    )

    rc = cli.cmd_start(args)

    assert rc == 0
    assert ("edit", "/tmp/briefing.md") in calls
    assert ("install", "myproj", "/tmp/briefing.md") in calls
    assert ("paste", "myproj", "%1", cli._DEFAULT_CODEX_COMMAND) in calls


def test_cmd_spawn_removes_briefing_file_if_session_creation_fails(monkeypatch, tmp_path) -> None:
    briefing = tmp_path / "briefing.md"
    briefing.write_text("x", encoding="utf-8")

    args = SimpleNamespace(
        agent=["codex=codex"],
        cwd="/tmp/work",
        session="myproj",
        layout="vertical",
        force=False,
        attach=False,
        briefing=True,
    )

    monkeypatch.setattr(cli, "_resolve_new_session_name", lambda **_k: ("myproj", False))
    monkeypatch.setattr(cli, "_create_briefing_file", lambda **_k: str(briefing))
    monkeypatch.setattr(cli, "_edit_file", lambda _p: None)
    monkeypatch.setattr(cli, "tmux_version", lambda: "tmux 3.3")
    monkeypatch.setattr(cli, "new_session", lambda *a, **k: (_ for _ in ()).throw(cli.TmuxError("boom")))

    rc = cli.cmd_spawn(args)

    assert rc == 1
    assert not briefing.exists()


def test_cmd_kill_removes_briefing_file(monkeypatch, tmp_path) -> None:
    briefing = tmp_path / "briefing.md"
    briefing.write_text("x", encoding="utf-8")
    args = SimpleNamespace(session="myproj")

    monkeypatch.setattr(cli, "get_session_option", lambda _s, _o: str(briefing))
    monkeypatch.setattr(cli, "kill_session", lambda _s: None)

    rc = cli.cmd_kill(args)

    assert rc == 0
    assert not briefing.exists()
