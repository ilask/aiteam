from __future__ import annotations

from collections.abc import Callable
import subprocess


def test_spawn_real_codex_claude_agent_headless(
    ensure_real_e2e: Callable[[list[str]], None],
    real_agent_commands: dict[str, str],
    make_session_name: Callable[[str], str],
    run_aiteam: Callable[..., subprocess.CompletedProcess[str]],
    wait_capture_non_empty: Callable[..., str],
    root_path,
) -> None:
    ensure_real_e2e(
        [
            real_agent_commands["codex"],
            real_agent_commands["claude"],
            real_agent_commands["agent"],
            real_agent_commands["gemini"],
        ]
    )

    session = make_session_name("aiteam-e2e")
    try:
        run_aiteam(
            [
                "spawn",
                "--session",
                session,
                "--cwd",
                str(root_path),
                "--worker",
                f"codex={real_agent_commands['codex']}",
                "--worker",
                f"claude={real_agent_commands['claude']}",
                "--worker",
                f"agent={real_agent_commands['agent']}",
                "--worker",
                f"gemini={real_agent_commands['gemini']}",
            ],
            timeout=60,
        )

        list_cp = run_aiteam(["list", "--filter", session], check=False)
        assert session in (list_cp.stdout or "")

        codex_out = wait_capture_non_empty(session, "codex")
        claude_out = wait_capture_non_empty(session, "claude")
        agent_out = wait_capture_non_empty(session, "agent")
        gemini_out = wait_capture_non_empty(session, "gemini")

        for pane_name, out in (("codex", codex_out), ("claude", claude_out), ("agent", agent_out), ("gemini", gemini_out)):
            low = out.lower()
            assert "command not found" not in low, f"{pane_name} appears missing:\n{out}"
            assert "not recognized as" not in low, f"{pane_name} appears missing:\n{out}"
    finally:
        run_aiteam(["kill", "--session", session], check=False)

