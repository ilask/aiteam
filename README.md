# aiteam (v2)

A tiny Node.js CLI that orchestrates **Agent Teams** (Codex, Claude Code, Gemini CLI) autonomously in a headless, tightly-coupled architecture.

**Note:** This is aiteam v2. We have migrated away from the legacy Python/tmux screen-scraping architecture to a robust Node.js WebSocket Hub with `stdio` JSON-RPC IPC.

It’s designed for workflows like:

- **Lead Agent** (Human or Mock UI) coordinates the team.
- **Claude Adapter** (`claude` headless stream mode) for architectural review and refactoring.
- **Gemini Adapter** (`gemini` headless stream mode) for log analysis and task implementation.
- **Codex Adapter** (`codex app-server` JSON-RPC mode) for test execution and OS operations.

…and it allows agents to autonomously `@agent_name` route messages to each other without human intervention.

## Requirements (Cross-Platform)

- Node.js **v20+**
- `pnpm` (via corepack)
- Any “agent CLI” commands you want to run (examples: `claude`, `gemini`, `codex`)

On Windows/macOS/Linux:

```bash
corepack enable
pnpm install
```

## Install & Run

### Development Build

```bash
cd tmux-ai-team-tool-repo
pnpm run build
```

### Global Installation (Recommended)

To run `aiteam` from anywhere on your system:

```bash
# Link globally via pnpm (or use: npm install -g .)
pnpm link --global
```

When you pull new changes, re-install globally so `aiteam` outside the repo uses the latest `dist/cli.js`:

```bash
pnpm run build
npm install -g . --force
```

Now you can start the Hub from any directory:

```bash
aiteam
aiteam codex
aiteam claude
```

### Run Locally (Without Global Install)

```bash
node dist/cli.js
```

## Quickstart (Headless Agent Teams)

Start the Central Hub. It will automatically spawn the Codex, Claude, and Gemini adapters in the background and present an interactive prompt.

```bash
node dist/cli.js
```

### Codex Profile (Recommended)

`aiteam` starts Codex via `codex app-server`. Make sure your `~/.codex/config.toml` has necessary capabilities enabled.

```toml
[profiles.aiteam]
model = "gpt-5.3-codex"
model_reasoning_effort = "high"
personality = "pragmatic"
approval_policy = "never"
sandbox_mode = "danger-full-access"
```

### Inter-Agent Routing

The core of v2 is the **Inter-Agent Router** with a single visible main agent.

```text
You(codex)> Run the test suite and summarize failures.
```

The human input line is routed to the selected main agent automatically (default: `codex`).
Background agents stay headless and communicate through the Hub.

An agent can autonomously delegate by outputting:
`@codex echo 'HELO'`
The Hub intercepts this and routes it natively.

### AI-Oriented Help

`aiteam -h` is optimized for AI operators and includes:

- main/peer role model (`lead`, `main`, `peers`)
- state model (`connected` / `disconnected`)
- inter-agent delegation contract (`@<agent> <task>`)
- autonomy policy (prefer agent-to-agent collaboration before reporting to lead)

Runtime status snapshot:

```text
/status
```

## Common Runtime Issues

- `Port 4501 is in use`:
  - Expected fallback behavior: `aiteam` auto-selects another free port.
- `aiteam` output looks like old `@agent`-only UX:
  - Rebuild and reinstall globally (`npm install -g . --force`) so global shim points to latest build.
- Claude asks permission before command/tool execution:
  - Default adapter mode is `--permission-mode bypassPermissions`.
  - Override with `AITEAM_CLAUDE_PERMISSION_MODE` if needed.
- Codex is slow or appears to hang on simple prompts:
  - Adapter now starts Codex with `approval_policy="never"` and `model_reasoning_effort="medium"` by default.
  - Override with `AITEAM_CODEX_APPROVAL_POLICY` / `AITEAM_CODEX_REASONING_EFFORT`.
  - Use `inherit` to defer to your global Codex profile config.
- Claude command execution on Windows hits `bash ... dofork ... 0xC0000142`:
  - By default, Claude `Bash` is allowed.
  - If your environment is unstable, disable only Bash with `AITEAM_CLAUDE_ALLOW_BASH=0`.
