from __future__ import annotations

from collections.abc import Callable
import subprocess


def test_real_workflow_start_add_codex_send_handoff_relay(
    ensure_real_e2e: Callable[[list[str]], None],
    real_agent_commands: dict[str, str],
    make_session_name: Callable[[str], str],
    run_aiteam: Callable[..., subprocess.CompletedProcess[str]],
    wait_capture_non_empty: Callable[..., str],
    wait_capture_contains: Callable[..., str],
    root_path,
) -> None:
    ensure_real_e2e(
        [
            real_agent_commands["codex"],
            real_agent_commands["claude"],
            real_agent_commands["agent"],
        ]
    )

    session = make_session_name("aiteam-e2e-flow")
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
                "claude",
                "--exec",
                real_agent_commands["claude"],
            ],
            timeout=60,
        )
        wait_capture_non_empty(session, "claude")

        run_aiteam(
            [
                "add",
                "--session",
                session,
                "--worker",
                f"agent={real_agent_commands['agent']}",
                "--layout",
                "horizontal",
            ],
            timeout=60,
        )
        wait_capture_non_empty(session, "agent")

        run_aiteam(
            [
                "add",
                "--session",
                session,
                "--worker",
                "sink=cat",
                "--layout",
                "vertical",
            ],
            timeout=60,
        )

        codex_cp = run_aiteam(
            [
                "codex",
                "--session",
                session,
                "--name",
                "main",
                "--exec",
                real_agent_commands["codex"],
            ],
            timeout=60,
        )
        selector = (codex_cp.stdout or "").strip().splitlines()[-1].strip()
        assert selector.startswith("codex:"), f"Unexpected codex selector output: {codex_cp.stdout!r}"
        wait_capture_non_empty(session, selector)

        run_aiteam(
            [
                "send",
                "--session",
                session,
                "--to",
                "claude",
                "--body",
                "echo REAL_RELAY_OK",
            ]
        )
        wait_capture_contains(session, "claude", "REAL_RELAY_OK")

        run_aiteam(
            [
                "relay",
                "--session",
                session,
                "--from",
                "claude",
                "--to",
                selector,
                "--already-visible",
                "--once",
                "--regex",
                "REAL_RELAY_OK",
                "--caption",
                "E2E_RELAY",
            ],
            timeout=60,
        )
        codex_after_relay = wait_capture_contains(session, selector, "REAL_RELAY_OK")
        assert "E2E_RELAY" in codex_after_relay

        run_aiteam(
            [
                "send",
                "--session",
                session,
                "--to",
                selector,
                "--body",
                "echo REAL_SEND_OK",
            ]
        )
        wait_capture_contains(session, selector, "REAL_SEND_OK")

        run_aiteam(
            [
                "send",
                "--session",
                session,
                "--to",
                selector,
                "--body",
                "echo E2E_HANDOFF_PAYLOAD",
            ]
        )
        wait_capture_contains(session, selector, "E2E_HANDOFF_PAYLOAD")

        run_aiteam(
            [
                "handoff",
                "--session",
                session,
                "--from",
                selector,
                "--to",
                "sink",
                "--lines",
                "40",
                "--caption",
                "E2E_HANDOFF",
            ],
            timeout=60,
        )
        sink_after_handoff = wait_capture_contains(session, "sink", "E2E_HANDOFF")
        assert "E2E_HANDOFF_PAYLOAD" in sink_after_handoff
    finally:
        run_aiteam(["kill", "--session", session], check=False)

