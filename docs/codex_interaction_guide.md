# Codex CLI Interaction Guide

This document summarizes the best practices and known pitfalls for interacting with the `codex` CLI programmatically or via terminal scripts, particularly when passing non-interactive prompts.

## 1. Using `codex exec` for Non-Interactive Execution

The standard `codex` command defaults to an interactive TUI session. To execute a single prompt and return the result without entering the TUI, use the `codex exec` subcommand.

### Passing Prompts to `codex exec`

There are two primary ways to pass a prompt to `codex exec`:

*   **As a Positional Argument (Recommended for multi-line):**
    If your prompt is stored in a file (e.g., `prompt.txt`), the most robust way to pass it—especially on Windows (PowerShell)—is to read the raw content and pass it as a single string argument.
    
    *PowerShell Example:*
    ```powershell
    codex exec "$(Get-Content prompt.txt -Raw)"
    ```
    *Bash Example:*
    ```bash
    codex exec "$(cat prompt.txt)"
    ```

*   **Via Standard Input (stdin):**
    You can pipe the content directly to `codex exec`. However, be aware that depending on the OS and the shell, piping might sometimes cause the process to hang or fail to terminate cleanly if the input stream isn't closed properly.
    
    *Example:*
    ```powershell
    Get-Content prompt.txt | codex exec
    ```

## 2. Common Pitfalls & Troubleshooting

### Hangs or Operation Cancelled
If `codex exec` hangs indefinitely or immediately returns `[Operation Cancelled] Reason: Operation cancelled`, it often means the command did not receive the expected input prompt, or the stdin stream was interrupted before the prompt could be fully processed. **Fix:** Ensure the prompt is passed as a complete string argument using command substitution (`$(...)`).

### Missing Configuration Profiles
If you try to load a specific profile using the `-p` or `--profile` flag (e.g., `-p aiteam`) and that profile does not exist in your `~/.codex/config.toml`, the command will fail immediately with:
`Error: config profile <name> not found`
**Fix:** Verify the profile exists in your configuration file before using the `-p` flag.

### Misplaced Flags
Flags intended for the interactive `codex` command (like `-a never` for approval policies) may not be supported directly by `codex exec`, or they might need to be passed differently. If you pass an unsupported flag, you will see:
`error: unexpected argument '-a' found`
**Fix:** Run `codex exec --help` to see exactly which flags are supported for non-interactive mode. For example, `codex exec` supports `-s` (sandbox), `-m` (model), and `-c` (config overrides).

## 3. Advanced: Overriding Configs Inline

If you need to change a behavior (like the approval policy) without modifying `config.toml`, you can use the `-c` flag to override nested TOML values directly from the command line:

```bash
codex exec -c "approval_policy='never'" "$(Get-Content prompt.txt -Raw)"
```
