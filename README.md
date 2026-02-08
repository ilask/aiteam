# tmux-ai-team-tool

A tiny CLI that makes **tmux-based “agent collaboration”** easier — especially on **WSL**.

It’s designed for workflows like:

- Pane A: **one main agent** (Claude Code, Cursor CLI, *or* Codex CLI)
- Pane B/C/D...: multiple **Codex CLI** panes (implement / test / refactor / error-analysis)

…and it reduces the annoying parts (session setup, pane naming, sending prompts, capturing output, quick handoffs, and optional push/relay).

## Requirements (WSL-friendly)

- **tmux** installed and available in `PATH`
- Python **3.9+**
- Any “agent CLI” commands you want to run (examples: `claude`, `agent` (Cursor CLI), `codex`)

On WSL/Ubuntu:

```bash
sudo apt update
sudo apt install -y tmux python3 python3-pip
```

## Install

### Option A: editable install (recommended)

```bash
cd tmux-ai-team-tool
python3 -m pip install -e .
```

You’ll get the `aiteam` command.

### Option B: run without installing

```bash
./aiteam --help

(or: `PYTHONPATH=src python3 -m tmux_ai_team --help`)
```

## Quickstart (WSL)

### 0) Start a session with **one main agent** (Claude, Cursor, or Codex)

If you omit `--session`, `aiteam` auto-generates one:

- inside a Git repo: preferred remote repo name
  - priority: `origin` -> `origin*` (lexicographic) -> other remotes (lexicographic) -> local top-level directory name
- if that name already exists: adds `-2`, `-3`, ...
- outside Git: falls back to `ai-team`

Claude Code as main:

```bash
aiteam start --cwd /path/to/project --main claude --attach
```

Cursor CLI as main (command is `agent`):

```bash
aiteam start --cwd /path/to/project --main cursor --attach

# or:
aiteam start --cwd /path/to/project --main custom --title cursor --command "agent" --attach
```

Codex as main:

```bash
aiteam start --cwd /path/to/project --main codex --attach
```

### 1) From inside the main pane, spawn Codex panes (multiple OK)

```bash
# Returns the selector on stdout, e.g. "codex:1"
CODEX_MAIN="$(aiteam codex --name main)"

CODEX_TESTS="$(aiteam codex --name tests)"
CODEX_REFACTOR="$(aiteam codex --name refactor)"
```

Each Codex pane title looks like:

`codex#<id>:<name>`

You can target a specific Codex later via:

`codex:<id>`

Example:

```bash
aiteam send --session myproj --to codex:2 --text "Run tests and summarize failures."
```

Useful options:

```bash
aiteam codex --layout horizontal   # split top/bottom
aiteam codex --focus new           # leave focus in the new Codex pane
aiteam codex --id 10 --name perf   # choose a specific id
aiteam codex --if-exists skip      # if that id already exists, do nothing
aiteam codex --no-return           # do NOT print selector to stdout
aiteam codex --json                # print JSON (id/name/selector/session)
```

### 2) Handoff without copy/paste

```bash
aiteam handoff --session myproj --from claude --to codex:1 --lines 120 --header "Plan from main:"
```

(Replace `--from claude` with your pane title, e.g. `--from cursor` or `--from codex`.)

### 3) Agent-to-agent push (optional)

Run a relay that watches the main pane and pushes marker blocks to a Codex pane:

```bash
aiteam relay --session myproj --from cursor --to codex:1 --header "From main:" --verbose
```

Tell the source agent to output:

```text
[PUSH]
Implement the plan above. Run tests. Summarize the diff.
[/PUSH]
```

Anything between `[PUSH]` and `[/PUSH]` gets pasted into the destination pane.

### 4) Capture Codex output

```bash
aiteam capture --session myproj --from codex:1 --lines 200
```

### 5) Kill the session

```bash
aiteam kill --session myproj
```

## Commands

- `start`  : create a tmux session and start a single main agent pane (Claude/Cursor/Codex)
- `spawn`  : create a tmux session, split panes, and start agent commands
- `add`    : add a new agent pane to an existing session
- `codex`  : start a new Codex instance pane (multiple supported; id+name)
- `attach` : attach to the tmux session
- `send`   : paste text into a pane (supports multiline)
- `capture`: capture the last N lines from a pane
- `handoff`: capture from one pane and paste into another (no copy/paste)
- `relay`  : watch a pane for marker blocks/regex matches and push them into another pane
- `list`   : list tmux sessions (filtered)
- `kill`   : kill a tmux session
- `doctor` : sanity checks (tmux presence, version, etc.)

## Auto error-analyzer Codex

If an `aiteam` command fails with a tmux/control error (exit code 1) **and you're inside tmux**,
`aiteam` will *best-effort* start a dedicated Codex pane titled like:

`codex#err1:error`

…and paste a structured prompt containing the error + environment details.
Disable with `--no-error-codex` or `AITEAM_DISABLE_ERROR_CODEX=1`.
