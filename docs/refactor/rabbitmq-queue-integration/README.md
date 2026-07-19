# Refactor: RabbitMQ queue integration - necessity review + phased plan

Status: PROPOSED (not started) - `infra/` already stands up a local RabbitMQ
sandbox (Podman, 12 queues: 8 `worker.*` + 4 `agent.*` on a `nexus.pipeline`
topic exchange) per explicit request. This doc is the judgment layer on top:
should `nexus.runner` actually consume it, and if so, which queues.

Related: [remove-agentic-useless-static-code/README.md](../remove-agentic-useless-static-code/README.md)
already ran this exact question once and landed on "no broker" - see its
Decision log, "Queue store" row. This doc re-opens the question with the
current worker/agent set and gives a different answer for a narrow subset.

## Current architecture (why this isn't a free win)

Facts pulled from the running code, not assumption:

1. **Single-instance runner lock** (`nexus/runtime/lock.py`, `acquire_lock`):
   the whole scheduler is designed so exactly one process runs at a time -
   a stale-lock override, not a coordination primitive. Any RabbitMQ
   consumer model that assumes N independent workers pulling from a queue
   violates this invariant unless workers are pulled out of the runner into
   their own standalone processes. That's a bigger redesign than "add a
   queue" - it's "remove the single-instance guarantee and rebuild what it
   protected."
2. **Worker loop is single-threaded, sequential, no concurrency at all**
   (`nexus/runtime/worker_loop.py::run_workers`): one worker at a time, one
   item at a time (`for item in items: worker.handle(item)`), inside one
   process. This is the actual place where a queue's fan-out would show up
   as a real speedup - today it doesn't exist here at all.
3. **Agent dispatch concurrency exists but is off by default**
   (`nexus/runtime/scheduler.py::run_cycle`, `pipeline_mode: sync` in
   `registry.yaml`). Even flipped to `async`, all four active agents
   (vision, lore, classification, wiki) hit **the same two local LLM
   endpoints** (`vision_llm` and `local_router`, both `http://localhost:1234`
   in `registry.yaml`). A single local LM Studio instance serializes
   inference regardless of how many callers queue up - concurrency at the
   orchestration layer doesn't create concurrency at the bottleneck.
4. **Git commits are serialized on purpose** (`FileLock` around
   `STATE_JSON`, `commit_scoped` per task/worker). Two consumers processing
   items whose `commit_scope` overlaps (e.g. `worker.ingestion` and
   `worker.token` both touch `.knowledge-base/00-Inbox/images`) would need
   the same cross-process serialization RabbitMQ doesn't give you for free.
5. **Batch sizes are small** (`registry.yaml` `workers:` block): ingestion
   25, thumbnails 10, token 10, wikilink 20, shortfiles 50 items *per
   cycle*. Broker round-trip + ack overhead per message is not obviously
   cheaper than an in-process function call at this volume.
6. **`inbox-queue.json` already is the work-tracking queue** - slot
   lifecycle (`pending → done/skip/error`), atomic writes via
   `locked_update_queue_entry`, already the source of truth per the prior
   refactor's decision log. A broker alongside it is a second, competing
   queue unless one fully replaces the other.

None of this says "RabbitMQ is wrong here forever." It says: the queue
would be sitting on top of a pipeline that is deliberately single-process,
so most of what a broker buys you (independent consumers, backpressure
across machines, at-least-once delivery across process crashes) has no
consumer on the other end yet.

## Verdict per queue

| Queue | Kind | Verdict | Why |
|---|---|---|---|
| `worker.token` | queue | **Conditional keep** | Real CPU/I-O cost per item (`nexus/workers/token.py` - PIL compositing). Only worker where multi-consumer fan-out would show up as wall-clock improvement, *if* item volume grows past what one process handles per cycle. |
| `worker.thumbnails` | queue | **Conditional keep** | Same profile as token (image resize), smaller cost per item. Bundle with token if this is ever built - don't build one without the other. |
| `worker.ingestion` | queue | **Disposable now** | File moves/docx conversion, moderate cost, but it's the *producer* for the other queue workers (`inbox-queue.json` entries) - queuing the producer adds a hop before the real bottleneck (LLM agents) without fixing it. |
| `worker.wikilink` | queue | **Disposable** | Cheap per-item (frontmatter regex/index lookup). Broker overhead likely exceeds the work itself. |
| `worker.shortfiles` | queue | **Disposable** | Registry.yaml's own comment calls it "cheap per-item work," batch_size 50. Textbook case where queuing adds latency, not throughput. |
| `worker.report` | scheduled | **Disposable, wrong shape** | Cron-like, single fire, reads the whole automation.log - there's no "item" to queue, one invocation does the whole job. |
| `worker.cleanup` | scheduled | **Disposable, wrong shape** | Same - one global sweep, not per-item work. |
| `worker.maintenance` | scheduled + signal | **Actively wrong to queue** | Repairs stale locks and poison-pill slots. Running it from multiple concurrent consumers is the exact race condition it exists to prevent. Must stay single-instance. |
| `agent.vision` / `agent.lore` | agent | **Disposable now** | Both bottleneck on the same local `vision_llm` endpoint (single LM Studio instance). Queuing requests you can't actually run in parallel just adds a broker hop before the same serialized inference. |
| `agent.classification` / `agent.wiki` | agent | **Disposable now** | Same reasoning, `local_router` endpoint. Becomes worth revisiting only if dispatch moves to a cloud API with real concurrent-request headroom (`claude-api`, `openrouter-api` dispatch types already exist in `nexus/shared/runners/`). |

