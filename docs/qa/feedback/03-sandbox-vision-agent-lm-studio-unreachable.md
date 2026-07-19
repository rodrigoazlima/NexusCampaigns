# QA Report: sandboxed vision agent live test — container cannot reach host LM Studio

**Reported by:** manual `nexus.tasks.sandbox_run` invocation against the real local vault (`.testing/vault`, Podman runtime)
**Symptom:** `sandbox_run.py`'s orchestration (build/stage/dispatch/diff/classify/cleanup) works correctly end to end, but the vision agent itself does no classification work inside the container — it logs `Qwen3-VL (localhost:1234) offline - skipping batch` and exits 0 with nothing to apply. Root cause: the container cannot open a TCP connection to the host's LM Studio server over Podman's `host.containers.internal` gateway, even though ICMP to that gateway succeeds and Windows Firewall already has `Allow` rules for LM Studio on both Public and Private profiles.

This document only records what was observed — no code was changed while producing it.

---

## Setup

| Field | Value |
|---|---|
| Command | `python -m nexus.tasks.sandbox_run --agent vision --dry-run` |
| Container runtime | `podman` (machine running, `podman info` OK) |
| Base image | `nexus-sandbox-base:a21f087dbeb9` (cache hit, ~87s total build+run) |
| Test image | `.knowledge-base/00-Inbox/images/custom-vision-sandbox-test.jpg` — a copy of the existing `elf.portrait.jpg`, dropped under a new name so vision would have a genuinely unprocessed file to classify (all other non-token images in the inbox were already in `agents/vision/state/processed-images.json`; every remaining "unprocessed" file was a `*-token.png` generated asset, filtered out by `classify_images.py`'s `_is_token_file`) |
| Run record | `system/state/sandbox/runs/run-20260719T124950Z-vision.json` (gitignored, kept locally) |

## What happened

Container exit code `0`, 8 file changes detected, 0 applied (dry-run), 8 dropped. All 8 changed files were runner bookkeeping only — none touched `.knowledge-base/00-Inbox/images` or `.knowledge-base/01-Processing`:

```
would-drop | other | agents/classification/agent.json               | outside declared commit_scope/state_files
would-drop | other | agents/lore/agent.json                          | outside declared commit_scope/state_files
would-drop | other | agents/runtime/state/agent-metrics.json         | outside declared commit_scope/state_files
would-drop | other | agents/runtime/state/logs/automation.log        | outside declared commit_scope/state_files
would-drop | other | agents/runtime/state/logs/runner_2026-07-19.log | outside declared commit_scope/state_files
would-drop | other | agents/runtime/state/tasks-state.json           | outside declared commit_scope/state_files
would-drop | other | agents/vision/state/logs/classify_images_...log | outside declared commit_scope/state_files
would-drop | other | agents/wiki/agent.json                          | outside declared commit_scope/state_files
```

These are all correctly classified as `other`/dropped (they're runtime bookkeeping outside `commitScope: ['.knowledge-base/00-Inbox/images', '.knowledge-base/01-Processing']` and outside `stateAllowlist`) — the classify/apply logic behaved exactly as designed. The problem is upstream of it: nothing about the test image changed at all.

Container log (tail):
```
[vision-agent] INFO: Dispatching via cli: python
[vision-agent] WARN: Qwen3-VL (localhost:1234) offline - skipping batch
[vision-agent] INFO: --- DONE (classified: 0, failed: 0, elapsed: 0.0s) ---
[runtime] WARN: Git commit failed for vision-agent: [Errno 2] No such file or directory: 'git'
```
(The `git` warning is expected/harmless inside the sandbox base image, which has no `git` binary — commit is a no-op there by design; `sandbox_run.py` does its own diff/apply instead.)

## Root cause: container → host LM Studio connectivity

The host itself is fine:
- `curl http://localhost:1234/v1/models` from the host → `200`, `qwen3-vl-4b-instruct` listed as loaded.
- `Get-NetTCPConnection -LocalPort 1234` → LM Studio bound to `0.0.0.0:1234` (all interfaces, not just loopback).
- `Get-NetFirewallRule` → two `LM Studio` inbound `Allow` rules, covering both `Public` and `Private` profiles.

But from inside a Podman container on the same machine:
```
$ podman run --rm --add-host=host.containers.internal:host-gateway alpine sh -c \
    "getent hosts host.containers.internal; ping -c1 -W2 host.containers.internal"
169.254.1.2  host.containers.internal
64 bytes from 169.254.1.2: ... (ping succeeds)

$ podman run --rm --add-host=host.containers.internal:host-gateway curlimages/curl \
    curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 5 http://host.containers.internal:1234/v1/models
http_code=000   (curl exit 7 — could not connect)
```

So the gateway IP resolves and answers ICMP, but the TCP connection to port 1234 is refused/unreachable. `sandbox_run.py`'s own `localhost` → `host.containers.internal` rewrite (`_rewrite_localhost`, applied to the staged `agents/registry.yaml` at build time) is doing its job correctly — this isn't a bug in `sandbox_run.py` itself. The break is in the network path between Podman's gvproxy user-mode network and the Windows LM Studio listener: something between the two — most likely a firewall rule or Windows network-profile categorization that treats the Podman machine's virtual adapter differently for TCP than for ICMP — is dropping the connection. Not root-caused further; fixing Windows/Podman network configuration is outside this codebase.

## Current vault state

`custom-vision-sandbox-test.jpg` is left in `.knowledge-base/00-Inbox/images/` (untouched, unprocessed) so a retest after the network issue is fixed doesn't need a new fixture. No other vault or agent state was modified — the run was `--dry-run`, and even the 8 detected changes were all `would-drop`, so nothing was written back to the real install.

## Recommendations

1. **Before trusting any sandboxed-agent classification result**, verify container→host reachability first, e.g. `podman run --rm --add-host=host.containers.internal:host-gateway curlimages/curl curl -sf http://host.containers.internal:1234/v1/models` — cheap smoke test, would have caught this in seconds instead of a full sandbox run.
2. Once connectivity is fixed, rerun `python -m nexus.tasks.sandbox_run --agent vision --dry-run` against the same `custom-vision-sandbox-test.jpg` and confirm a real classification diff appears under `.knowledge-base/01-Processing/` before applying for real (drop `--dry-run`).
3. Consider having `sandbox_run.py` itself do a cheap host-gateway reachability probe as part of `_preflight()` for `claude-api`/local-LLM dispatch types, so "container ran fine but silently classified nothing" fails loudly instead of looking like a clean 0-change run.
