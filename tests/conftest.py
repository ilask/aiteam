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
