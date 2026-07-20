# Bug: vision-agent sandbox silently classifies nothing (WSL Hyper-V firewall blocks container→host LLM)

**Status:** Fix written, pending verification (needs elevated re-run of `setup-service.ps1` + a live `sandbox_run.py --agent vision --dry-run` retest).
**Reported by:** dashboard Home page showing zero processed images despite 180 images sitting in `00-Inbox/images`.

## Symptom

`agents.vision` never advances past `"pending"` for any inbox image (`system/state/inbox-queue.json`). Every scheduled cycle logs and exits clean:

```
[vision-agent] WARN: Qwen3-VL (localhost:1234) offline - skipping batch
[vision-agent] INFO: --- DONE (classified: 0, failed: 0, elapsed: 0.0s) ---
```

`tasks-state.json` shows `vision-agent.lastRun` advancing every cycle - the scheduler runs fine, the agent itself just never does work. Home page (`system/dashboard/src/app/home/page.tsx`) has nothing to show for `world`/`cast`/`powers`/`story`/`bestiary` pillars because no image ever produces a draft in `01-Processing`.

## Root cause

`agents/registry.yaml` has `agents.vision.sandbox.enabled: true` (the only agent sandboxed) - its dispatch runs `python -m nexus.runner --task vision-agent --force` inside a Podman container built by `system/src/nexus/tasks/sandbox_run.py`, with `localhost` rewritten to `host.containers.internal` (`_rewrite_localhost`) so the container can reach the host's LM Studio server.

Confirmed via direct reproduction (this session):
- Host: `curl http://localhost:1234/v1/models` → `200`, model loaded, listening `0.0.0.0:1234`.
- Classic Windows Defender Firewall: explicit `Allow` rules for "LM Studio" on both `Public` and `Private` profiles.
- Podman machine (WSL2, `podman-machine-default`) → host gateway (`172.18.208.1`, resolved via `podman machine ssh -- ip route show default`): **ICMP succeeds, TCP:1234 refused/unreachable.**

The blocker is **not** classic Windows Firewall - it's Windows 11's separate **Hyper-V VM firewall** layer, which filters traffic for the WSL utility VM independently of per-adapter Windows Firewall profiles:

```powershell
PS> Get-NetFirewallHyperVVMCreator
VMCreatorId  : {40E0AC32-46A5-438A-A0B2-2B479E8F2E90}
FriendlyName : WSL
```

This VM has ~154 predefined rules (Core Networking / ICMPv6 / DHCP etc. - explains why ping works) but **no rule permitting outbound TCP to port 1234**. The classic "LM Studio" `New-NetFirewallRule` entries are invisible to this layer entirely - a normal Windows Firewall allow rule does not open the Hyper-V VM firewall too. No `.wslconfig` exists on this machine, so the WSL Hyper-V firewall runs at its (undocumented-locally, effectively default-deny-for-unlisted-ports) default posture.

This exactly matches the prior investigation in `docs/qa/feedback/03-sandbox-vision-agent-lm-studio-unreachable.md`, which stopped short of root-causing the network layer itself ("fixing Windows/Podman network configuration is outside this codebase"). This bug report closes that gap.

## Fix applied

Scoped fix, chosen over disabling the WSL firewall wholesale (would affect every WSL distro on the machine, not just Podman): a targeted `New-NetFirewallHyperVRule` allowing outbound TCP to vision's LLM port, scoped to the WSL VM only.

Added `Ensure-VisionSandboxFirewallRule` to `system/ops/setup-service.ps1` (function ~line 494, called ~line 1085 right after Podman/Docker detection, only when Podman is found):

- Idempotent - checks for an existing rule named `NexusVisionSandbox-LLMOut` before creating one.
- Resolves the WSL `VMCreatorId` dynamically via `Get-NetFirewallHyperVVMCreator` (not hardcoded - portable across machines).
- Reads the port from `agents/registry.yaml`'s `llm_endpoints.vision_llm.url` instead of hardcoding `1234`.
- Non-fatal on any failure (older Windows without Hyper-V firewall cmdlets, permission issue, etc.) - logs a `WARN` and continues install, matching this script's existing pattern for optional preflight checks (Podman/Docker not found is likewise a warning, not a hard stop).
- Runs only during a real install invocation (`setup-service.ps1` with no `-Status`/`-Uninstall`) - both those flags `exit` before reaching this code, so `-Status` stays read-only and `-Uninstall` doesn't touch firewall state.

`setup-service.ps1` already requires an elevated shell for every non-`-Status` action (`Is-Admin` check ~line 208), so no new elevation prompt is introduced - the rule is created as part of the same elevated run the service install already needs.

## Verification steps (not yet run - needs elevated shell)

1. `pwsh -File system/ops/setup-service.ps1 -CleanInstall` (or any elevated install invocation) - confirm log line `Added WSL Hyper-V firewall rule for vision sandbox -> host LLM (TCP 1234).`
2. Re-probe from inside the WSL VM:
   ```
   podman machine ssh -- python3 -c "import socket; s=socket.socket(); s.settimeout(3); print(s.connect_ex(('172.18.208.1', 1234)))"
   ```
   Expect `0` (was refused before the rule existed).
3. `python -m nexus.tasks.sandbox_run --agent vision --dry-run` against a real unprocessed inbox image - confirm a genuine classification diff appears under `.knowledge-base/01-Processing/` (not another silent 0-change, exit-0 run).
4. Drop `--dry-run`, confirm `agents.vision` flips to `"done"` in `inbox-queue.json` for the processed image and a draft lands in `01-Processing`.

## Related

- `docs/qa/feedback/03-sandbox-vision-agent-lm-studio-unreachable.md` - original observation, network layer not yet identified.
- `agents/registry.yaml` - `agents.vision.sandbox` config, `llm_endpoints.vision_llm`.
- `system/src/nexus/tasks/sandbox_run.py` - `_podman_wsl_gateway_ip()`, `_warn_unreachable_llm_ports()` (existing preflight probe that already surfaces this exact failure as a WARN, just couldn't fix it).
