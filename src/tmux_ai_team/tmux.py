"""
tmux helpers for tmux-ai-team-tool.

We deliberately keep dependencies at zero and talk to tmux via subprocess.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import tempfile
from typing import List, Optional


class TmuxError(RuntimeError):
    pass


def _run_tmux(args: List[str], *, check: bool = True, capture: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    """
    Run a tmux command.

    args: list of tmux arguments excluding the leading "tmux".
    """
    cmd = ["tmux", *args]
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=text,
        )
    except OSError as e:
        raise TmuxError(f"Unable to execute tmux: {e}") from e
    except subprocess.CalledProcessError as e:
        # Include stderr for better diagnostics
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        msg = f"tmux command failed: {' '.join(cmd)}"
        if stdout:
            msg += f"\nstdout:\n{stdout}"
        if stderr:
            msg += f"\nstderr:\n{stderr}"
        raise TmuxError(msg) from e


def tmux_version() -> str:
    cp = _run_tmux(["-V"])
    return (cp.stdout or "").strip()


def session_exists(session: str) -> bool:
    cp = _run_tmux(["has-session", "-t", session], check=False, capture=True)
    return cp.returncode == 0


def kill_session(session: str) -> None:
    _run_tmux(["kill-session", "-t", session])


def list_sessions() -> List[str]:
    cp = _run_tmux(["list-sessions", "-F", "#{session_name}"], check=False)
    if cp.returncode != 0:
        return []
    out = (cp.stdout or "").strip()
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]



def in_tmux() -> bool:
    """Return True if running inside a tmux client."""
    # TMUX is typically set inside tmux; display-message is the more reliable check.
    return bool(os.environ.get("TMUX"))


def display_message(fmt: str, *, target: Optional[str] = None) -> str:
    """Return `tmux display-message -p` output for the given format string.

    If target is provided, it is passed as `-t <target>` (pane/window/session).
    """
    args = ["display-message", "-p"]
    if target:
        args += ["-t", target]
    args.append(fmt)
    cp = _run_tmux(args, check=True)
    return (cp.stdout or "").strip()


def current_session_name() -> str:
    """Return the current tmux session name (requires being inside a tmux client)."""
    return display_message("#{session_name}")


def current_pane_id() -> str:
    """Return the current tmux pane id (requires being inside a tmux client)."""
    return display_message("#{pane_id}")


def pane_current_path(target: Optional[str] = None) -> str:
    """Return pane current path.

    If target is omitted, uses the current client pane.
    """
    return display_message("#{pane_current_path}", target=target)


def select_pane(pane_id: str) -> None:
    _run_tmux(["select-pane", "-t", pane_id], check=False)


def split_from(target: str, *, cwd: Optional[str] = None, vertical: bool = True) -> None:
    """Split starting from a specific target (pane/window/session).

    vertical=True => left/right split (-h). vertical=False => top/bottom (-v)
    """
    args = ["split-window", "-t", target]
    if cwd:
        args += ["-c", cwd]
    args += ["-h" if vertical else "-v"]
    _run_tmux(args)

def new_session(session: str, *, cwd: Optional[str] = None, force: bool = False) -> None:
    if session_exists(session):
        if force:
            kill_session(session)
        else:
            raise TmuxError(f"Session already exists: {session} (use --force to replace it)")
    args = ["new-session", "-d", "-s", session]
    if cwd:
        args += ["-c", cwd]
    _run_tmux(args)

    # Nice-to-have: show pane titles on borders (supported on newer tmux).
    # If the tmux version is older, ignore errors.
    _run_tmux(["set-option", "-t", session, "pane-border-status", "top"], check=False)
    _run_tmux(["set-option", "-t", session, "pane-border-format", "#{pane_title}"], check=False)


def split_window(session: str, *, cwd: Optional[str] = None, vertical: bool = True) -> None:
    """
    Create a new pane by splitting the active pane in the given session/window.
    vertical=True => left/right split (-h). vertical=False => top/bottom split (-v)
    """
    args = ["split-window", "-t", f"{session}:0"]
    if cwd:
        args += ["-c", cwd]
    args += ["-h" if vertical else "-v"]
    _run_tmux(args)


def select_layout_tiled(session: str) -> None:
    _run_tmux(["select-layout", "-t", f"{session}:0", "tiled"], check=False)


@dataclass(frozen=True)
class PaneInfo:
    pane_id: str
    pane_index: int
    pane_title: str


def list_panes(session: str) -> List[PaneInfo]:
    fmt = "#{pane_id}\t#{pane_index}\t#{pane_title}"
    cp = _run_tmux(["list-panes", "-t", f"{session}:0", "-F", fmt])
    out = (cp.stdout or "").strip()
    panes: List[PaneInfo] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pane_id, pane_index_s, pane_title = parts
        try:
            pane_index = int(pane_index_s)
        except ValueError:
            continue
        panes.append(PaneInfo(pane_id=pane_id.strip(), pane_index=pane_index, pane_title=pane_title.strip()))
    panes.sort(key=lambda p: p.pane_index)
    return panes


def set_session_option(session: str, option: str, value: str) -> None:
    """Set a session-scoped option (including user options like @foo)."""
    _run_tmux(["set-option", "-t", session, option, value], check=False)


def get_session_option(session: str, option: str) -> Optional[str]:
    """Get a session-scoped option value, or None if unset."""
    cp = _run_tmux(["show-option", "-t", session, "-v", option], check=False)
    if cp.returncode != 0:
        return None
    val = (cp.stdout or "").strip()
    return val or None


def set_hook(session: str, hook: str, command: str) -> None:
    """Set a tmux hook command for the session (best-effort)."""
    _run_tmux(["set-hook", "-t", session, hook, command], check=False)


def set_pane_title(pane_id: str, title: str) -> None:
    # tmux select-pane -t <pane> -T <title>
    _run_tmux(["select-pane", "-t", pane_id, "-T", title], check=False)


def _load_buffer_from_text(text: str) -> str:
    """
    Load given text into a tmux buffer using a temp file.
    Returns the buffer name.
    """
    import uuid
    bufname = f"aiteam_{uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as tf:
        tf.write(text)
        tf.flush()
        tmp_path = tf.name

    try:
        _run_tmux(["load-buffer", "-b", bufname, tmp_path])
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return bufname


def paste_text(pane_id: str, text: str, *, enter: bool = True) -> None:
    """
    Paste text into a pane. This supports multiline text robustly.

    If enter=True, also sends Enter after pasting.
    """
    bufname = _load_buffer_from_text(text)
    try:
        _run_tmux(["paste-buffer", "-b", bufname, "-t", pane_id])
    finally:
        _run_tmux(["delete-buffer", "-b", bufname], check=False)

    if enter:
        # C-m == Enter
        _run_tmux(["send-keys", "-t", pane_id, "C-m"])


def send_keys(pane_id: str, keys: List[str]) -> None:
    _run_tmux(["send-keys", "-t", pane_id, *keys])


def capture_pane(pane_id: str, *, lines: int = 200) -> str:
    # -S -N means "start from N lines up from the bottom"
    # Use check=False so we still get partial output even if tmux complains.
    start = f"-{max(1, int(lines))}"
    cp = _run_tmux(["capture-pane", "-t", pane_id, "-p", "-S", start], check=True)
    return cp.stdout or ""


def attach(session: str) -> None:
    """
    Replace current process with `tmux attach -t <session>` for interactive use.
    """
    os.execvp("tmux", ["tmux", "attach", "-t", session])
