from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _env_enabled() -> bool:
    return (os.environ.get("AITEAM_RUN_REAL_E2E") or "").strip() == "1"


def _aiteam_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC}{os.pathsep}{current}" if current else str(SRC)
    return env


def _run_aiteam(args: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        [sys.executable, "-m", "tmux_ai_team", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
        env=_aiteam_env(),
    )
    if check and cp.returncode != 0:
        raise AssertionError(
            f"aiteam command failed ({cp.returncode}): {' '.join(args)}\n"
            f"stdout:\n{cp.stdout}\n"
            f"stderr:\n{cp.stderr}\n"
        )
    return cp


def _binary_name(command: str) -> str:
    parts = shlex.split(command)
    if not parts:
        return ""
    return os.path.basename(parts[0])


def _wait_capture_non_empty(session: str, pane: str, *, timeout_sec: float = 25.0) -> str:
    deadline = time.time() + timeout_sec
    last = ""
    while time.time() < deadline:
        cp = _run_aiteam(
            ["capture", "--session", session, "--from", pane, "--lines", "160"],
            timeout=15,
            check=False,
        )
        out = (cp.stdout or "").strip()
        if cp.returncode == 0 and out:
            return out
        last = f"rc={cp.returncode}\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting non-empty capture from pane '{pane}'. Last:\n{last}")


def _wait_capture_contains(session: str, pane: str, needle: str, *, timeout_sec: float = 25.0) -> str:
    deadline = time.time() + timeout_sec
    last = ""
    while time.time() < deadline:
        cp = _run_aiteam(
            ["capture", "--session", session, "--from", pane, "--lines", "240"],
            timeout=15,
            check=False,
        )
        out = cp.stdout or ""
        if cp.returncode == 0 and needle in out:
            return out
        last = f"rc={cp.returncode}\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting '{needle}' in pane '{pane}'. Last:\n{last}")


