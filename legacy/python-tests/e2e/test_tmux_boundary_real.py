from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess


def test_tmux_commands_are_only_invoked_by_aiteam_process(
    ensure_real_e2e: Callable[[list[str]], None],
    make_session_name: Callable[[str], str],
    run_aiteam: Callable[..., subprocess.CompletedProcess[str]],
    wait_capture_contains: Callable[..., str],
    tmux_invocation_guard: Path | None,
    root_path,
) -> None:
    # Purpose: ensure pane-side execution works under tmux shim guard,
    # and verify that aiteam actually issued tmux control commands.
    ensure_real_e2e(["bash"])
    assert tmux_invocation_guard is not None

    session = make_session_name("aiteam-e2e-boundary")
    try:
        run_aiteam(
            [
                "start",
                "--session",
                session,
                "--cwd",
                str(root_path),
                "--main",
                "custom",
                "--title",
                "codex#1:main",
                "--exec",
                "bash",
            ],
            timeout=60,
        )

        run_aiteam(
            [
                "send",
                "--session",
                session,
                "--to",
                "codex:1",
                "--body",
                "printf '__BOUNDARY_OK__\\n'",
            ],
            timeout=30,
        )
        wait_capture_contains(session, "codex:1", "__BOUNDARY_OK__")
    finally:
        run_aiteam(["kill", "--session", session], check=False)

    lines = [line for line in tmux_invocation_guard.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, "tmux shim log is empty"
    assert any("tmux_ai_team" in line for line in lines), "tmux control calls from aiteam were not observed"
