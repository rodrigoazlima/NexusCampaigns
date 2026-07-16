"""lore.tools.generate_npcs

Generates PF2e NPC sheets from classified character images × active scenarios.
Implements reflexion loop (impl-guide/01-reflexion-loop.md): score → critique → revise
up to _MAX_REVISIONS rounds. Outputs with score < 7 after all rounds are flagged
with needs_human_review: true and a ## Reviewer Notes section.

No LLM → skip gracefully. Batch: BATCH_SIZE image×scenario pairs per run.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid as _uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from nexus.shared import (  # noqa: E402
    FrontmatterIO,
    LLMClient,
    LLMOfflineError,
    LLMResponseError,
    NPCLLMOutput,
    QualityGate,
    image_tag,
    locked_update_queue_entry,
)
from nexus.shared.config import LLMEndpointConfig  # noqa: E402
from nexus.shared.loaders import load_llm_endpoint  # noqa: E402

TASK_ID         = "lore-agent"
SCRIPT_BASENAME = "generate_npcs.py"
BATCH_SIZE      = 10

_VAULT_ROOT   = _PROJECT_ROOT / ".knowledge-base"
_PROCESSING   = _VAULT_ROOT / "01-Processing"
_LIBRARY      = _VAULT_ROOT / "02-Library"
_AGENT_STATE  = _AGENTS_DIR / "lore" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_SHARED_STATE = _PROJECT_ROOT / "system" / "state"
_MASTER_LOG   = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_VISION_STATE = _AGENTS_DIR / "vision" / "state" / "processed-images.json"
_PROC_NPCS    = _AGENT_STATE / "processed-npcs.json"
_SCENARIOS    = _AGENT_STATE / "scenarios.json"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"
_PROMPT_FILE  = _AGENTS_DIR / "lore" / "prompts" / "generate-npc.txt"
_REVISE_FILE  = _AGENTS_DIR / "lore" / "prompts" / "revise-npc.md"

_LLM_CFG = load_llm_endpoint(
    "vision_llm",
    fallback = LLMEndpointConfig(
        url      = "http://localhost:1234/v1/chat/completions",
        model    = "qwen3-vl-4b-instruct",
        type     = "vision",
        provider = "lmstudio",
    ),
    agent_dir    = _AGENTS_DIR / "lore",
    task_id      = TASK_ID,
    project_root = _PROJECT_ROOT,
)

_CHARACTER_TYPES = frozenset({"portrait", "body", "token"})
_GATE            = QualityGate()
_MAX_REVISIONS   = 2

_STAT_FIELDS = frozenset({"str", "dex", "con", "int", "wis", "cha"})


def _normalize_stats(raw: dict) -> dict:
    """Convert D&D-style ability scores (1-20) to PF2e modifiers (-5 to +5).

    LLMs sometimes return scores instead of modifiers. Values >5 are treated
    as scores and converted via (score - 10) // 2, then clamped to [-5, 5].
    """
    result = dict(raw)
    for field in _STAT_FIELDS:
        v = result.get(field)
        if isinstance(v, int):
            if v > 5:
                result[field] = max(-5, min(5, (v - 10) // 2))
            else:
                result[field] = max(-5, min(5, v))
    return result


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"generate-npcs_{today}.log"
        self._master = _MASTER_LOG

    def _write(self, level: str, msg: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{TASK_ID}] {level}: {msg}"
        print(line, flush=True)
        self._master.parent.mkdir(parents=True, exist_ok=True)
        for p in (self._master, self._daily):
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, m: str)    -> None: self._write("INFO",  m)
    def warning(self, m: str) -> None: self._write("WARN",  m)
    def error(self, m: str)   -> None: self._write("ERROR", m)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, count: int = 0, failed: int = 0) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write("INFO", f"--- DONE --- processed={count} failed={failed} elapsed={elapsed}s")


# ---------------------------------------------------------------------------
# NPC generator — implements INPCGenerator
# ---------------------------------------------------------------------------

class _NPCGeneratorImpl:
    """Wraps LLMClient for NPC sheet generation. Implements INPCGenerator."""

    def __init__(self, client: LLMClient, prompt_tpl: str) -> None:
        self._client     = client
        self._prompt_tpl = prompt_tpl

    def _build_prompt(self, scenario: dict, canon_context: str) -> str:
        return (
            self._prompt_tpl
            .replace("{scenario_name}",        scenario["name"])
            .replace("{scenario_description}", scenario["description"])
            .replace("{arc}",                  scenario.get("arc", ""))
            .replace("{canon_context}",        canon_context)
        )

    def generate(
        self,
        image_path: Path,
        scenario: dict,
        canon_context: str,
    ) -> NPCLLMOutput:
        prompt = self._build_prompt(scenario, canon_context)
        raw = self._client.vision_chat(
            image_path, prompt,
            system="You are a Pathfinder 2e NPC generator. Return ONLY valid JSON.",
            max_tokens=1200,
        )
        return NPCLLMOutput.model_validate(_normalize_stats(raw))

    def generate_with_critique(
        self,
        image_path: Path,
        scenario: dict,
        canon_context: str,
        critique: str,
    ) -> NPCLLMOutput:
        """Re-generate with critique injected into the user prompt."""
        revise_tpl = (
            _REVISE_FILE.read_text(encoding="utf-8")
            if _REVISE_FILE.exists()
            else (
                "CRITIQUE:\n{critique}\n\n"
                "Revise the NPC sheet to address all gaps above. "
                "Keep all correct information. Return ONLY valid JSON."
            )
        )
        base_prompt = self._build_prompt(scenario, canon_context)
        revision_prompt = (
            base_prompt + "\n\n"
            + revise_tpl.replace("{critique}", critique)
        )
        raw = self._client.vision_chat(
            image_path, revision_prompt,
            system="You are a Pathfinder 2e NPC generator. Return ONLY valid JSON.",
            max_tokens=1200,
        )
        return NPCLLMOutput.model_validate(_normalize_stats(raw))


# ---------------------------------------------------------------------------
# Reflexion loop helpers
# ---------------------------------------------------------------------------

def _output_to_frontmatter(npc: NPCLLMOutput, image_rel: str, scenario: dict) -> dict:
    """Build minimal frontmatter dict for quality scoring."""
    rels = [f"[[{scenario['id']}]]"] + [r for r in npc.relationships if r != f"[[{scenario['id']}]]"]
    return {
        "type":          "npc",
        "tags":          ["npc"],
        "source":        [image_rel],
        "relationships": rels,
    }


def _output_to_body(npc: NPCLLMOutput, scenario: dict) -> str:
    """Build body string for quality scoring."""
    rels = [f"[[{scenario['id']}]]"] + [r for r in npc.relationships if r != f"[[{scenario['id']}]]"]
    body = (
        f"\n## Description\n\n{npc.description}\n\n"
        f"## Abilities\n\n"
        + "\n".join(f"- {a}" for a in npc.abilities) + "\n\n"
    )
    if npc.tactics:
        body += f"## Tactics\n\n{npc.tactics}\n\n"
    if npc.plot_hooks:
        body += "## Plot Hooks\n\n" + "\n".join(f"- {h}" for h in npc.plot_hooks) + "\n\n"
    body += "## Related\n\n" + "\n".join(rels) + "\n"
    return body


def _build_critique(fm: dict, body: str, score: int) -> str:
    """Build a targeted critique string from quality gate gap analysis."""
    gaps: list[str] = []

    if not re.search(r"^##\s+(description|descrição|desc)\b", body, re.I | re.M):
        gaps.append("- Missing '## Description' section with meaningful content")

    rels      = fm.get("relationships") or []
    body_links = re.findall(r"\[\[.+?\]\]", body)
    if not rels and not body_links:
        gaps.append("- No [[wikilinks]] to related entities (location, faction, quest)")

    if len(fm.get("tags") or []) < 3:
        gaps.append("- Fewer than 3 tags; add specific PF2e and campaign tags")

    if not fm.get("source"):
        gaps.append("- Missing source field")

    if not re.search(r"^##\s+plot\s+hooks\b", body, re.I | re.M):
        gaps.append("- Missing '## Plot Hooks' section with 3 specific hooks")

    if not re.search(r"^##\s+tactics\b", body, re.I | re.M):
        gaps.append("- Missing '## Tactics' section describing how they fight or negotiate")

    if not gaps:
        gaps.append("- Description section lacks meaningful content (too short or generic)")

    gap_text = "\n".join(gaps)
    return (
        f"The previous NPC sheet scored {score}/10. "
        f"It is missing these required elements:\n{gap_text}\n\n"
        f"Revise the NPC sheet to address all gaps above. "
        f"Keep all correct information from the previous version."
    )


def _flag_for_human_review(output: NPCLLMOutput, score: int) -> NPCLLMOutput:
    """Return a copy of output with needs_human_review=True and review_notes set."""
    return output.model_copy(update={
        "needs_human_review": True,
        "review_notes": (
            f"Auto-generated. Quality score after {_MAX_REVISIONS} revision rounds: {score}/10. "
            f"Human review required before Library promotion."
        ),
    })


def _score_and_revise(
    generator: _NPCGeneratorImpl,
    image_path: Path,
    scenario: dict,
    canon_context: str,
    first_output: NPCLLMOutput,
    image_rel: str,
) -> NPCLLMOutput:
    """Run up to _MAX_REVISIONS critique rounds. Return best output (G4)."""
    current = first_output
    fm      = _output_to_frontmatter(current, image_rel, scenario)
    body    = _output_to_body(current, scenario)
    score   = _GATE.score(fm, body)

    for _round in range(1, _MAX_REVISIONS + 1):
        if score >= 7:
            break
        critique = _build_critique(fm, body, score)
        try:
            revised   = generator.generate_with_critique(image_path, scenario, canon_context, critique)
            new_fm    = _output_to_frontmatter(revised, image_rel, scenario)
            new_body  = _output_to_body(revised, scenario)
            new_score = _GATE.score(new_fm, new_body)
        except (LLMOfflineError, LLMResponseError, Exception):
            break  # keep current best on revision failure
        if new_score > score:
            current, fm, body, score = revised, new_fm, new_body, new_score

    if score < 7:
        current = _flag_for_human_review(current, score)
    return current


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_scenarios() -> list[dict]:
    if not _SCENARIOS.exists():
        from nexus.shared.defaults import SCENARIOS_DEFAULT
        _AGENT_STATE.mkdir(parents=True, exist_ok=True)
        _SCENARIOS.write_text(json.dumps(SCENARIOS_DEFAULT, indent=2), encoding="utf-8")
    return json.loads(_SCENARIOS.read_text(encoding="utf-8"))


def _load_vision_state() -> dict[str, Any]:
    if not _VISION_STATE.exists():
        return {"images": {}}
    return json.loads(_VISION_STATE.read_text(encoding="utf-8"))


def _load_proc_npcs() -> dict[str, Any]:
    if not _PROC_NPCS.exists():
        return {}
    return json.loads(_PROC_NPCS.read_text(encoding="utf-8"))


def _save_proc_npcs(data: dict) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _PROC_NPCS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(_PROC_NPCS)


def _load_queue() -> dict[str, Any]:
    if not _QUEUE_FILE.exists():
        return {}
    return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))


def _canon_context() -> str:
    lines: list[str] = []
    if not _LIBRARY.is_dir():
        return "No canon entities yet."
    fio = FrontmatterIO()
    for md_path in sorted(_LIBRARY.glob("**/*.md"))[:50]:
        try:
            fm, _ = fio.read(md_path)
            lines.append(f"- {fm.get('id', md_path.stem)} ({fm.get('type', '?')})")
        except Exception:
            continue
    return "\n".join(lines) or "No canon entities yet."


def _unique_output(stem: str) -> Path:
    _PROCESSING.mkdir(parents=True, exist_ok=True)
    p = _PROCESSING / f"{stem}.md"
    if not p.exists():
        return p
    counter = 1
    while True:
        p = _PROCESSING / f"{stem}-{counter:02d}.md"
        if not p.exists():
            return p
        counter += 1


# ---------------------------------------------------------------------------
# NPC draft writer
# ---------------------------------------------------------------------------

def _write_npc_draft(
    path: Path,
    npc: NPCLLMOutput,
    image_rel: str,
    scenario: dict,
    sha256: str = "",
) -> str:
    """Writes the NPC draft. Returns its uuid so callers can log it against
    the source image's own hash/uuid for end-to-end traceability."""
    today = date.today().isoformat()
    slug  = path.stem
    rels  = [f"[[{scenario['id']}]]"] + [r for r in npc.relationships if r != f"[[{scenario['id']}]]"]
    npc_uuid = str(_uuid.uuid4())

    frontmatter: dict[str, Any] = {
        "id":          slug,
        "uuid":        npc_uuid,
        "type":        "npc",
        "status":      "draft",
        "quality":     0,
        "created":     today,
        "updated":     today,
        "tags":        ["npc"],
        "source":      [image_rel],
        "sha256":      sha256,
        "reviewed":    False,
        "relationships": rels,
        "name":        npc.name,
        "ancestry":    npc.ancestry,
        "heritage":    npc.heritage,
        "class":       npc.char_class,
        "level":       npc.level,
        "background":  npc.background,
        "str":         npc.str_mod,
        "dex":         npc.dex_mod,
        "con":         npc.con_mod,
        "int":         npc.int_mod,
        "wis":         npc.wis_mod,
        "cha":         npc.cha_mod,
        "trait":       npc.trait,
        "ideal":       npc.ideal,
        "bond":        npc.bond,
        "flaw":        npc.flaw,
        "role":        npc.role,
    }

    if npc.needs_human_review:
        frontmatter["needs_human_review"] = True

    body = (
        f"\n## Description\n\n{npc.description}\n\n"
        f"## Abilities\n\n"
        + "\n".join(f"- {a}" for a in npc.abilities) + "\n\n"
    )
    if npc.tactics:
        body += f"## Tactics\n\n{npc.tactics}\n\n"
    if npc.plot_hooks:
        body += "## Plot Hooks\n\n" + "\n".join(f"- {h}" for h in npc.plot_hooks) + "\n\n"
    body += "## Related\n\n" + "\n".join(rels) + "\n"

    if npc.needs_human_review:
        body += (
            f"\n## Reviewer Notes\n\n"
            f"> Auto-flagged: {npc.review_notes}\n"
        )

    FrontmatterIO().write(path, frontmatter, body)
    return npc_uuid


