from __future__ import annotations

import argparse
import json
import hashlib
import os
import re
import sys
import time
import traceback
from typing import List, Tuple, Optional

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


def _parse_agents(agent_args: List[str]) -> List[Tuple[str, str]]:
    """
    Parse ["name=command", ...] into [(name, command), ...].
    """
    agents: List[Tuple[str, str]] = []
    for item in agent_args:
        if "=" not in item:
            raise ValueError(f"Invalid --agent value (expected name=command): {item}")
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
        agents = ["claude=claude", "codex=codex"]

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

    try:
        _eprint(f"tmux: {tmux_version()}")
        new_session(args.session, cwd=cwd, force=args.force)

        # Create panes
        if n == 1:
            pass
        elif n == 2:
            vertical = (args.layout == "vertical")
            split_window(args.session, cwd=cwd, vertical=vertical)
        else:
            # Create N-1 splits, then tile.
            # Alternate split direction to reduce extreme aspect ratios.
            vertical = True
            for _ in range(n - 1):
                split_window(args.session, cwd=cwd, vertical=vertical)
                vertical = not vertical
            select_layout_tiled(args.session)

        # Set titles + run commands
        panes = list_panes(args.session)
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

        if args.attach:
            tmux_attach(args.session)
        return 0

    except TmuxError as e:
        _set_last_error(str(e))
        _eprint(str(e))
        return 1





