from __future__ import annotations

from collections.abc import Callable
import subprocess
import time


def test_capture_marker_wait_handles_long_running_codex_like_work(
    ensure_real_e2e: Callable[[list[str]], None],
    make_session_name: Callable[[str], str],
    run_aiteam: Callable[..., subprocess.CompletedProcess[str]],
    wait_capture_non_empty: Callable[..., str],
    root_path,
) -> None:
    # Purpose: when capture marker is not ready yet, caller gets a "wait" hint;
    # waiting long enough should then capture the completed result.
    ensure_real_e2e(["bash"])

    session = make_session_name("aiteam-e2e-capture-wait")
    marker = "__E2E_WAIT_DONE__"
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
        wait_capture_non_empty(session, "codex:1")

        run_aiteam(
            [
                "send",
                "--session",
                session,
                "--to",
                "codex:1",
                "--body",
                "bash -lc 'sleep 2; A=__E2E_WAIT_; B=DONE__; printf \"%s%s\\n\" \"$A\" \"$B\"'",
            ],
            timeout=30,
        )

        t0 = time.monotonic()
        early = run_aiteam(
            [
                "capture",
                "--session",
                session,
                "--from",
                "codex:1",
                "--lines",
                "160",
                "--marker",
                marker,
                "--wait-seconds",
                "0.3",
                "--interval-seconds",
                "0.1",
            ],
            timeout=30,
            check=False,
        )
        early_elapsed = time.monotonic() - t0

        assert early.returncode == 3, f"stdout={early.stdout}\nstderr={early.stderr}"
        assert "Codex may still be processing; wait and retry." in (early.stderr or "")
        assert marker not in (early.stdout or "")
        assert early_elapsed < 2.0

        t1 = time.monotonic()
        late = run_aiteam(
            [
                "capture",
                "--session",
                session,
                "--from",
                "codex:1",
                "--lines",
                "160",
                "--marker",
                marker,
                "--wait-seconds",
                "6.0",
                "--interval-seconds",
                "0.2",
            ],
            timeout=30,
            check=False,
        )
        late_elapsed = time.monotonic() - t1

        assert late.returncode == 0, f"stdout={late.stdout}\nstderr={late.stderr}"
        assert marker in (late.stdout or "")
        assert late_elapsed >= 1.0
    finally:
        run_aiteam(["kill", "--session", session], check=False)
