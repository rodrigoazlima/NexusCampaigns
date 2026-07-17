"""nexus.runtime.chat - dispatches one dashboard chat-queue item (--chat-id),
a synchronous request/response path independent of the scheduler cycle."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

from .dispatch_config import extract_dispatch_sub, load_agent_dispatch
from .log import make_logger
from .paths import AGENT_NAME_TO_TASK, AGENTS_DIR, CHAT_QUEUE, SYSTEM_STATE


def read_chat_queue() -> list[dict]:
    if not CHAT_QUEUE.exists():
        return []
    try:
        data = json.loads(CHAT_QUEUE.read_text(encoding="utf-8").lstrip("﻿"))
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_chat_queue(items: list[dict]) -> None:
    SYSTEM_STATE.mkdir(parents=True, exist_ok=True)
    tmp = CHAT_QUEUE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    tmp.replace(CHAT_QUEUE)


def chat_update(items: list[dict], chat_id: str, **fields) -> None:
    for item in items:
        if item.get("id") == chat_id:
            item.update(fields)
            item["updatedAt"] = datetime.now(timezone.utc).isoformat()
            break


def load_system_prompt(agent_name: str) -> str:
    candidates = [
        AGENTS_DIR / agent_name / "prompts" / "system.md",
        AGENTS_DIR / agent_name / "prompts" / "system.txt",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return (
        "You are a Dungeon Master knowledge assistant for a tabletop RPG campaign. "
        "Help with worldbuilding, NPC creation, locations, quests, factions, lore, and narrative. "
        "Be concise, creative, and specific."
    )


def call_lm_studio(cfg: dict, system: str, user_message: str) -> str:
    """Send chat message to LM Studio (OpenAI-compatible) endpoint."""
    base_url   = cfg["base_url"].rstrip("/")
    url        = f"{base_url}/chat/completions"
    timeout_s  = int(cfg.get("timeout_seconds", 120))
    payload    = {
        "model":       cfg["model"],
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_message},
        ],
        "temperature": float(cfg.get("temperature", 0.0)),
        "max_tokens":  int(cfg.get("max_tokens", 2048)),
        "stream":      False,
    }
    body    = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer lm-studio"}
    req     = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def call_claude(cfg: dict, system: str, user_message: str) -> str:
    """Send chat message to Anthropic Claude API."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client   = anthropic.Anthropic(api_key=api_key, timeout=float(cfg.get("timeout_seconds", 120)))
    response = client.messages.create(
        model=cfg.get("model", "claude-haiku-4-5-20251001"),
        max_tokens=int(cfg.get("max_tokens", 2048)),
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(
        block.text for block in response.content if block.type == "text"
    )


def dispatch_chat(chat_id: str) -> int:
    """Dispatch a single chat queue item by ID. Returns exit code."""
    log = make_logger("chat")

    items = read_chat_queue()
    item  = next((i for i in items if i.get("id") == chat_id), None)
    if item is None:
        log.error(f"Chat item {chat_id!r} not found in queue")
        return 1

    agent_name  = item.get("agentName", "")
    user_message = item.get("message", "")
    task_id     = AGENT_NAME_TO_TASK.get(agent_name, f"{agent_name}-agent")

    chat_update(items, chat_id, status="processing")
    write_chat_queue(items)

    log.info(f"Chat dispatch: agent={agent_name} task={task_id} id={chat_id}")

    try:
        dispatch_cfg = load_agent_dispatch(task_id, log)
        if dispatch_cfg is None:
            raise RuntimeError(f"Cannot load dispatch config for task {task_id!r}")

        sub = extract_dispatch_sub(dispatch_cfg)
        system = load_system_prompt(agent_name)
        dispatch_type = dispatch_cfg.type

        if dispatch_type in ("lm-studio", "openai-api"):
            response = call_lm_studio(sub, system, user_message)
        elif dispatch_type == "claude-api":
            response = call_claude(sub, system, user_message)
        else:
            raise RuntimeError(f"Unsupported dispatch type for chat: {dispatch_type!r}")

        chat_update(items, chat_id, status="done", response=response)
        write_chat_queue(items)
        log.info(f"Chat done: {chat_id}")
        return 0

    except Exception as exc:
        log.error(f"Chat dispatch failed: {exc}")
        chat_update(items, chat_id, status="error", error=str(exc))
        write_chat_queue(items)
        return 1
