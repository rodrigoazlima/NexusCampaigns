"""nexus.runtime — the scheduler, split by responsibility.

paths       — filesystem paths and static constants
log         — Logger construction
lock        — single-instance process lock (runner.lock)
state       — tasks-state.json I/O
metrics     — per-run metrics (agent-metrics.json)
costs       — per-run token/cost tracking (state/costs/*.json)
registry_yaml — registry.yaml reads (execution order, pipeline mode, agent.json synthesis)
dispatch_config — task_id -> AgentDispatchConfig resolution
discovery   — agents/*/agent.json -> ordered task list
preconditions — cheap "has work?" checks that skip a dispatch
signals     — signal-bus triggered-task detection
committer   — scoped git add+commit, shared by agents and workers
worker_loop — in-process static worker scheduling
chat        — dashboard chat-queue dispatch (--chat-id)
scheduler   — Runtime, the IOrchestrator implementation
cli         — argument parsing and process entrypoint (main())

See system/src/nexus/runner.py for the CLI entrypoint this package backs.
"""
