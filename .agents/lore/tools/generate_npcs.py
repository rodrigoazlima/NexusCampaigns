"""lore.tools.09_generate_npcs

Generates PF2e NPC sheets from classified character images × active scenarios.
No LLM → skip gracefully. Batch: 10 image×scenario pairs per run.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    FrontmatterIO,
    LLMClient,
    LLMOfflineError,
    LLMResponseError,
    NPCLLMOutput,
)
from shared.config import LLMEndpointConfig  # noqa: E402

TASK_ID         = "lore-agent"
SCRIPT_BASENAME = "generate_npcs.py"
BATCH_SIZE      = 10

_VAULT_ROOT   = _PROJECT_ROOT / "knowledge-base"
_PROCESSING   = _VAULT_ROOT / "01-Processing"
_LIBRARY      = _VAULT_ROOT / "02-Library"
_AGENT_STATE  = _AGENTS_DIR / "lore" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_SHARED_STATE = _PROJECT_ROOT / ".shared" / "state"
_MASTER_LOG   = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_VISION_STATE = _AGENTS_DIR / "vision" / "state" / "processed-images.json"
_PROC_NPCS    = _AGENT_STATE / "processed-npcs.json"
_SCENARIOS    = _AGENT_STATE / "scenarios.json"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"
_PROMPT_FILE  = _AGENTS_DIR / "lore" / "prompts" / "generate-npc.txt"

_LLM_CFG = LLMEndpointConfig(
    url      = "http://localhost:1234/v1/chat/completions",
    model    = "qwen3-vl-4b-instruct",
    type     = "vision",
    provider = "lmstudio",
)

_CHARACTER_TYPES = frozenset({"portrait", "body", "token"})


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


def _load_scenarios() -> list[dict]:
    if not _SCENARIOS.exists():
        from shared.defaults import SCENARIOS_DEFAULT
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


def _save_queue(queue: dict) -> None:
    _SHARED_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
    tmp.replace(_QUEUE_FILE)


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


def _write_npc_draft(path: Path, npc: NPCLLMOutput, image_rel: str, scenario: dict) -> None:
    today = date.today().isoformat()
    slug  = path.stem
    rels  = [f"[[{scenario['id']}]]"] + [r for r in npc.relationships if r != f"[[{scenario['id']}]]"]
    frontmatter = {
        "id":          slug,
        "type":        "npc",
        "status":      "draft",
        "quality":     0,
        "created":     today,
        "updated":     today,
        "tags":        ["npc"],
        "source":      [image_rel],
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
    body = (
        f"\n## Description\n\n{npc.description}\n\n"
        f"## Abilities\n\n"
        + "\n".join(f"- {a}" for a in npc.abilities) + "\n\n"
        f"## Related\n\n"
        + "\n".join(rels) + "\n"
    )
    FrontmatterIO().write(path, frontmatter, body)


def main() -> None:
    log = _Logger()
    t0  = log.start()
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("Qwen3-VL (localhost:1234) offline — skipping batch")
        log.done(t0)
        sys.exit(0)

    scenarios    = [s for s in _load_scenarios() if s.get("active", True)]
    vision_state = _load_vision_state()
    proc_npcs    = _load_proc_npcs()
    queue        = _load_queue()
    canon_ctx    = _canon_context()

    prompt_tpl = (
        _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists()
        else "Generate NPC JSON for scenario: {scenario_name}. {scenario_description}"
    )

    # Build unprocessed pairs
    eligible_images = [
        (img_key, entry)
        for img_key, entry in vision_state.get("images", {}).items()
        if entry.get("type") in _CHARACTER_TYPES and entry.get("status") == "ok"
    ]

    pairs: list[tuple[str, dict, dict]] = []
    for img_key, img_entry in eligible_images:
        for scenario in scenarios:
            composite_key = f"{img_entry['path']}|{scenario['id']}"
            if composite_key not in proc_npcs:
                pairs.append((composite_key, img_entry, scenario))

    if not pairs:
        log.info("No unprocessed image×scenario pairs")
        log.done(t0)
        sys.exit(0)

    batch   = pairs[:BATCH_SIZE]
    count   = 0
    failed  = 0
    log.info(f"Batch: {len(batch)} of {len(pairs)} pair(s)")

    for composite_key, img_entry, scenario in batch:
        img_path = _PROJECT_ROOT / img_entry["path"]
        img_rel  = img_entry["path"]

        if not img_path.exists():
            log.warning(f"Image gone: {img_rel}")
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

        prompt = (
            prompt_tpl
            .replace("{scenario_name}", scenario["name"])
            .replace("{scenario_description}", scenario["description"])
            .replace("{arc}", scenario.get("arc", ""))
            .replace("{canon_context}", canon_ctx)
        )

        try:
            raw = client.vision_chat(
                img_path, prompt,
                system="You are a Pathfinder 2e NPC generator. Return ONLY valid JSON.",
                max_tokens=800,
            )
            npc = NPCLLMOutput.model_validate(raw)
        except LLMOfflineError:
            log.warning("LLM offline — aborting batch")
            break
        except (LLMResponseError, Exception) as exc:
            log.error(f"NPC generation failed ({img_path.name} × {scenario['id']}): {exc}")
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

        from shared import to_slug as _to_slug
        stem     = f"{_to_slug(img_path.stem)}-{scenario['id']}"
        out_path = _unique_output(stem)

        try:
            _write_npc_draft(out_path, npc, img_rel, scenario)
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
            queue[img_rel]["agents"]["lore"] = "done"
            _save_queue(queue)

        log.info(f"Generated NPC: {out_path.name} ({scenario['name']})")
        count += 1

    log.done(t0, count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

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
        "description": "Generate a full PF2e NPC sheet from a character image + scenario using the local vision LLM. Writes draft to 01-Processing/.",
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
        "description": "Process up to BATCH_SIZE pending image×scenario pairs. Returns count generated.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import io, contextlib, json as _json
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    if name == "load_canon_context":
        ctx = _canon_context()
        lines = [l for l in ctx.splitlines() if l.strip()]
        return f"Canon context: {len(lines)} lines"

    if name == "list_pending_pairs":
        vision_state = _load_vision_state()
        proc_npcs = _load_proc_npcs()
        scenarios = [s for s in _load_scenarios() if s.get("active")]
        images = vision_state.get("images", {})
        pending = []
        for key, img in images.items():
            if img.get("type") not in ("portrait", "body"):
                continue
            for sc in scenarios:
                composite = f"{key}|{sc['id']}"
                if composite not in proc_npcs:
                    pending.append({"image_key": key, "scenario_id": sc["id"], "image_path": img.get("path", "")})
        return _json.dumps(pending[:20])

    if name == "generate_npc":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "NPC generation run complete"

    if name == "run_batch":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")
