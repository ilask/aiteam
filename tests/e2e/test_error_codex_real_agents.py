from __future__ import annotations

from collections.abc import Callable
import subprocess
import sys
import time


def test_error_codex_autostarts_when_enabled(
    ensure_real_e2e: Callable[[list[str]], None],
    make_session_name: Callable[[str], str],
    run_aiteam: Callable[..., subprocess.CompletedProcess[str]],
    wait_capture_any_contains: Callable[..., str],
    root_path,
) -> None:
    ensure_real_e2e(["codex"])

    session = make_session_name("aiteam-e2e-err")
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
                "main",
                "--exec",
                "bash",
            ],
            timeout=60,
        )

        cp = run_aiteam(
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

        err_out = wait_capture_any_contains(
            session,
            "codex:err1",
            ["Please respond with:", "Likely root cause", "No Codex pane with id '999'"],
            timeout_sec=45.0,
        )
        assert "No Codex pane with id '999'" in err_out
    finally:
        run_aiteam(["kill", "--session", session], check=False)


def test_error_codex_parallel_failures_spawn_only_one_error_pane(
    ensure_real_e2e: Callable[[list[str]], None],
    make_session_name: Callable[[str], str],
    run_aiteam: Callable[..., subprocess.CompletedProcess[str]],
    wait_capture_any_contains: Callable[..., str],
    error_pane_titles: Callable[[str], list[str]],
    aiteam_env: dict[str, str],
    root_path,
) -> None:
    # Purpose: concurrent failures should not create duplicate codex#err* panes.
    ensure_real_e2e(["codex"])

    session = make_session_name("aiteam-e2e-err-race")
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
            cwd=str(root_path),
            env=aiteam_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        p2 = subprocess.Popen(
            cmd,
            cwd=str(root_path),
            env=aiteam_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        o1, e1 = p1.communicate(timeout=90)
        o2, e2 = p2.communicate(timeout=90)

        assert p1.returncode == 1, f"stdout={o1}\nstderr={e1}"
        assert p2.returncode == 1, f"stdout={o2}\nstderr={e2}"

        wait_capture_any_contains(
            session,
            "codex:err1",
            ["Please respond with:", "Likely root cause", "No Codex pane with id '999'"],
            timeout_sec=45.0,
        )

        deadline = time.time() + 15.0
        err_titles: list[str] = []
        while time.time() < deadline:
            err_titles = error_pane_titles(session)
            if len(err_titles) == 1:
                break
            time.sleep(0.3)

        assert len(err_titles) == 1, f"expected exactly one error pane, got: {err_titles}"
    finally:
        run_aiteam(["kill", "--session", session], check=False)


def test_error_codex_send_failures_keep_single_error_pane(
    ensure_real_e2e: Callable[[list[str]], None],
    make_session_name: Callable[[str], str],
    run_aiteam: Callable[..., subprocess.CompletedProcess[str]],
    wait_capture_any_contains: Callable[..., str],
    error_pane_titles: Callable[[str], list[str]],
    aiteam_env: dict[str, str],
    root_path,
) -> None:
    # Purpose: rapid send-path failures should still spawn only one error analyzer pane.
    ensure_real_e2e(["codex"])

    session = make_session_name("aiteam-e2e-err-send")
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
            "send",
            "--session",
            session,
            "--to",
            "codex:999",
            "--body",
            "E2E_SEND_FAIL_TRIGGER",
        ]

        p1 = subprocess.Popen(
            cmd,
            cwd=str(root_path),
            env=aiteam_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        p2 = subprocess.Popen(
            cmd,
            cwd=str(root_path),
            env=aiteam_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        o1, e1 = p1.communicate(timeout=90)
        o2, e2 = p2.communicate(timeout=90)

        assert p1.returncode == 1, f"stdout={o1}\nstderr={e1}"
        assert p2.returncode == 1, f"stdout={o2}\nstderr={e2}"
        assert "No Codex pane with id '999'" in e1
        assert "No Codex pane with id '999'" in e2

        err_out = wait_capture_any_contains(
            session,
            "codex:err1",
            ["Please respond with:", "Likely root cause", "No Codex pane with id '999'"],
            timeout_sec=45.0,
        )
        assert "No Codex pane with id '999'" in err_out

        deadline = time.time() + 15.0
        err_titles: list[str] = []
        while time.time() < deadline:
            err_titles = error_pane_titles(session)
            if len(err_titles) == 1:
                break
            time.sleep(0.3)
        assert len(err_titles) == 1, f"expected exactly one error pane, got: {err_titles}"
    finally:
        run_aiteam(["kill", "--session", session], check=False)