def _error_pane_titles(session: str) -> list[str]:
    cp = subprocess.run(
        ["tmux", "list-panes", "-t", session, "-F", "#{pane_title}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        return []
    titles = []
    for raw in (cp.stdout or "").splitlines():
        title = raw.strip()
        if title.startswith("codex#err") and title.endswith(":error"):
            titles.append(title)
    return titles


@pytest.mark.skipif(not _env_enabled(), reason="Set AITEAM_RUN_REAL_E2E=1 to run real-agent e2e tests.")
def test_spawn_real_codex_claude_agent_headless() -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")

    codex_cmd = (os.environ.get("AITEAM_E2E_CODEX_CMD") or "codex --help").strip()
    claude_cmd = (os.environ.get("AITEAM_E2E_CLAUDE_CMD") or "claude --help").strip()
    agent_cmd = (os.environ.get("AITEAM_E2E_AGENT_CMD") or "agent --help").strip()

    missing = []
    for command in (codex_cmd, claude_cmd, agent_cmd):
        bin_name = _binary_name(command)
        if not bin_name or shutil.which(bin_name) is None:
            missing.append(bin_name or "(empty)")
    if missing:
        pytest.skip(f"Missing required binaries for real e2e: {', '.join(sorted(set(missing)))}")

    session = f"aiteam-e2e-{os.getpid()}-{int(time.time())}"
    try:
        _run_aiteam(
            [
                "spawn",
                "--session",
                session,
                "--cwd",
                str(ROOT),
                "--worker",
                f"codex={codex_cmd}",
                "--worker",
                f"claude={claude_cmd}",
                "--worker",
                f"agent={agent_cmd}",
            ],
            timeout=60,
        )

        list_cp = _run_aiteam(["list", "--filter", session], check=False)
        assert session in (list_cp.stdout or "")

        codex_out = _wait_capture_non_empty(session, "codex")
        claude_out = _wait_capture_non_empty(session, "claude")
        agent_out = _wait_capture_non_empty(session, "agent")

        for pane_name, out in (("codex", codex_out), ("claude", claude_out), ("agent", agent_out)):
            low = out.lower()
            assert "command not found" not in low, f"{pane_name} appears missing:\n{out}"
            assert "not recognized as" not in low, f"{pane_name} appears missing:\n{out}"
    finally:
        _run_aiteam(["kill", "--session", session], check=False)


@pytest.mark.skipif(not _env_enabled(), reason="Set AITEAM_RUN_REAL_E2E=1 to run real-agent e2e tests.")
def test_real_workflow_start_add_codex_send_handoff_relay() -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")

    codex_cmd = (os.environ.get("AITEAM_E2E_CODEX_CMD") or "codex --help").strip()
    claude_cmd = (os.environ.get("AITEAM_E2E_CLAUDE_CMD") or "claude --help").strip()
    agent_cmd = (os.environ.get("AITEAM_E2E_AGENT_CMD") or "agent --help").strip()

    missing = []
    for command in (codex_cmd, claude_cmd, agent_cmd):
        bin_name = _binary_name(command)
        if not bin_name or shutil.which(bin_name) is None:
            missing.append(bin_name or "(empty)")
    if missing:
        pytest.skip(f"Missing required binaries for real e2e: {', '.join(sorted(set(missing)))}")

    session = f"aiteam-e2e-flow-{os.getpid()}-{int(time.time())}"
    try:
        _run_aiteam(
            [
                "start",
                "--session",
                session,
                "--cwd",
                str(ROOT),
                "--main",
                "custom",
                "--title",
                "claude",
                "--exec",
                claude_cmd,
            ],
            timeout=60,
        )
        _wait_capture_non_empty(session, "claude")

        _run_aiteam(
            [
                "add",
                "--session",
                session,
                "--worker",
                f"agent={agent_cmd}",
                "--layout",
                "horizontal",
            ],
            timeout=60,
        )
        _wait_capture_non_empty(session, "agent")

        _run_aiteam(
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

        codex_cp = _run_aiteam(
            [
                "codex",
                "--session",
                session,
                "--name",
                "main",
                "--exec",
                codex_cmd,
            ],
            timeout=60,
        )
        selector = (codex_cp.stdout or "").strip().splitlines()[-1].strip()
        assert selector.startswith("codex:"), f"Unexpected codex selector output: {codex_cp.stdout!r}"
        _wait_capture_non_empty(session, selector)

        _run_aiteam(
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
        _wait_capture_contains(session, "claude", "REAL_RELAY_OK")

        _run_aiteam(
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
        codex_after_relay = _wait_capture_contains(session, selector, "REAL_RELAY_OK")
        assert "E2E_RELAY" in codex_after_relay

        _run_aiteam(
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
        _wait_capture_contains(session, selector, "REAL_SEND_OK")

        _run_aiteam(
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
        _wait_capture_contains(session, selector, "E2E_HANDOFF_PAYLOAD")

        _run_aiteam(
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
        sink_after_handoff = _wait_capture_contains(session, "sink", "E2E_HANDOFF")
        assert "E2E_HANDOFF_PAYLOAD" in sink_after_handoff
    finally:
        _run_aiteam(["kill", "--session", session], check=False)


@pytest.mark.skipif(not _env_enabled(), reason="Set AITEAM_RUN_REAL_E2E=1 to run real-agent e2e tests.")
def test_error_codex_autostarts_when_enabled() -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    if shutil.which("codex") is None:
        pytest.skip("codex is not installed")

    session = f"aiteam-e2e-err-{os.getpid()}-{int(time.time())}"
    try:
        _run_aiteam(
            [
                "start",
                "--session",
                session,
                "--cwd",
                str(ROOT),
                "--main",
                "custom",
                "--title",
                "main",
                "--exec",
                "bash",
            ],
            timeout=60,
        )

        cp = _run_aiteam(
            [
                "--error-codex",
                "capture",
                "--session",
                session,
                "--from",
                "codex:999",
                "--lines",
                "20",
            ],
            timeout=60,
            check=False,
        )
        assert cp.returncode == 1
        assert "No Codex pane with id '999'" in (cp.stderr or "")

        err_out = _wait_capture_contains(session, "codex:err1", "Please respond with:", timeout_sec=40.0)
        assert "No Codex pane with id '999'" in err_out
    finally:
        _run_aiteam(["kill", "--session", session], check=False)


@pytest.mark.skipif(not _env_enabled(), reason="Set AITEAM_RUN_REAL_E2E=1 to run real-agent e2e tests.")
def test_error_codex_parallel_failures_spawn_only_one_error_pane() -> None:
    # Purpose: concurrent failures should not create duplicate codex#err* panes.
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    if shutil.which("codex") is None:
        pytest.skip("codex is not installed")

    session = f"aiteam-e2e-err-race-{os.getpid()}-{int(time.time())}"
    try:
        _run_aiteam(
            [
                "start",
                "--session",
                session,
                "--cwd",
                str(ROOT),
                "--main",
                "custom",
                "--title",
                "main",
                "--exec",
                "bash",
            ],
            timeout=60,
        )

        cmd = [
            sys.executable,
            "-m",
            "tmux_ai_team",
            "--error-codex",
            "capture",
            "--session",
            session,
            "--from",
            "codex:999",
            "--lines",
            "20",
        ]

        p1 = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=_aiteam_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        p2 = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=_aiteam_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        o1, e1 = p1.communicate(timeout=90)
        o2, e2 = p2.communicate(timeout=90)

        assert p1.returncode == 1, f"stdout={o1}\nstderr={e1}"
        assert p2.returncode == 1, f"stdout={o2}\nstderr={e2}"

        _wait_capture_contains(session, "codex:err1", "Please respond with:", timeout_sec=40.0)

        deadline = time.time() + 15.0
        err_titles: list[str] = []
        while time.time() < deadline:
            err_titles = _error_pane_titles(session)
            if len(err_titles) == 1:
                break
            time.sleep(0.3)

        assert len(err_titles) == 1, f"expected exactly one error pane, got: {err_titles}"
    finally:
        _run_aiteam(["kill", "--session", session], check=False)
