"""wiki.tools

Concrete module: 03_compile_wiki.py
Implements: IWikiCompiler + BaseAgent
Dependencies: ILLMClient (local_router), IStateStore (inbox-queue.json)
Targets: inbox-queue.json entries where agents.wiki == "pending"
"""