- Gemini on Windows shows `AttachConsole failed`:
  - Adapter runs Gemini with `-p` one-shot prompts and Windows Node entrypoint fallback.
  - Adapter stderr is hidden by default to avoid log noise; enable it with `AITEAM_GEMINI_LOG_STDERR=1`.
- `[sys:n] waiting for codex...` frequency tuning:
  - Adjust with `AITEAM_SYS_PROGRESS_INTERVAL_MS` (default: `5000` ms).
  - Waiting banner includes elapsed seconds and blocks new prompts until the current target replies.

## Testing (Vitest)

We use Vitest for unit tests (Hub/Adapters) and full E2E Workflow tests.

E2E tests are driven through `wezterm cli` (Windows). They require:
- WezTerm installed (`wezterm.exe`)
- `codex` CLI available in PATH
- built artifacts (`pnpm run build`)

```bash
# Run all tests
pnpm run test

# Run E2E tests only
pnpm run test src/__tests__/e2e/
```

### Test Layout

- Active Node/Vitest tests: `src/__tests__/`
- Manual adapter probe scripts (not auto-run by Vitest): `src/__tests__/probes/`

## E2E Scenarios (Copy/Paste)

The following examples map directly to existing E2E specs.

### 1) Headless Smoke Workflow (`src/__tests__/e2e/headless-workflow.spec.ts`)

Run the spec only:

```bash
pnpm exec vitest run src/__tests__/e2e/headless-workflow.spec.ts --reporter verbose
```

Manual interactive equivalent:

```text
aiteam
/status
Hello, are you there?
exit
```

Expected:
- `/status` shows `- codex: connected`
- A `[codex] ...` reply appears
- `Shutting down...` appears on `exit`

### 2) Deep Inter-Agent Collaboration + Image Generation (`src/__tests__/e2e/inter-agent.spec.ts`)

Run the spec only:

```bash
pnpm exec vitest run src/__tests__/e2e/inter-agent.spec.ts --reporter verbose
```

Manual interactive equivalent (send this as one message after `aiteam` starts):

```text
You are codex main coordinator. Hard constraint: do NOT run shell commands or terminal tools yourself. Focus only on agent-to-agent delegation and synthesis. Do NOT use internal collab tools like spawnAgent/wait/closeAgent. Only delegate using literal @claude and @gemini lines. Never ask claude to read/write files. Claude must answer in plain text only. Do not skip delegation. You MUST delegate to claude and gemini first. First output exactly two delegation lines (one per line) before any explanation: @claude Provide a plain-text GROWI semantic-search architecture overview (Elasticsearch vector backend + OpenAI embeddings). Do not use file/tools. @gemini /generate "GROWI semantic search architecture diagram manual_token_20260223" --count=1 Then continue autonomous multi-agent workflow: 1) delegate to claude for GROWI semantic search overview design (Elasticsearch vector backend + OpenAI embeddings). 2) delegate to gemini with an actual /generate command that includes token manual_token_20260223. 3) produce codex impact scope. 4) perform mutual review among claude/codex/gemini and resolve disagreements. Return concise updates while work is running. Do not ask lead for extra steps unless blocked.
```

Then send:

```text
Provide final consolidated overview with sections: CLAUDE_DESIGN, CODEX_IMPACT, GEMINI_DIAGRAM, MUTUAL_REVIEW.
```

Expected:
- `/status` routed pairs include both `codex->claude` and `codex->gemini`
- a new PNG is generated in `nanobanana-output/`
- debug log includes `fromConnection=gemini` with `eventType=gemini_text`

### 3) Hub Port Fallback (`src/__tests__/e2e/headless-workflow.spec.ts`)

Manual reproduction:

```powershell
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 4501)
$listener.Start()
aiteam
```

Expected startup line:

```text
[aiteam] Port 4501 is in use. Using port <another-port>.
```

Cleanup:

```powershell
$listener.Stop()
```

## E2E Dataset (Agent Teams Evaluation)

The repository includes a git submodule pointing to `weseek/growi` to evaluate complex Agent Teams collaboration (e.g. semantic search implementation). See `e2e-dataset/growi-semantic-search-task/TASK_SPEC.md` for details.
