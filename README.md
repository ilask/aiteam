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

Now you can start the Hub from any directory:

```bash
aiteam
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

The core of v2 is the **Inter-Agent Router**. You can delegate a task directly:

```text
You> @codex Run the test suite and summarize failures.
```

Or, an agent can autonomously delegate. If Claude decides to run a command, it will output:
`@codex echo 'HELO'`
The Hub intercepts this and routes it natively.

## Testing (Vitest)

We use Vitest for unit tests (Hub/Adapters) and full E2E Workflow tests.

```bash
# Run all tests
pnpm run test

# Run E2E tests only
pnpm run test src/__tests__/e2e/
```

## E2E Dataset (Agent Teams Evaluation)

The repository includes a git submodule pointing to `weseek/growi` to evaluate complex Agent Teams collaboration (e.g. semantic search implementation). See `e2e-dataset/growi-semantic-search-task/TASK_SPEC.md` for details.
