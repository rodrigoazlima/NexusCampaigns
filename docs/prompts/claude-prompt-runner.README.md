# claude-prompt-runner.ps1

Batch-runs every prompt file under `docs/prompts/` through
`claude --dangerously-skip-permissions -p`, one at a time, with retry/cooldown
handling for usage and credit limits. Completed prompts are moved into
`docs/prompts/prompt-done/`.

## Quick start

From anywhere (the script re-anchors itself to the repo root):

```powershell
pwsh docs/prompts/claude-prompt-runner.ps1
```

That's it. It discovers the prompts, runs them sequentially, and exits when all
are done (or have exhausted their retries).

## What it does

1. **Anchors to the repo root.** Before doing anything, the script derives the
   codebase root by stripping the `$PromptDirectory` tail off `$PSScriptRoot`
   (its own absolute folder) and `Set-Location`s there, so the relative defaults
   (`docs/prompts`, `.system/...`) resolve no matter where you invoke it from.
   The root is computed from the variables, not a hardcoded depth — move the
   script and it still finds the right root as long as it stays under
   `$PromptDirectory`.
2. **Discovers prompts.** Every top-level `*.md` in `docs/prompts/` except
   `*README*`. Subfolders (`gen/`, `prompt-done/`) are not scanned.
3. **Runs each prompt.** Pipes the file's contents into
   `claude --dangerously-skip-permissions -p` as a background job, capturing
   output and exit code.
4. **On success** — marks the prompt completed and **moves the file into
   `docs/prompts/prompt-done/`** so it won't run again.
5. **On failure** — increments the retry count and waits out the cooldown before
   trying again. Failure = non-zero exit code, or output matching a known
   limit message (`usage limit reached`, `insufficient credits`,
   `credit limit reached`).
6. **Persists state** to `.system/claude-queue-state.json` after every step, so
   you can Ctrl-C and re-run to resume exactly where it left off.

## Parameters

| Param | Default | Meaning |
|-------|---------|---------|
| `-PromptDirectory` | `docs/prompts` | Folder to scan (relative to repo root). |
| `-Filter` | `*.md` | Glob for prompt files. README files are always excluded. |
| `-StateFile` | `.system/claude-queue-state.json` | Resume/queue state. |
| `-RetryDelayMinutes` | `40` | Cooldown before retrying a failed prompt. |
| `-MaxRetries` | `200` | Per-prompt retry cap before giving up. |
| `-TimeoutMinutes` | `30` | Per-prompt run timeout. |

Examples:

```powershell
# Only run the refactor prompts, 15-min timeout
pwsh docs/prompts/claude-prompt-runner.ps1 -Filter "*-refactor.md" -TimeoutMinutes 15

# Point at a different prompt folder
pwsh docs/prompts/claude-prompt-runner.ps1 -PromptDirectory docs/other-prompts
```

## Resuming

State lives in `.system/claude-queue-state.json`. Re-running picks up the queue:
completed prompts stay completed (and are already moved to `prompt-done/`), and
newly added `*.md` files are appended to the queue automatically. To start
completely fresh, delete the state file.

## Notes

- Requires the `claude` CLI on `PATH`.
- `--dangerously-skip-permissions` is passed, so prompts run unattended without
  approval prompts. Only point this at prompts you trust.
- Output is streamed to the console with timestamps; nothing is written to a log
  file by default.