**Net: 2 of 12 conditionally justified, 0 justified today, 10 disposable
under the current single-process, single-LLM-backend architecture.**

## What would actually justify turning this on

Don't build ahead of these triggers - each is a concrete, observable signal,
not a guess:

- **Ingestion backlog measurably exceeds one cycle's batch_size on a
  recurring basis** (check `system/state/workers/token/` progress vs.
  `inbox-queue.json` pending count over time) → `worker.token` +
  `worker.thumbnails` become real candidates for a multi-consumer pool.
- **Agent dispatch moves off local LM Studio to a provider with real
  concurrency** (cloud API key configured, `pipeline_mode: async` actually
  produces wall-clock improvement in `state/agent-metrics.json`) →
  `agent.*` queues become worth wiring as a dispatch buffer.
- **Cross-machine execution becomes a requirement** (e.g. offloading
  thumbnail/token generation to a second host) - this is the only trigger
  that unconditionally justifies a broker, since in-process function calls
  can't cross machines.

If none of these are true yet, don't wire `infra/` into `nexus.runner` -
keep it as a standing local sandbox for prototyping and move on.

## Phased plan (if/when a trigger above fires)

**Phase 0 - prerequisite, blocks everything else**
Decide the concurrency model before touching workers: either (a) the runner
process itself gets an internal thread/process pool consuming from
RabbitMQ while staying the single git-committing authority (lower risk,
matches the existing single-instance lock), or (b) workers become
standalone consumer processes and the single-instance lock in
`nexus/runtime/lock.py` is relaxed to a per-worker-kind lock. (a) is the
default recommendation - it gets the fan-out benefit for CPU-bound item
processing without touching the commit-serialization or maintenance-worker
safety invariants above.

**Phase 1 - producer/consumer split for `worker.token` + `worker.thumbnails` only**
1. `worker.pending()` publishes to `worker.token` / `worker.thumbnails`
   instead of (or in addition to) returning the list directly - keep
   `inbox-queue.json` as the durable source of truth, RabbitMQ becomes a
   work-distribution layer on top, not a replacement.
2. Consumer side: a bounded thread pool inside the same runner process
   (per Phase 0 option (a)) pulls from the queue and calls the *existing*
   `handle(item)` unchanged - no change to worker contract
   (`nexus/workers/base.py`).
3. `commit_scoped` calls stay serialized behind the existing `FileLock` -
   consumers hand results back to the main loop rather than committing
   directly, so the git-commit invariant from
   `worker-contract.spec.md` doesn't need to change.
4. Feature-flag: `queue_backend: none | rabbitmq` in `registry.yaml`,
   default `none` - matches how `workers_enabled` was introduced in the
   prior refactor.

**Phase 2 - measure before going further**
Compare `state/agent-metrics.json` / worker duration_ms before and after.
If the broker hop doesn't beat in-process sequential processing at current
volume, stop here - don't proceed to Phase 3 speculatively.

**Phase 3 - agent dispatch buffer (only if the cloud-API trigger fires)**
Same shape as Phase 1, applied to `agent.vision` / `agent.lore` /
`agent.classification` / `agent.wiki`, gated on dispatch type being a
concurrency-capable backend (not `lm-studio`).

**Explicitly out of scope, don't build:**
- Queuing `worker.report` / `worker.cleanup` / `worker.maintenance` - wrong
  shape (single global sweep, not per-item), and maintenance queuing is
  actively unsafe (see Verdict table).
- Removing `inbox-queue.json` - it stays the durable state; RabbitMQ (if
  adopted) is additive, not a replacement, per the prior refactor's
  decision log.
- Multi-machine consumer deployment - no current requirement for it; the
  vault is a single local working tree (`.knowledge-base/` junction).

## Decision log

| Decision | Choice | Why |
|---|---|---|
| Build now vs. wait for trigger | **Wait** | 10 of 12 queues have no consumer-side concurrency to exploit under the current single-process runner; building the wiring first is solving a problem that doesn't exist yet. |
| Which queues are worth it at all | `worker.token`, `worker.thumbnails` only | Only two with real per-item CPU/I-O cost and independent (non-overlapping-enough) commit scopes. |
| Replace `inbox-queue.json`? | No | Still the durable source of truth; a broker adds distribution, not persistence guarantees the pipeline needs. |
| Runner concurrency model | In-process thread pool (Phase 0 option a) over standalone consumer processes | Preserves the single-instance lock and commit-serialization invariants instead of redesigning around them. |
| Agent queues | Deferred until dispatch backend has real concurrency | Local LM Studio is the actual bottleneck; queuing in front of a serial backend doesn't parallelize anything. |
| Scheduled workers (report/cleanup/maintenance) | Never queue | Wrong unit of work (global sweep, not per-item); maintenance queuing is a correctness hazard, not just a non-benefit. |
