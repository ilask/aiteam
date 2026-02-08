from __future__ import annotations

import argparse
import json
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import traceback
from typing import List, Tuple, Optional
from urllib.parse import urlparse

from . import __version__
from .tmux import (
    TmuxError,
    tmux_version,
    new_session,
    split_window,
    split_from,
    select_layout_tiled,
    list_panes,
    set_pane_title,
    paste_text,
    capture_pane,
    attach as tmux_attach,
    kill_session,
    list_sessions,
    session_exists,
    set_session_option,
    get_session_option,
    set_hook,
    current_session_name,
    current_pane_id,
    pane_current_path,
    select_pane,
)


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


# Last error message (used to seed the auto error-analyzer Codex pane).
_LAST_ERROR: Optional[str] = None


def _set_last_error(msg: str) -> None:
    global _LAST_ERROR
    _LAST_ERROR = msg


def _get_last_error() -> Optional[str]:
    return _LAST_ERROR


# Codex pane title format: "codex#<id>:<name>"
_CODEX_TITLE_RX = re.compile(r"^codex#(?P<id>[^:]+)(?::(?P<name>.*))?$")
_CODEX_ID_SELECTOR_RX = re.compile(r"^codex[:#](?P<id>[^:]+)$")
_DEFAULT_CODEX_PROFILE = "aiteam"
_DEFAULT_CODEX_COMMAND = f"codex -p {_DEFAULT_CODEX_PROFILE}"
_BRIEFING_OPTION = "@aiteam_briefing_file"


def _parse_codex_title(title: str) -> Optional[Tuple[str, str]]:
    """Parse a codex pane title.

    Returns (id, name). Name may be empty.
    """
    m = _CODEX_TITLE_RX.match((title or "").strip())
    if not m:
        return None
    cid = (m.group("id") or "").strip()
    name = (m.group("name") or "").strip()
    if not cid:
        return None
    return cid, name


def _list_codex_panes(session: str):
    panes = list_panes(session)
    out = []
    for p in panes:
        parsed = _parse_codex_title(p.pane_title)
        if parsed:
            cid, cname = parsed
            out.append((cid, cname, p))
    return out


def _next_codex_numeric_id(session: str) -> str:
    """Allocate the next numeric Codex id in a session ("1", "2", ...)."""
    nums: List[int] = []
    for cid, _cname, _p in _list_codex_panes(session):
        if cid.isdigit():
            try:
                nums.append(int(cid))
            except Exception:
                pass
    return str(max(nums) + 1 if nums else 1)


def _next_prefixed_codex_id(session: str, prefix: str) -> str:
    """Allocate the next prefixed Codex id, e.g. prefix='err' => err1, err2..."""
    max_n = 0
    for cid, _cname, _p in _list_codex_panes(session):
        if cid.startswith(prefix) and cid[len(prefix):].isdigit():
            try:
                max_n = max(max_n, int(cid[len(prefix):]))
            except Exception:
                pass
    return f"{prefix}{max_n + 1}"