def cmd_start(args: argparse.Namespace) -> int:
    """Create a tmux session with a single *main* agent pane.

    This is a convenience for WSL/terminal workflows where you want:
      - 1x main agent (Claude Code, Cursor CLI, or Codex)
      - spawn Codex panes later via `aiteam codex ...`

    Examples:
      aiteam start --session myproj --main claude --attach
      aiteam start --session myproj --main cursor --attach
      aiteam start --session myproj --main codex --attach
      aiteam start --session myproj --main custom --command "agent" --title cursor --attach
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
        # Users can still override this with --command.
        if cmd is None:
            cmd = "agent"
        if title is None:
            title = "cursor"
    elif main == "codex":
        if cmd is None:
            cmd = "codex"
        if title is None:
            title = "codex"
    else:
        # custom
        if cmd is None:
            raise TmuxError("For --main custom, you must provide --command.")
        if title is None:
            title = "main"

    cwd = args.cwd or os.getcwd()

    try:
        _eprint(f"tmux: {tmux_version()}")
        new_session(args.session, cwd=cwd, force=args.force)

        panes = list_panes(args.session)
        if not panes:
            raise TmuxError(f"No panes found in session '{args.session}' after creating it.")
        pane_id = panes[0].pane_id
        set_pane_title(pane_id, title)
        paste_text(pane_id, cmd, enter=True)

        if args.attach:
            tmux_attach(args.session)
        return 0
    except TmuxError as e:
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
            raise TmuxError("Agent not specified. Use --agent name=command or --name/--command.")

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
        setattr(add_args, "command", getattr(args, "command", "codex"))
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
    raise TmuxError("No input text provided. Use --text, --file, or --stdin.")


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
        kill_session(args.session)
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
            if args.dotall:
                flags |= re.DOTALL
            if args.ignore_case:
                flags |= re.IGNORECASE
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
                raise TmuxError("--begin/--end must be non-empty (or use --pattern).")
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

        # Initial snapshot (used to either seed the cache or send existing blocks once).
        initial = capture_pane(src_id, lines=lines)
        initial_msgs = extract_messages(initial)

        if args.include_existing:
            # Send any matches already present in the pane, once.
            for msg in initial_msgs:
                normalized = msg.strip("\n")
                if not normalized.strip():
                    continue
                h = _sha(normalized.strip())
                if not h or h in seen:
                    continue
                seen[h] = time.time()
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
                if args.once or (max_sends > 0 and sent_count >= max_sends):
                    return 0

        else:
            # Seed cache with existing content, to avoid relaying old blocks.
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
        paste_text(new_pane_id, "codex", enter=True)
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
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--no-error-codex",
        action="store_true",
        help="Disable auto-starting an error-analyzer Codex pane when aiteam encounters a tmux/control error.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("spawn", help="Create a tmux session, split panes, and start agent commands.")
    sp.add_argument("--session", default="ai-team", help="tmux session name (default: ai-team)")
    sp.add_argument("--cwd", default=None, help="Working directory for panes (default: current directory)")
    sp.add_argument("--layout", choices=["vertical", "horizontal", "tiled"], default="vertical",
                    help="Pane split layout for 2 agents. For 3+ agents, layout becomes tiled. (default: vertical)")
    sp.add_argument("--agent", action="append", default=[], help="Agent definition: name=command (repeatable)")
    sp.add_argument("--force", action="store_true", help="Replace session if it already exists")
    sp.add_argument("--attach", action="store_true", help="Attach after spawning")
    sp.set_defaults(func=cmd_spawn)

    sp = sub.add_parser("start", help="Create a tmux session with a single main agent pane (Claude/Cursor/Codex).")
    sp.add_argument("--session", default="ai-team", help="tmux session name (default: ai-team)")
    sp.add_argument("--cwd", default=None, help="Working directory for the session (default: current directory)")
    sp.add_argument("--main", choices=["claude", "cursor", "codex", "custom"], default="claude", help="Which main agent to start (default: claude)")
    sp.add_argument("--command", default=None, help="Command to start the main agent (overrides the default for --main)")
    sp.add_argument("--title", default=None, help="Pane title for the main agent (default: claude/cursor/codex/main)")
    sp.add_argument("--force", action="store_true", help="Replace session if it already exists")
    sp.add_argument("--attach", action="store_true", help="Attach after starting")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser(
        "add",
        help="Add a new agent pane to an existing session (split from the current pane if inside tmux).",
    )
    sp.add_argument("--session", default=None, help="tmux session name (default: current session if inside tmux)")
    sp.add_argument("--agent", default=None, help="Agent definition: name=command (alternative to --name/--command)")
    sp.add_argument("--name", default=None, help="Agent name (pane title)")
    sp.add_argument("--command", default=None, help="Command to run in the new pane")
    sp.add_argument("--cwd", default=None, help="Working directory for the new pane (default: current directory)")
    sp.add_argument(
        "--layout",
        choices=["vertical", "horizontal"],
        default="vertical",
        help="Split layout (default: vertical)",
    )
    sp.add_argument("--tiled", action="store_true", help="After adding, apply tmux tiled layout")
    sp.add_argument(
        "--split-from",
        dest="split_from",
        default=None,
        help="Pane selector to split from (agent name or pane index). Default: current pane.",
    )
    sp.add_argument(
        "--if-exists",
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
    sp.add_argument("--command", default="codex", help="Command to start Codex (default: codex)")
    sp.add_argument("--cwd", default=None, help="Working directory for the new pane (default: current directory)")
    sp.add_argument(
        "--layout",
        choices=["vertical", "horizontal"],
        default="vertical",
        help="Split layout (default: vertical)",
    )
    sp.add_argument("--tiled", action="store_true", help="After adding, apply tmux tiled layout")
    sp.add_argument(
        "--split-from",
        dest="split_from",
        default=None,
        help="Pane selector to split from (agent name or pane index). Default: current pane.",
    )
    sp.add_argument(
        "--if-exists",
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
        "--no-return",
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
    g.add_argument("--text", help="Text to send")
    g.add_argument("--file", help="Read text from file")
    g.add_argument("--stdin", action="store_true", help="Read text from stdin")
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
    sp.add_argument("--header", default=None, help="Optional header line")
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
        "--dedupe-ttl",
        type=float,
        default=600.0,
        help="Seconds to remember already-relayed messages (default: 600). 0 disables eviction.",
    )
    sp.add_argument(
        "--include-existing",
        action="store_true",
        help="Relay any matching blocks already visible when relay starts (default: off)",
    )
    sp.add_argument("--once", action="store_true", help="Exit after the first successful relay")
    sp.add_argument(
        "--max-sends",
        type=int,
        default=0,
        help="Exit after relaying N messages (0 = unlimited, default: 0)",
    )
    sp.add_argument("--no-enter", action="store_true", help="Do not send Enter after pasting")
    sp.add_argument("--header", default=None, help="Optional header line to prepend to each relayed message")
    sp.add_argument("--prefix", default=None, help="Optional prefix (can be multi-line) to prepend to each message")
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not paste into the destination pane; print relayed messages to stdout",
    )
    sp.add_argument("--verbose", action="store_true", help="Log each relay event to stderr")

    # Extraction mode
    sp.add_argument(
        "--pattern",
        default=None,
        help="Regex pattern to extract messages. If omitted, marker mode is used.",
    )
    sp.add_argument(
        "--group",
        default=None,
        help="Regex capture group number to send (default: group 1 if present, else full match)",
    )
    sp.add_argument("--dotall", action="store_true", help="Regex: enable DOTALL ('.' matches newlines)")
    sp.add_argument("--ignore-case", action="store_true", help="Regex: ignore case")

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
