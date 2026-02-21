# AI Team Members

This file contains guidelines and context for interacting with the various AI agents in this project.
It is intended to be read by the main agent (like Gemini, Claude, or Cursor) to understand how to effectively coordinate with sub-agents like Codex.

## Codex CLI

When instructing or communicating with the Codex CLI, be aware of its specific execution quirks, especially when running non-interactively.

**⚠️ IMPORTANT: Before attempting to run commands against `codex` or `codex exec`, please review the [Codex CLI Interaction Guide](docs/codex_interaction_guide.md).**

It contains crucial knowledge gathered from trial-and-error regarding:
*   How to properly pass multi-line prompts without causing hangs.
*   Why piping (`|`) into `codex exec` might fail on certain OS environments.
*   How to correctly format flags for non-interactive mode.