def _sanitize_session_name(raw: str) -> str:
    """Sanitize a string into a tmux session-name-friendly token."""
    s = (raw or "").strip()
    if not s:
        return "ai-team"
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[/:\\]+", "-", s)
    s = re.sub(r"[^\w-]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "ai-team"


def _git_toplevel(cwd: str) -> Optional[str]:
    cp = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        return None
    top = (cp.stdout or "").strip()
    if not top:
        return None
    return top


def _repo_name_from_remote_url(url: str) -> Optional[str]:
    u = (url or "").strip()
    if not u:
        return None

    if "://" in u:
        parsed = urlparse(u)
        path = (parsed.path or "").strip()
        name = os.path.basename(path.rstrip("/"))
    else:
        # SCP-like URL: git@host:owner/repo.git
        if ":" in u and not u.startswith("/"):
            path = u.split(":", 1)[1]
            name = os.path.basename(path.rstrip("/"))
        else:
            name = os.path.basename(u.rstrip("/"))

    if name.endswith(".git"):
        name = name[:-4]
    name = name.strip()
    return name or None


def _git_remote_names(cwd: str) -> List[str]:
    cp = subprocess.run(
        ["git", "-C", cwd, "remote"],
        check=False,
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        return []
    remotes = [(line or "").strip() for line in (cp.stdout or "").splitlines()]
    remotes = [r for r in remotes if r]
    return remotes


def _remote_priority_key(name: str) -> Tuple[int, str]:
    if name == "origin":
        return (0, name)
    if name.startswith("origin"):
        return (1, name)
    return (2, name)


def _git_repo_name(cwd: str) -> Optional[str]:
    """Return preferred git repo name for cwd.

    Priority:
      1) remote named "origin"
      2) remotes starting with "origin" (lexicographic)
      3) all other remotes (lexicographic)
      4) local top-level directory name
    """
    remotes = sorted(_git_remote_names(cwd), key=_remote_priority_key)
    for remote in remotes:
        cp = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", remote],
            check=False,
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            continue
        name = _repo_name_from_remote_url((cp.stdout or "").strip())
        if name:
            return name

    top = _git_toplevel(cwd)
    if not top:
        return None
    return os.path.basename(top.rstrip("/\\")) or None


def _next_available_session_name(base: str) -> str:
    """Return base, or base-2/base-3... if the session already exists."""
    if not session_exists(base):
        return base
    n = 2
    while True:
        candidate = f"{base}-{n}"
        if not session_exists(candidate):
            return candidate
        n += 1


def _resolve_new_session_name(*, requested: Optional[str], cwd: str) -> Tuple[str, bool]:
    """Resolve session name for commands that create a new session.

    Returns (session_name, is_auto).
    """
    req = (requested or "").strip()
    if req:
        return req, False

    repo = _git_repo_name(cwd)
    base = _sanitize_session_name(repo) if repo else "ai-team"
    return _next_available_session_name(base), True


def _create_briefing_file(*, session: str, cwd: str) -> str:
    safe = _sanitize_session_name(session)
    fd, path = tempfile.mkstemp(prefix=f"aiteam_briefing_{safe}_", suffix=".md")
    os.close(fd)

    text = (
        "AITEAM SESSION BRIEFING (ephemeral)\n"
        "\n"
        "This text is pasted into each new Codex pane in this tmux session.\n"
        "It is deleted automatically when the tmux session closes.\n"
        "\n"
        f"Session: {session}\n"
        f"Workdir: {cwd}\n"
        "\n"
        "Instructions:\n"
        "\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _edit_file(path: str) -> None:
    editor = (os.environ.get("AITEAM_EDITOR") or os.environ.get("EDITOR") or "").strip()
    if not editor:
        editor = "nano"
    cmd = shlex.split(editor) + [path]
    cp = subprocess.run(cmd, check=False)
    if cp.returncode != 0:
        raise TmuxError(f"Editor exited with non-zero status {cp.returncode}: {' '.join(cmd)}")


def _install_session_briefing(session: str, path: str) -> None:
    set_session_option(session, _BRIEFING_OPTION, path)
    cleanup_cmd = f"run-shell \"rm -f -- {shlex.quote(path)}\""
    set_hook(session, "session-closed", cleanup_cmd)


def _load_session_briefing_text(session: str) -> Optional[str]:
    path = get_session_option(session, _BRIEFING_OPTION)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    text = (text or "").strip()
    return text or None


def _is_codex_command(command: str) -> bool:
    s = (command or "").strip()
    if not s:
        return False
    try:
        parts = shlex.split(s, posix=True)
    except Exception:
        parts = s.split()
    if not parts:
        return False
    i = 0
    # Skip leading VAR=VAL style env assignments.
    while i < len(parts) and ("=" in parts[i] and not parts[i].startswith("-")):
        i += 1
    if i >= len(parts):
        return False
    return os.path.basename(parts[i]) == "codex"


def _maybe_paste_briefing(*, session: str, pane_id: str, command: str) -> None:
    if not _is_codex_command(command):
        return
    text = _load_session_briefing_text(session)
    if not text:
        return
    time.sleep(0.8)
    paste_text(pane_id, text, enter=True)


def _strict_short_flag(long_flag: str) -> str:
    """Return strict short flag derived from the first alnum in the long flag."""
    name = (long_flag or "").strip().lstrip("-")
    for ch in name:
        if ch.isalnum():
            return f"-{ch.lower()}"
    raise ValueError(f"Unable to derive a short option from '{long_flag}'")


def _pick_short_flag(parser: argparse.ArgumentParser, long_flag: str) -> str:
    """Pick strict short flag for `long_flag` in `parser`, or raise on conflict."""
    used = set()
    for action in parser._actions:
        for opt in action.option_strings:
            if opt.startswith("-") and not opt.startswith("--"):
                used.add(opt)

    candidate = _strict_short_flag(long_flag)
    if candidate in used:
        raise ValueError(
            f"Short option collision in parser '{parser.prog}': "
            f"{candidate} already exists; rename option '{long_flag}' to keep unique initials."
        )
    return candidate


def _patch_container_add_argument(container, parser: argparse.ArgumentParser) -> None:
    """Patch add_argument on a parser/group to auto-attach short flags."""
    if getattr(container, "_aiteam_auto_short_wrapped", False):
        return

    original_add_argument = container.add_argument

    def add_argument_with_auto_short(*name_or_flags, **kwargs):
        flags = list(name_or_flags)
        has_long = any(isinstance(f, str) and f.startswith("--") for f in flags)
        has_short = any(isinstance(f, str) and f.startswith("-") and not f.startswith("--") for f in flags)

        if has_long and not has_short:
            first_long = next(f for f in flags if isinstance(f, str) and f.startswith("--"))
            short = _pick_short_flag(parser, first_long)
            flags = [short, *flags]
        elif has_long and has_short:
            first_long = next(f for f in flags if isinstance(f, str) and f.startswith("--"))
            first_short = next(f for f in flags if isinstance(f, str) and f.startswith("-") and not f.startswith("--"))
            expected = _strict_short_flag(first_long)
            if first_short != expected:
                raise ValueError(
                    f"Invalid short option for '{first_long}' in parser '{parser.prog}': "
                    f"expected '{expected}', got '{first_short}'."
                )

        return original_add_argument(*flags, **kwargs)

    container.add_argument = add_argument_with_auto_short
    setattr(container, "_aiteam_auto_short_wrapped", True)


def _enable_auto_short_options(parser: argparse.ArgumentParser) -> None:
    """Enable automatic short option generation for a parser and its groups."""
    if getattr(parser, "_aiteam_auto_short_enabled", False):
        return

    _patch_container_add_argument(parser, parser)

    original_add_mutually_exclusive_group = parser.add_mutually_exclusive_group
    original_add_argument_group = parser.add_argument_group

    def add_mutually_exclusive_group_with_auto(*args, **kwargs):
        group = original_add_mutually_exclusive_group(*args, **kwargs)
        _patch_container_add_argument(group, parser)
        return group

    def add_argument_group_with_auto(*args, **kwargs):
        group = original_add_argument_group(*args, **kwargs)
        _patch_container_add_argument(group, parser)
        return group

    parser.add_mutually_exclusive_group = add_mutually_exclusive_group_with_auto
    parser.add_argument_group = add_argument_group_with_auto

    setattr(parser, "_aiteam_auto_short_enabled", True)


def _parse_agents(agent_args: List[str]) -> List[Tuple[str, str]]:
    """
    Parse ["name=command", ...] into [(name, command), ...].
    """
    agents: List[Tuple[str, str]] = []
    for item in agent_args:
        if "=" not in item:
            raise ValueError(f"Invalid --worker value (expected name=command): {item}")
        name, cmd = item.split("=", 1)
        name = name.strip()
        cmd = cmd.strip()
        if not name:
            raise ValueError(f"Invalid agent name in: {item}")
        if not cmd:
            raise ValueError(f"Invalid agent command in: {item} (empty command)")
        agents.append((name, cmd))
    return agents


def _find_pane(session: str, selector: str) -> str:
    """
    selector can be:
      - a pane index (e.g. "0", "1")
      - a pane title (agent name), exact match
      - a codex id selector: "codex:<id>" or "codex#<id>" (matches pane title "codex#<id>:<name>")
    Returns the pane_id.
    """
    panes = list_panes(session)

    # Codex id selector: codex:<id>
    m = _CODEX_ID_SELECTOR_RX.match(selector.strip())
    if m:
        cid = (m.group("id") or "").strip()
        matches = []
        for _cid, _cname, p in _list_codex_panes(session):
            if _cid == cid:
                matches.append(p)
        if matches:
            # IDs are intended to be unique.
            return matches[0].pane_id
        available_ids = ", ".join([c for c, _, _ in _list_codex_panes(session)])
        raise TmuxError(f"No Codex pane with id '{cid}' in session {session}. Available Codex ids: {available_ids or '(none)'}")
    # Try numeric index first
    if selector.isdigit():
        idx = int(selector)
        for p in panes:
            if p.pane_index == idx:
                return p.pane_id
        raise TmuxError(f"No pane with index {idx} in session {session}")

    # Exact title match (case-sensitive)
    for p in panes:
        if p.pane_title == selector:
            return p.pane_id

    # Back-compat / convenience: selector 'codex' can target a single codex instance.
    if selector == "codex":
        codexes = _list_codex_panes(session)
        if len(codexes) == 1:
            return codexes[0][2].pane_id
        if len(codexes) > 1:
            available = ", ".join([f"codex:{cid}({cname or 'no-name'})" for cid, cname, _ in codexes])
            raise TmuxError(
                "Multiple Codex panes exist. Please target one by id, e.g. --to codex:1\n"
                f"Available: {available}"
            )

    # Fallback: case-insensitive match
    low = selector.lower()
    for p in panes:
        if p.pane_title.lower() == low:
            return p.pane_id

    available = ", ".join([f"{p.pane_index}:{p.pane_title or '(no-title)'}" for p in panes])
    raise TmuxError(f"Pane not found: {selector}. Available: {available}")


def cmd_spawn(args: argparse.Namespace) -> int:
    agents = args.agent
    if not agents:
        agents = ["claude=claude", f"codex={_DEFAULT_CODEX_COMMAND}"]

    try:
        agent_pairs = _parse_agents(agents)
    except ValueError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 2

    n = len(agent_pairs)
    if n < 1:
        _eprint("No agents specified.")
        return 2

    cwd = args.cwd or os.getcwd()
    session, auto_session = _resolve_new_session_name(
        requested=getattr(args, "session", None),
        cwd=cwd,
    )
    briefing_path: Optional[str] = None
    session_created = False

    try:
        if getattr(args, "briefing", False):
            briefing_path = _create_briefing_file(session=session, cwd=cwd)
            _edit_file(briefing_path)

        _eprint(f"tmux: {tmux_version()}")
        if auto_session:
            _eprint(f"session(auto): {session}")
        new_session(session, cwd=cwd, force=args.force)
        session_created = True
        if briefing_path:
            _install_session_briefing(session, briefing_path)

        # Create panes
        if n == 1:
            pass
        elif n == 2:
            vertical = (args.layout == "vertical")
            split_window(session, cwd=cwd, vertical=vertical)
        else:
            # Create N-1 splits, then tile.
            # Alternate split direction to reduce extreme aspect ratios.
            vertical = True
            for _ in range(n - 1):
                split_window(session, cwd=cwd, vertical=vertical)
                vertical = not vertical
            select_layout_tiled(session)

        # Set titles + run commands
        panes = list_panes(session)
        if len(panes) != n:
            # This can happen with older tmux quirks; still proceed best-effort.
            _eprint(f"Warning: expected {n} panes but found {len(panes)} panes. Mapping will be best-effort.")

        for i, (name, command) in enumerate(agent_pairs):
            if i >= len(panes):
                break
            pane_id = panes[i].pane_id
            set_pane_title(pane_id, name)
            # Run agent command
            paste_text(pane_id, command, enter=True)
            _maybe_paste_briefing(session=session, pane_id=pane_id, command=command)

        if args.attach:
            tmux_attach(session)
        return 0

    except TmuxError as e:
        if briefing_path and not session_created:
            try:
                os.unlink(briefing_path)
            except Exception:
                pass
        _set_last_error(str(e))
        _eprint(str(e))
        return 1





def cmd_start(args: argparse.Namespace) -> int:
    """Create a tmux session with a single *main* agent pane.

    This is a convenience for WSL/terminal workflows where you want:
      - 1x main agent (Claude Code, Cursor CLI, or Codex)
      - spawn Codex panes later via `aiteam codex ...`

    Examples:
      aiteam start --main claude --attach
      aiteam start --main cursor --attach
      aiteam start --main codex --attach
      aiteam start --main custom --exec "agent" --title cursor --attach
    """
    main = (getattr(args, "main", None) or "claude").strip().lower()
    cmd = (getattr(args, "command", None) or "").strip() or None
    title = (getattr(args, "title", None) or "").strip() or None

    # Defaults
    if main == "claude":
        if cmd is None:
            cmd = "claude"
        if title is None:
            title = "claude"
    elif main == "cursor":
        # Cursor CLI's landing page shows the primary command as `agent`.
        # Users can still override this with --exec.
        if cmd is None:
            cmd = "agent"
        if title is None:
            title = "cursor"
    elif main == "codex":
        if cmd is None:
            cmd = _DEFAULT_CODEX_COMMAND
        if title is None:
            title = "codex"
    else:
        # custom
        if cmd is None:
            raise TmuxError("For --main custom, you must provide --exec.")
        if title is None:
            title = "main"

    cwd = args.cwd or os.getcwd()
    session, auto_session = _resolve_new_session_name(
        requested=getattr(args, "session", None),
        cwd=cwd,
    )
    briefing_path: Optional[str] = None
    session_created = False

    try:
        if getattr(args, "briefing", False):
            briefing_path = _create_briefing_file(session=session, cwd=cwd)
            _edit_file(briefing_path)

        _eprint(f"tmux: {tmux_version()}")
        if auto_session:
            _eprint(f"session(auto): {session}")
        new_session(session, cwd=cwd, force=args.force)
        session_created = True
        if briefing_path:
            _install_session_briefing(session, briefing_path)

        panes = list_panes(session)
        if not panes:
            raise TmuxError(f"No panes found in session '{session}' after creating it.")
        pane_id = panes[0].pane_id
        set_pane_title(pane_id, title)
        paste_text(pane_id, cmd, enter=True)
        _maybe_paste_briefing(session=session, pane_id=pane_id, command=cmd)

        if args.attach:
            tmux_attach(session)
        return 0
    except TmuxError as e:
        if briefing_path and not session_created:
            try:
                os.unlink(briefing_path)
            except Exception:
                pass
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def _resolve_session(session: Optional[str]) -> str:
    """Resolve the tmux session name.

    If session is provided, return it.
    Otherwise, try to detect the current session (requires running inside tmux).
    """
    if session:
        return session
    try:
        return current_session_name()
    except Exception as e:
        raise TmuxError("No --session provided and the current tmux session could not be detected. Run inside tmux or pass --session.") from e


def cmd_add(args: argparse.Namespace) -> int:
    """Add a single agent pane to an existing session.

    This is the building block for "Claude (one) -> spawn Codex from Claude" workflows.
    """
    try:
        session = _resolve_session(getattr(args, "session", None))

        # Determine agent (name + command)
        name: Optional[str] = getattr(args, "name", None)
        command: Optional[str] = getattr(args, "command", None)
        agent_arg: Optional[str] = getattr(args, "agent", None)

        if agent_arg:
            pairs = _parse_agents([agent_arg])
            name, command = pairs[0]
        if not name or not command:
            raise TmuxError("Agent not specified. Use --worker name=command or --name/--exec.")

        # If the agent pane already exists, decide what to do.
        panes = list_panes(session)
        existing = [p for p in panes if p.pane_title == name]
        if existing:
            mode = getattr(args, "if_exists", "skip")
            if mode == "skip":
                if getattr(args, "quiet", False) is not True:
                    _eprint(f"Pane '{name}' already exists in session '{session}' (skip).")
                return 0
            raise TmuxError(f"Pane '{name}' already exists in session '{session}'.")

        # Figure out where to split from.
        split_from_selector: Optional[str] = getattr(args, "split_from", None)

        orig_pane: Optional[str] = None
        try:
            orig_pane = current_pane_id()
        except Exception:
            orig_pane = None

        if split_from_selector:
            # User supplied a pane selector within the session.
            split_target = _find_pane(session, split_from_selector)
        else:
            # Default: split from the current pane if possible, else from pane 0.
            if orig_pane:
                split_target = orig_pane
            else:
                panes = list_panes(session)
                if not panes:
                    raise TmuxError(f"No panes found in session '{session}'.")
                split_target = panes[0].pane_id

        # Determine working directory for the new pane.
        cwd = getattr(args, "cwd", None)
        if cwd is None:
            # Prefer the caller's current directory when available.
            try:
                cwd = os.getcwd()
            except Exception:
                # Fallback: use tmux-reported path from the split target pane.
                try:
                    cwd = pane_current_path(split_target)
                except Exception:
                    cwd = None

        # Perform the split.
        layout = getattr(args, "layout", "vertical")
        vertical = (layout == "vertical")

        before = {p.pane_id for p in list_panes(session)}
        split_from(split_target, cwd=cwd, vertical=vertical)

        # Identify the new pane.
        new_pane: Optional[str] = None
        try:
            new_pane = current_pane_id()
        except Exception:
            new_panes = {p.pane_id for p in list_panes(session)} - before
            if len(new_panes) == 1:
                new_pane = next(iter(new_panes))
            elif len(new_panes) > 1:
                # Best-effort: pick the highest pane index
                panes_after = list_panes(session)
                panes_after.sort(key=lambda p: p.pane_index)
                for p in reversed(panes_after):
                    if p.pane_id in new_panes:
                        new_pane = p.pane_id
                        break

        if not new_pane:
            raise TmuxError("Failed to determine the new pane id after splitting.")

        # Configure pane + start agent.
        set_pane_title(new_pane, name)
        paste_text(new_pane, command, enter=True)
        _maybe_paste_briefing(session=session, pane_id=new_pane, command=command)

        # Optional tiling for 3+ panes.
        if layout == "tiled" or getattr(args, "tiled", False):
            select_layout_tiled(session)

        # Return focus to the original pane (default).
        focus = getattr(args, "focus", "stay")
        if focus == "stay" and orig_pane:
            select_pane(orig_pane)

        return 0

    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def cmd_codex(args: argparse.Namespace) -> int:
    """Start a new Codex instance in a new pane.

    Supports multiple Codex panes. Each Codex pane gets:
      - an id (unique within the tmux session)
      - a human-friendly name/label

    Pane title format: codex#<id>:<name>
    You can target it later via selectors like: codex:<id>

    Designed to be run from inside the Claude Code pane, but works as long as tmux can reach the session.
    """
    try:
        session = _resolve_session(getattr(args, "session", None))

        # Determine id
        requested_id = (getattr(args, "id", None) or "").strip() or None
        if requested_id is None:
            cid = _next_codex_numeric_id(session)
        else:
            cid = requested_id

        # Determine name label
        label = (getattr(args, "name", None) or "").strip() or "codex"

        # Ensure id uniqueness within the session
        existing_ids = {existing_id for existing_id, _cname, _p in _list_codex_panes(session)}
        if cid in existing_ids:
            mode = getattr(args, "if_exists", "error")
            if mode == "skip":
                if not getattr(args, "quiet", False):
                    _eprint(f"Codex id '{cid}' already exists (skip). Use codex:{cid} to target it.")
                return 0
            raise TmuxError(
                f"Codex id '{cid}' already exists in session '{session}'. "
                f"Pick another --id or omit --id to auto-allocate."
            )

        title = f"codex#{cid}:{label}"

        # Reuse cmd_add implementation by mapping args -> add args
        add_args = argparse.Namespace(**vars(args))
        setattr(add_args, "agent", None)
        setattr(add_args, "name", title)
        setattr(add_args, "command", getattr(args, "command", _DEFAULT_CODEX_COMMAND))
        # For Codex instances, pane-title collisions should be treated as errors.
        setattr(add_args, "if_exists", "error")

        rc = cmd_add(add_args)
        if rc == 0:
            selector = f"codex:{cid}"
            # Human-friendly notice on stderr (unless --quiet)
            if not getattr(args, "quiet", False):
                _eprint(f"Started Codex: id={cid} name={label} (target selector: {selector})")

            # Machine-friendly return value on stdout (enabled by default)
            print_json = bool(getattr(args, "json", False))
            print_selector = bool(getattr(args, "print_selector", True))
            if print_json:
                print(json.dumps({
                    "id": cid,
                    "name": label,
                    "selector": selector,
                    "pane_title": title,
                    "session": session,
                }, ensure_ascii=False))
            elif print_selector:
                print(selector)
        return rc

    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1

def cmd_attach(args: argparse.Namespace) -> int:
    try:
        tmux_attach(args.session)
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def _read_text_input(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.file is not None:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    if args.stdin:
        return sys.stdin.read()
    raise TmuxError("No input text provided. Use --body, --file, or --pipe.")


def cmd_send(args: argparse.Namespace) -> int:
    try:
        target_pane = _find_pane(args.session, args.to)
        text = _read_text_input(args)
        paste_text(target_pane, text, enter=(not args.no_enter))
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        pane_id = _find_pane(args.session, args.from_pane)
        out = capture_pane(pane_id, lines=args.lines)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out)
        else:
            sys.stdout.write(out)
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def cmd_handoff(args: argparse.Namespace) -> int:
    try:
        from_id = _find_pane(args.session, args.from_pane)
        to_id = _find_pane(args.session, args.to_pane)
        captured = capture_pane(from_id, lines=args.lines).rstrip()

        header = args.header
        if header is None:
            header = f"Handoff from {args.from_pane}:"

        message = (
            f"{header}\n"
            f"----- BEGIN CAPTURE ({args.lines} lines) -----\n"
            f"{captured}\n"
            f"----- END CAPTURE -----\n"
        )

        paste_text(to_id, message, enter=(not args.no_enter))
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    try:
        sessions = list_sessions()
        if args.filter:
            sessions = [s for s in sessions if args.filter in s]
        for s in sessions:
            print(s)
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def cmd_kill(args: argparse.Namespace) -> int:
    try:
        briefing_path = get_session_option(args.session, _BRIEFING_OPTION)
        kill_session(args.session)
        if briefing_path:
            try:
                os.unlink(briefing_path)
            except Exception:
                pass
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        print(f"tmux-ai-team-tool {__version__}")
        print(f"tmux: {tmux_version()}")
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def cmd_relay(args: argparse.Namespace) -> int:
    """Continuously watch a pane and "push" extracted messages into another pane.

    This enables agent-to-agent push communication when an agent is instructed to
    output a specific marker block or pattern.
    """
    try:
        src_id = _find_pane(args.session, args.from_pane)
        dst_id = _find_pane(args.session, args.to_pane)

        lines = int(args.lines)
        interval = float(args.interval)
        ttl = float(args.dedupe_ttl)
        max_sends = int(args.max_sends)
        sent_count = 0

        # Extraction strategy
        if args.pattern:
            flags = re.MULTILINE
            rx = re.compile(args.pattern, flags)

            def extract_messages(text: str) -> List[str]:
                msgs: List[str] = []
                for m in rx.finditer(text):
                    if args.group is not None:
                        try:
                            msgs.append(m.group(int(args.group)))
                        except Exception:
                            msgs.append(m.group(0))
                    else:
                        # If there is at least one capture group, prefer group 1.
                        if m.lastindex and m.lastindex >= 1:
                            msgs.append(m.group(1))
                        else:
                            msgs.append(m.group(0))
                return msgs

        else:
            begin = args.begin
            end = args.end
            if begin == "" or end == "":
                raise TmuxError("--begin/--end must be non-empty (or use --regex).")
            rx = re.compile(re.escape(begin) + r"(.*?)" + re.escape(end), re.DOTALL)

            def extract_messages(text: str) -> List[str]:
                msgs: List[str] = []
                for m in rx.finditer(text):
                    if args.keep_markers:
                        msgs.append(m.group(0))
                    else:
                        msgs.append(m.group(1))
                return msgs

        # Dedup cache (hash -> last_seen_time)
        seen: dict[str, float] = {}

        # Initial snapshot: seed cache with existing matches to avoid relaying old blocks.
        initial = capture_pane(src_id, lines=lines)
        initial_msgs = extract_messages(initial)
        for msg in initial_msgs:
            h = _sha(msg.strip())
            if h:
                seen[h] = time.time()

        while True:
            time.sleep(max(0.1, interval))
            snapshot = capture_pane(src_id, lines=lines)
            now = time.time()

            # Evict old hashes to keep memory bounded.
            if ttl > 0:
                for h, ts in list(seen.items()):
                    if now - ts > ttl:
                        del seen[h]

            for msg in extract_messages(snapshot):
                normalized = msg.strip("\n")
                if not normalized.strip():
                    continue
                h = _sha(normalized.strip())
                if not h or h in seen:
                    continue
                seen[h] = now

                out_msg = normalized
                if args.prefix:
                    out_msg = f"{args.prefix}\n{out_msg}"
                if args.header:
                    out_msg = f"{args.header}\n{out_msg}"

                if args.dry_run:
                    sys.stdout.write(out_msg + "\n")
                else:
                    paste_text(dst_id, out_msg, enter=(not args.no_enter))

                sent_count += 1
                if args.verbose:
                    _eprint(f"Relayed 1 message ({len(out_msg)} chars): {args.from_pane} -> {args.to_pane}")

                if args.once or (max_sends > 0 and sent_count >= max_sends):
                    return 0

    except KeyboardInterrupt:
        return 0
    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1


_ERROR_ANALYZER_GUARD = False


def _error_codex_already_running(session: str) -> bool:
    for cid, cname, _p in _list_codex_panes(session):
        if cname in {"error", "error-analyzer", "error_analysis", "erroranalysis"}:
            return True
        if cid.startswith("err"):
            return True
    return False


def _build_error_analyzer_prompt(*, error_text: str, argv: List[str], session: str) -> str:
    # Keep it reasonably short.
    max_chars = 8000
    err = (error_text or "").strip()
    if len(err) > max_chars:
        err = err[:max_chars] + "\n... (truncated)"

    panes = list_panes(session)
    pane_summary = "\n".join([f"- {p.pane_index}: {p.pane_title or '(no-title)'} ({p.pane_id})" for p in panes])

    return (
        "You are Codex running as an automated *error analysis* agent for the aiteam tmux controller.\n"
        "Goal: explain why the command failed and propose a concrete workaround or fix.\n\n"
        f"aiteam version: {__version__}\n"
        f"tmux version: {tmux_version()}\n"
        f"tmux session: {session}\n"
        f"command: {' '.join(argv)}\n\n"
        "tmux panes:\n"
        f"{pane_summary}\n\n"
        "error:\n"
        "-----\n"
        f"{err}\n"
        "-----\n\n"
        "Please respond with:\n"
        "1) Likely root cause (1-3 bullet points)\n"
        "2) Fast workaround steps\n"
        "3) If this looks like an aiteam bug, propose a minimal patch (file + code snippet)\n"
    )


def _auto_start_error_analyzer_codex(args: argparse.Namespace, *, error_text: str) -> None:
    """Best-effort: if aiteam fails inside tmux, spin up a dedicated Codex pane to analyze the error."""
    global _ERROR_ANALYZER_GUARD
    if _ERROR_ANALYZER_GUARD:
        return

    if getattr(args, "no_error_codex", False):
        return
    if os.environ.get("AITEAM_DISABLE_ERROR_CODEX", "").strip() in {"1", "true", "yes"}:
        return

    # Only trigger on "control" errors (exit code 1). Don't launch a Codex just for argument mistakes.
    if getattr(args, "_exit_code", None) not in (None, 1):
        return

    try:
        _ERROR_ANALYZER_GUARD = True

        # Need a session to attach the pane to.
        session_hint = getattr(args, "session", None)
        try:
            session = _resolve_session(session_hint)
        except Exception:
            return

        # If tmux itself isn't available, there's nothing we can do.
        try:
            _ = tmux_version()
        except Exception:
            return

        # Avoid spawning multiple error analyzers.
        if _error_codex_already_running(session):
            return

        cid = _next_prefixed_codex_id(session, "err")
        title = f"codex#{cid}:error"

        # Split from current pane if possible; otherwise split from the first pane in the session.
        orig_pane: Optional[str] = None
        try:
            orig_pane = current_pane_id()
            split_target = orig_pane
        except Exception:
            panes = list_panes(session)
            if not panes:
                return
            split_target = panes[0].pane_id

        try:
            cwd = pane_current_path(split_target)
        except Exception:
            cwd = os.getcwd()

        before = {p.pane_id for p in list_panes(session)}
        split_from(split_target, cwd=cwd, vertical=True)

        # Identify new pane
        new_pane_id: Optional[str] = None
        after = list_panes(session)
        new_panes = [p for p in after if p.pane_id not in before]
        if len(new_panes) == 1:
            new_pane_id = new_panes[0].pane_id
        elif len(new_panes) > 1:
            # Pick the highest pane index as best-effort.
            new_panes.sort(key=lambda p: p.pane_index)
            new_pane_id = new_panes[-1].pane_id
        else:
            try:
                new_pane_id = current_pane_id()
            except Exception:
                return

        set_pane_title(new_pane_id, title)

        # Start Codex and feed it the prompt.
        paste_text(new_pane_id, _DEFAULT_CODEX_COMMAND, enter=True)
        time.sleep(0.6)

        prompt = _build_error_analyzer_prompt(
            error_text=error_text,
            argv=["aiteam", *getattr(args, "_argv", [])],
            session=session,
        )
        paste_text(new_pane_id, prompt, enter=True)

        # Make things visible when panes grow.
        select_layout_tiled(session)

        # Return focus to where the user was.
        if orig_pane:
            select_pane(orig_pane)

        _eprint(f"Auto-started error-analyzer Codex: codex:{cid} (pane title: {title})")
    finally:
        _ERROR_ANALYZER_GUARD = False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiteam", description="A lightweight tmux helper for multi-agent CLI collaboration.")
    _enable_auto_short_options(p)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--no-error-codex",
        action="store_true",
        help="Disable auto-starting an error-analyzer Codex pane when aiteam encounters a tmux/control error.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    original_add_parser = sub.add_parser

    def add_parser_with_auto_short(*args, **kwargs):
        sp = original_add_parser(*args, **kwargs)
        _enable_auto_short_options(sp)
        return sp

    sub.add_parser = add_parser_with_auto_short

    sp = sub.add_parser("spawn", help="Create a tmux session, split panes, and start agent commands.")
    sp.add_argument(
        "--session",
        default=None,
        help="tmux session name (default: auto from git repo name, preferring remote names; with -2/-3... on conflicts; fallback: ai-team)",
    )
    sp.add_argument("--cwd", default=None, help="Working directory for panes (default: current directory)")
    sp.add_argument(
        "--briefing",
        action="store_true",
        help="Open an editor to create an ephemeral session briefing (pasted into new Codex panes).",
    )
    sp.add_argument("--layout", choices=["vertical", "horizontal", "tiled"], default="vertical",
                    help="Pane split layout for 2 agents. For 3+ agents, layout becomes tiled. (default: vertical)")
    sp.add_argument("--worker", dest="agent", action="append", default=[], help="Worker definition: name=command (repeatable)")
    sp.add_argument("--force", action="store_true", help="Replace session if it already exists")
    sp.add_argument("--attach", action="store_true", help="Attach after spawning")
    sp.set_defaults(func=cmd_spawn)

    sp = sub.add_parser("start", help="Create a tmux session with a single main agent pane (Claude/Cursor/Codex).")
    sp.add_argument(
        "--session",
        default=None,
        help="tmux session name (default: auto from git repo name, preferring remote names; with -2/-3... on conflicts; fallback: ai-team)",
    )
    sp.add_argument("--cwd", default=None, help="Working directory for the session (default: current directory)")
    sp.add_argument(
        "--briefing",
        action="store_true",
        help="Open an editor to create an ephemeral session briefing (pasted into new Codex panes).",
    )
    sp.add_argument("--main", choices=["claude", "cursor", "codex", "custom"], default="claude", help="Which main agent to start (default: claude)")
    sp.add_argument("--exec", dest="command", default=None, help="Command to start the main agent (overrides the default for --main)")
    sp.add_argument("--title", default=None, help="Pane title for the main agent (default: claude/cursor/codex/main)")
    sp.add_argument("--force", action="store_true", help="Replace session if it already exists")
    sp.add_argument("--attach", action="store_true", help="Attach after starting")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser(
        "add",
        help="Add a new agent pane to an existing session (split from the current pane if inside tmux).",
    )
    sp.add_argument("--session", default=None, help="tmux session name (default: current session if inside tmux)")
    sp.add_argument("--worker", dest="agent", default=None, help="Worker definition: name=command (alternative to --name/--exec)")
    sp.add_argument("--name", default=None, help="Agent name (pane title)")
    sp.add_argument("--exec", dest="command", default=None, help="Command to run in the new pane")
    sp.add_argument("--cwd", default=None, help="Working directory for the new pane (default: current directory)")
    sp.add_argument(
        "--layout",
        choices=["vertical", "horizontal"],
        default="vertical",
        help="Split layout (default: vertical)",
    )
    sp.add_argument("--tiled", action="store_true", help="After adding, apply tmux tiled layout")
    sp.add_argument(
        "--base-pane",
        dest="split_from",
        default=None,
        help="Pane selector to split from (agent name or pane index). Default: current pane.",
    )
    sp.add_argument(
        "--if-duplicate",
        dest="if_exists",
        choices=["skip", "error"],
        default="skip",
        help="If a pane with the same title already exists: skip or error (default: skip)",
    )
    sp.add_argument(
        "--focus",
        choices=["stay", "new"],
        default="stay",
        help="Where to leave focus after adding: stay (back to original) or new (new pane) (default: stay)",
    )
    sp.add_argument("--quiet", action="store_true", help="Reduce stderr output")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser(
        "codex",
        help="Start a new Codex instance in a new pane (multiple Codex panes supported).",
    )
    sp.add_argument("--session", default=None, help="tmux session name (default: current session if inside tmux)")
    sp.add_argument(
        "--id",
        default=None,
        help="Codex instance id (unique within session). If omitted, auto-allocates a numeric id.",
    )
    sp.add_argument("--name", default="codex", help="Codex instance label (shown in pane title).")
    sp.add_argument("--exec", dest="command", default=_DEFAULT_CODEX_COMMAND, help=f"Command to start Codex (default: {_DEFAULT_CODEX_COMMAND})")
    sp.add_argument("--cwd", default=None, help="Working directory for the new pane (default: current directory)")
    sp.add_argument(
        "--layout",
        choices=["vertical", "horizontal"],
        default="vertical",
        help="Split layout (default: vertical)",
    )
    sp.add_argument("--tiled", action="store_true", help="After adding, apply tmux tiled layout")
    sp.add_argument(
        "--base-pane",
        dest="split_from",
        default=None,
        help="Pane selector to split from (agent name or pane index). Default: current pane.",
    )
    sp.add_argument(
        "--policy",
        dest="if_exists",
        choices=["skip", "error"],
        default="error",
        help="If the requested --id already exists: skip or error (default: error)",
    )
    sp.add_argument(
        "--focus",
        choices=["stay", "new"],
        default="stay",
        help="Where to leave focus after adding: stay or new (default: stay)",
    )
    sp.add_argument("--quiet", action="store_true", help="Reduce stderr output")
    sp.add_argument(
        "--omit-selector",
        dest="print_selector",
        action="store_false",
        default=True,
        help="Do not print the Codex selector to stdout on success (default: prints selector).",
    )
    sp.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON object (id/name/selector/session) to stdout on success.",
    )
    sp.set_defaults(func=cmd_codex)


    sp = sub.add_parser("attach", help="Attach to a tmux session.")
    sp.add_argument("--session", required=True, help="tmux session name")
    sp.set_defaults(func=cmd_attach)

    sp = sub.add_parser("send", help="Paste text into a pane by agent name or pane index.")
    sp.add_argument("--session", required=True, help="tmux session name")
    sp.add_argument("--to", required=True, help="Target pane selector (agent name or pane index)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--body", dest="text", help="Text to send")
    g.add_argument("--file", help="Read text from file")
    g.add_argument("--pipe", dest="stdin", action="store_true", help="Read text from stdin")
    sp.add_argument("--no-enter", action="store_true", help="Do not send Enter after pasting")
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("capture", help="Capture the last N lines from a pane.")
    sp.add_argument("--session", required=True, help="tmux session name")
    sp.add_argument("--from", dest="from_pane", required=True, help="Source pane selector (agent name or pane index)")
    sp.add_argument("--lines", type=int, default=200, help="Number of lines from the bottom (default: 200)")
    sp.add_argument("--output", help="Write captured text to a file instead of stdout")
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser("handoff", help="Capture from one pane and paste into another.")
    sp.add_argument("--session", required=True, help="tmux session name")
    sp.add_argument("--from", dest="from_pane", required=True, help="Source pane selector (agent name or pane index)")
    sp.add_argument("--to", dest="to_pane", required=True, help="Destination pane selector (agent name or pane index)")
    sp.add_argument("--lines", type=int, default=120, help="Number of lines to capture (default: 120)")
    sp.add_argument("--caption", dest="header", default=None, help="Optional header line")
    sp.add_argument("--no-enter", action="store_true", help="Do not send Enter after pasting")
    sp.set_defaults(func=cmd_handoff)

    sp = sub.add_parser(
        "relay",
        help="Watch a pane for marker blocks or regex matches and push them into another pane (agent-to-agent push).",
    )
    sp.add_argument("--session", required=True, help="tmux session name")
    sp.add_argument("--from", dest="from_pane", required=True, help="Source pane selector (agent name or pane index)")
    sp.add_argument("--to", dest="to_pane", required=True, help="Destination pane selector (agent name or pane index)")
    sp.add_argument("--lines", type=int, default=2000, help="Capture window size (default: 2000 lines)")
    sp.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds (default: 1.0)")
    sp.add_argument(
        "--window-ttl",
        dest="dedupe_ttl",
        type=float,
        default=600.0,
        help="Seconds to remember already-relayed messages (default: 600). 0 disables eviction.",
    )
    sp.add_argument("--once", action="store_true", help="Exit after the first successful relay")
    sp.add_argument(
        "--max-sends",
        type=int,
        default=0,
        help="Exit after relaying N messages (0 = unlimited, default: 0)",
    )
    sp.add_argument("--no-enter", action="store_true", help="Do not send Enter after pasting")
    sp.add_argument("--caption", dest="header", default=None, help="Optional header line to prepend to each relayed message")
    sp.add_argument("--prefix", default=None, help="Optional prefix (can be multi-line) to prepend to each message")
    sp.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Do not paste into the destination pane; print relayed messages to stdout",
    )
    sp.add_argument("--verbose", action="store_true", help="Log each relay event to stderr")

    # Extraction mode
    sp.add_argument(
        "--regex",
        dest="pattern",
        default=None,
        help="Regex pattern to extract messages. If omitted, marker mode is used.",
    )
    sp.add_argument(
        "--group",
        default=None,
        help="Regex capture group number to send (default: group 1 if present, else full match)",
    )
    # Marker mode (default)
    sp.add_argument("--begin", default="[PUSH]", help="Marker begin token (default: [PUSH])")
    sp.add_argument("--end", default="[/PUSH]", help="Marker end token (default: [/PUSH])")
    sp.add_argument(
        "--keep-markers",
        action="store_true",
        help="Forward the marker tokens too (default: forward only the content between markers)",
    )

    sp.set_defaults(func=cmd_relay)

    sp = sub.add_parser("list", help="List tmux sessions (optionally filtered).")
    sp.add_argument("--filter", default=None, help="Only show sessions containing this substring")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("kill", help="Kill a tmux session.")
    sp.add_argument("--session", required=True, help="tmux session name")
    sp.set_defaults(func=cmd_kill)

    sp = sub.add_parser("doctor", help="Print environment diagnostics.")
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    # Keep original argv for error-analyzer context.
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    setattr(args, "_argv", list(argv))

    try:
        rc = args.func(args)
    except KeyboardInterrupt:
        # Standard shell convention
        raise SystemExit(130)
    except Exception:
        tb = traceback.format_exc()
        _set_last_error(tb)
        _eprint(tb)
        setattr(args, "_exit_code", 1)
        # Best-effort: launch an error analyzer Codex.
        try:
            _auto_start_error_analyzer_codex(args, error_text=tb)
        except Exception:
            pass
        raise SystemExit(1)
    else:
        setattr(args, "_exit_code", rc)
        if rc == 1:
            err = _get_last_error() or f"Command failed with exit code {rc}"
            try:
                _auto_start_error_analyzer_codex(args, error_text=err)
            except Exception:
                pass
        raise SystemExit(rc)


if __name__ == '__main__':
    main()
