"""repair.tools

Concrete module: 12_repair_agent.py
Implements: BaseAgent
Repairs: stale-lock, missing-directory, missing-image-ref
Detects: overdue tasks (> 2× intervalSeconds)
No LLM calls. Cannot restart OS services.
"""