# ---------------------------------------------------------------------------
# Core batch implementation
# ---------------------------------------------------------------------------

def _run_batch_impl(log: "_Logger") -> tuple[int, int]:
    """Process up to BATCH_SIZE pending image×scenario pairs with reflexion loop.

    Returns (count_processed, count_failed).
    """
    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("Qwen3-VL (localhost:1234) offline — skipping batch")
        return 0, 0

    prompt_tpl = (
        _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists()
        else "Generate NPC JSON for scenario: {scenario_name}. {scenario_description}"
    )

    generator    = _NPCGeneratorImpl(client, prompt_tpl)
    scenarios    = [s for s in _load_scenarios() if s.get("active", True)]
    vision_state = _load_vision_state()
    proc_npcs    = _load_proc_npcs()
    queue        = _load_queue()
    canon_ctx    = _canon_context()

    eligible_images = [
        (img_key, entry)
        for img_key, entry in vision_state.get("images", {}).items()
        if entry.get("type") in _CHARACTER_TYPES and entry.get("status") == "ok"
        if queue.get(entry.get("path", ""), {}).get("agents", {}).get("lore") != "paused"
    ]

    pairs: list[tuple[str, dict, dict]] = []
    for img_key, img_entry in eligible_images:
        for scenario in scenarios:
            composite_key = f"{img_entry['path']}|{scenario['id']}"
            if composite_key not in proc_npcs:
                pairs.append((composite_key, img_entry, scenario))

    if not pairs:
        log.info("No unprocessed image×scenario pairs")
        return 0, 0

    batch  = pairs[:BATCH_SIZE]
    count  = 0
    failed = 0
    log.info(f"Batch: {len(batch)} of {len(pairs)} pair(s)")

    for composite_key, img_entry, scenario in batch:
        img_path = _PROJECT_ROOT / img_entry["path"]
        img_rel  = img_entry["path"]
        img_tag  = image_tag(sha256=img_entry.get("sha256"), uuid=img_entry.get("uuid"), path=img_rel)

        if not img_path.exists():
            log.warning(f"Image gone{img_tag}")
            proc_npcs[composite_key] = {
                "imageKey":    img_entry.get("sha256", ""),
                "scenarioId":  scenario["id"],
                "outputPath":  "",
                "processedAt": datetime.now(timezone.utc).isoformat(),
                "status":      "error-image",
            }
            _save_proc_npcs(proc_npcs)
            failed += 1
            continue

        # --- Initial generation ---
        try:
            first_output = generator.generate(img_path, scenario, canon_ctx)
        except LLMOfflineError:
            log.warning("LLM offline — aborting batch")
            break
        except (LLMResponseError, Exception) as exc:
            log.error(f"NPC generation failed (× {scenario['id']}): {exc}{img_tag}")
            proc_npcs[composite_key] = {
                "imageKey":    img_entry.get("sha256", ""),
                "scenarioId":  scenario["id"],
                "outputPath":  "",
                "processedAt": datetime.now(timezone.utc).isoformat(),
                "status":      "error-llm",
            }
            _save_proc_npcs(proc_npcs)
            failed += 1
            continue

        # --- Reflexion loop (P1) ---
        npc = _score_and_revise(generator, img_path, scenario, canon_ctx, first_output, img_rel)
        if npc.needs_human_review:
            log.warning(
                f"NPC flagged for human review after {_MAX_REVISIONS} rounds: "
                f"{img_path.name} × {scenario['id']}"
            )

        # --- Write draft ---
        from nexus.shared import to_slug as _to_slug  # noqa: PLC0415
        arc      = scenario.get("arc", "a0").lower()
        stem     = f"npc-{_to_slug(img_path.stem)}-{arc}"
        out_path = _unique_output(stem)

        try:
            npc_uuid = _write_npc_draft(out_path, npc, img_rel, scenario, sha256=img_entry.get("sha256", ""))
        except Exception as exc:
            log.error(f"Write failed for {out_path.name}: {exc}")
            proc_npcs[composite_key] = {
                "imageKey":    img_entry.get("sha256", ""),
                "scenarioId":  scenario["id"],
                "outputPath":  "",
                "processedAt": datetime.now(timezone.utc).isoformat(),
                "status":      "error-write",
            }
            _save_proc_npcs(proc_npcs)
            failed += 1
            continue

        out_rel = out_path.relative_to(_PROJECT_ROOT).as_posix()
        proc_npcs[composite_key] = {
            "imageKey":    img_entry.get("sha256", ""),
            "scenarioId":  scenario["id"],
            "outputPath":  out_rel,
            "processedAt": datetime.now(timezone.utc).isoformat(),
            "status":      "ok",
        }
        _save_proc_npcs(proc_npcs)

        if img_rel in queue and isinstance(queue[img_rel].get("agents"), dict):
            def _mark_lore_done(entry: dict) -> Optional[str]:
                entry.setdefault("agents", {})["lore"] = "done"
                return None

            locked_update_queue_entry(_QUEUE_FILE, img_rel, _mark_lore_done)

        log.info(
            f"Generated NPC: {out_path.name} ({scenario['name']})"
            f"{image_tag(sha256=img_entry.get('sha256'), uuid=npc_uuid, path=out_rel)}"
        )
        count += 1

    return count, failed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log = _Logger()
    t0  = log.start()
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    count, failed = _run_batch_impl(log)
    log.done(t0, count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from nexus.shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "load_canon_context",
        "description": "Load approved entities from 02-Library/ as relationship context for NPC generation. Returns entity count.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_pending_pairs",
        "description": "List unprocessed (image, scenario) pairs ready for NPC generation. Returns JSON array of pairs.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "generate_npc",
        "description": (
            "Generate a full PF2e NPC sheet from a character image + scenario using the local vision LLM. "
            "Applies reflexion loop (up to 2 critique rounds). "
            "Writes draft to 01-Processing/. Flags low-quality outputs with needs_human_review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_key":   {"type": "string", "description": "SHA256 key of the image in processed-images.json"},
                "scenario_id": {"type": "string", "description": "Scenario ID from scenarios.json"},
            },
            "required": ["image_key", "scenario_id"],
        },
    },
    {
        "name": "run_batch",
        "description": (
            "Process up to BATCH_SIZE pending image×scenario pairs with reflexion loop. "
            "Returns count generated."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import io, contextlib, json as _json  # noqa: E401
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    if name == "load_canon_context":
        ctx   = _canon_context()
        lines = [ln for ln in ctx.splitlines() if ln.strip()]
        return f"Canon context: {len(lines)} lines"

    if name == "list_pending_pairs":
        vision_state = _load_vision_state()
        proc_npcs    = _load_proc_npcs()
        scenarios    = [s for s in _load_scenarios() if s.get("active")]
        images       = vision_state.get("images", {})
        pending: list[dict] = []
        for key, img in images.items():
            if img.get("type") not in ("portrait", "body"):
                continue
            for sc in scenarios:
                composite = f"{key}|{sc['id']}"
                if composite not in proc_npcs:
                    pending.append({
                        "image_key":   key,
                        "scenario_id": sc["id"],
                        "image_path":  img.get("path", ""),
                    })
        return _json.dumps(pending[:20])

    if name in ("generate_npc", "run_batch"):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")
