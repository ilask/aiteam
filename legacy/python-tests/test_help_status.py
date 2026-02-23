from __future__ import annotations

import tmux_ai_team.cli as cli


def test_agent_kind_from_pane_title_detects_supported_agents() -> None:
    assert cli._agent_kind_from_pane_title("codex#1:main") == "codex"
    assert cli._agent_kind_from_pane_title("codex") == "codex"
    assert cli._agent_kind_from_pane_title("claude") == "claude"
    assert cli._agent_kind_from_pane_title("agent") == "agent"
    assert cli._agent_kind_from_pane_title("cursor") == "cursor"
    assert cli._agent_kind_from_pane_title("gemini") == "gemini"
    assert cli._agent_kind_from_pane_title("misc-pane") is None


def test_help_status_epilog_returns_none_when_context_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_detect_help_agent_context", lambda: None)
    monkeypatch.setattr(cli, "_readme_abs_path", lambda: "/tmp/README.md")

    epilog = cli._help_status_epilog()

    assert "main-agent quick commands:" in epilog
    assert "aiteam codex --name <name>" in epilog
    assert "readme: /tmp/README.md" in epilog
    assert "status: running from aiteam agent pane" not in epilog


def test_help_status_epilog_includes_agent_context(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_readme_abs_path", lambda: "/tmp/README.md")
    monkeypatch.setattr(cli, "_detect_help_agent_context", lambda: ("codex", "demo", "codex#3:review"))

    epilog = cli._help_status_epilog()

    assert "kind=codex" in epilog
    assert "session=demo" in epilog
    assert "pane_title=codex#3:review" in epilog
    assert "readme: /tmp/README.md" in epilog


def test_root_help_text_avoids_tmux_wording() -> None:
    parser = cli.build_parser()
    help_text = parser.format_help().lower()
    assert "tmux helper" not in help_text
    assert "tmux session" not in help_text
