from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from typing import Any

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def _binary_name(command: str) -> str:
    parts = shlex.split(command)
    if not parts:
        return ""
    return os.path.basename(parts[0])


def _aiteam_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC}{os.pathsep}{current}" if current else str(SRC)
    return env


def _write_tmux_shim(*, shim_path: pathlib.Path) -> None:
    shim_path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

log_file="${AITEAM_TMUX_SHIM_LOG:?missing AITEAM_TMUX_SHIM_LOG}"
real_tmux="${AITEAM_REAL_TMUX:?missing AITEAM_REAL_TMUX}"
ppid="${PPID}"
parent_cmd="$(tr '\\0' ' ' <"/proc/${ppid}/cmdline" 2>/dev/null || true)"
printf '%s\\t%s\\t%s\\t%s\\t%s\\n' "$(date +%s.%N)" "$$" "$ppid" "$parent_cmd" "$*" >> "$log_file"
exec "$real_tmux" "$@"
""",
        encoding="utf-8",
    )
    shim_path.chmod(0o755)


@pytest.fixture
def run_aiteam() -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(args: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
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

    return _run


@pytest.fixture
def tmux_invocation_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    """Wrap tmux and fail if non-controller processes invoke mutating tmux commands."""
    real_tmux = shutil.which("tmux")
    if real_tmux is None:
        yield None
        return

    shim_dir = tmp_path / "tmux-shim-bin"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim_path = shim_dir / "tmux"
    _write_tmux_shim(shim_path=shim_path)

    log_path = tmp_path / "tmux-calls.log"
    monkeypatch.setenv("AITEAM_REAL_TMUX", real_tmux)
    monkeypatch.setenv("AITEAM_TMUX_SHIM_LOG", str(log_path))
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    yield log_path

    if not log_path.exists():
        return
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return

    allow_parent_tokens = ("tmux_ai_team", "pytest", "py.test")
    # Codex may probe terminal metadata via read-only tmux calls before rendering.
    # We allow only these exact probes from non-controller callers.
    allow_non_controller_tmux_args = {
        "display-message -p #{client_termtype}",
        "display-message -p #{client_termname}",
    }
    unexpected: list[str] = []
    for line in lines:
        parts = line.split("\t", 4)
        parent_cmd = parts[3] if len(parts) >= 4 else ""
        tmux_args = (parts[4] if len(parts) >= 5 else "").strip()
        is_controller = any(token in parent_cmd for token in allow_parent_tokens)
        is_allowed_probe = tmux_args in allow_non_controller_tmux_args
        if not is_controller and not is_allowed_probe:
            unexpected.append(line)

    if unexpected:
        raise AssertionError(
            "Detected tmux invocations from unexpected caller process(es):\n"
            + "\n".join(unexpected)
        )


@pytest.fixture
def make_session_name() -> Callable[[str], str]:
    def _make(prefix: str) -> str:
        return f"{prefix}-{os.getpid()}-{int(time.time() * 1000)}"

    return _make


@pytest.fixture
def real_agent_commands() -> dict[str, str]:
    return {
        "codex": (os.environ.get("AITEAM_E2E_CODEX_CMD") or "codex --help").strip(),
        "claude": (os.environ.get("AITEAM_E2E_CLAUDE_CMD") or "claude --help").strip(),
        "agent": (os.environ.get("AITEAM_E2E_AGENT_CMD") or "agent --help").strip(),
        "gemini": (os.environ.get("AITEAM_E2E_GEMINI_CMD") or "gemini --help").strip(),
    }


@pytest.fixture
def ensure_real_e2e() -> Callable[[Iterable[str]], None]:
    def _ensure(commands: Iterable[str]) -> None:
        if (os.environ.get("AITEAM_RUN_REAL_E2E") or "").strip() != "1":
            pytest.skip("Set AITEAM_RUN_REAL_E2E=1 to run real-agent e2e tests.")
        if shutil.which("tmux") is None:
            pytest.skip("tmux is not installed")

        missing: list[str] = []
        for command in commands:
            bin_name = _binary_name(command)
            if not bin_name or shutil.which(bin_name) is None:
                missing.append(bin_name or "(empty)")
        if missing:
            uniq = ", ".join(sorted(set(missing)))
            pytest.skip(f"Missing required binaries for real e2e: {uniq}")

    return _ensure


@pytest.fixture
def wait_capture_non_empty(run_aiteam: Callable[..., subprocess.CompletedProcess[str]]) -> Callable[..., str]:
    def _wait(session: str, pane: str, *, timeout_sec: float = 25.0) -> str:
        deadline = time.time() + timeout_sec
        last = ""
        while time.time() < deadline:
            cp = run_aiteam(
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

    return _wait


@pytest.fixture
def wait_capture_contains(run_aiteam: Callable[..., subprocess.CompletedProcess[str]]) -> Callable[..., str]:
    def _wait(session: str, pane: str, needle: str, *, timeout_sec: float = 25.0) -> str:
        deadline = time.time() + timeout_sec
        last = ""
        while time.time() < deadline:
            cp = run_aiteam(
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

    return _wait


@pytest.fixture
def wait_capture_any_contains(run_aiteam: Callable[..., subprocess.CompletedProcess[str]]) -> Callable[..., str]:
    def _wait(session: str, pane: str, needles: list[str], *, timeout_sec: float = 25.0) -> str:
        deadline = time.time() + timeout_sec
        last = ""
        while time.time() < deadline:
            cp = run_aiteam(
                ["capture", "--session", session, "--from", pane, "--lines", "260"],
                timeout=15,
                check=False,
            )
            out = cp.stdout or ""
            if cp.returncode == 0 and any(needle in out for needle in needles):
                return out
            last = f"rc={cp.returncode}\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
            time.sleep(0.5)
        raise AssertionError(f"Timed out waiting one of {needles!r} in pane '{pane}'. Last:\n{last}")

    return _wait


@pytest.fixture
def error_pane_titles() -> Callable[[str], list[str]]:
    def _titles(session: str) -> list[str]:
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

    return _titles


@pytest.fixture
def root_path() -> pathlib.Path:
    return ROOT


@pytest.fixture
def aiteam_env() -> dict[str, Any]:
    return _aiteam_env()
