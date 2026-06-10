"""lore.tools

Concrete module: generate_npcs.py
Implements: INPCGenerator + BaseAgent
Dependencies: ILLMClient (vision_llm), vision state (processed-images.json),
              IStateStore (processed-npcs.json, scenarios.json)
Read-only: 02-Library/ (canon context injection, max 50 entities)
"""
