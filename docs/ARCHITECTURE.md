# Architecture

## High-level dataflow

```
HTTP / WS clients
       │
       ▼
┌───────────────────────────────────────────────────────────────┐
│                      FastAPI (Phase 4)                        │
│  REST routes  ──────────────▶  Postgres / SQLite (audit log)  │
│  WS routes    ◀──────────────  Redis Streams (replay buffer)  │
│  Background task scheduler                                    │
└───────────┬───────────────────────────────────────────────────┘
            │ schedules
            ▼
┌───────────────────────────────────────────────────────────────┐
│                  LangGraph state machine (Phase 3)            │
│                                                               │
│  patient_intake                                               │
│       │                                                       │
│       ▼                                                       │
│  parallel_initial_dx (Send → 5 specialists)                   │
│       │                                                       │
│       ▼                                                       │
│  bayesian_update ── aggregates per-specialist Ddx → team Ddx  │
│       │                                                       │
│       ▼                                                       │
│  caddick_synthesis (LLM synthesis + deterministic routing)    │
│       │                                                       │
│       ▼                                                       │
│  convergence_check ──┬─── converged → final_report → END      │
│       │              │                                        │
│       │              └─── stagnation hint (advisory)          │
│       ▼                                                       │
│  specialist_turn (Send → 1-3 specialists)                     │
│       │                                                       │
│       └────── loop back to bayesian_update                    │
└───────────────────────────────────────────────────────────────┘
            │ tool calls (during specialist turns)
            ▼
┌───────────────────────────────────────────────────────────────┐
│             Medical Intelligence Layer (Phase 2)              │
│                                                               │
│  ToolDispatcher (auto-derives OpenAI schemas from Pydantic)   │
│           │                                                   │
│  ┌────────┴─────────┬──────────────┬─────────────────┐       │
│  ▼                  ▼              ▼                 ▼       │
│ Bayesian          Neo4j         ChromaDB         Curated     │
│  engine        (Hetionet)        (MedQA)         red-flags   │
│  (SQLite)                                                    │
└───────────────────────────────────────────────────────────────┘
```

## Module dependency

```
api ───────────► orchestration ───────► agents
 │                    │
 │                    │
 ▼                    ▼
schemas          intelligence ──────► db (Bayes), rag (Chroma), Neo4j
 │
 ▼
models (core Pydantic types — depended on by everything)
```

## State persistence layers

| Store | Role | Lifetime |
|---|---|---|
| Postgres / SQLite | Cases table, audit log, agent_responses, tool_calls | Permanent |
| Redis | Live case state, sequence counter, event Stream (cap 500), pub/sub channels | 24h TTL |
| Neo4j | Hetionet knowledge graph | Permanent |
| ChromaDB | MedQA vector index | Permanent |
| SQLite (bayes.db) | Disease priors, symptom likelihoods, test characteristics | Permanent |

## Multi-client fan-out

```
                 ┌───────────────────────────┐
   browser ─────►│  WS /ws/cases/{id}        │
   websocat ────►│      (3 clients on same   │
   replay tool ─►│       case_id)            │
                 └────────────┬──────────────┘
                              │ subscribes to channel
                              ▼
                  case:{case_id}:stream  ◀── PUBLISH ─── runner
```

Each client gets every event. New connections replay from Redis Stream (or Postgres if past the 500-event cap), then live-tail via pub/sub.

## Failure modes

| Failure | Behavior |
|---|---|
| Neo4j down | MI graph tools return `{"error": "graph unavailable"}`; agents continue |
| Redis down | Pub/sub broken, single subscriber per case; falls back to Postgres polling |
| Postgres down | Audit log writes skipped (logged warning); case state in Redis unaffected |
| LLM 5xx | Retry 3× with exp backoff; emit `error` event with `recoverable=true` on final failure |
| Schema parse failure | One reformatting retry then escalate |
| Client WS disconnect | Case continues; reconnect with `?from_sequence=N` |
| Server crash | On startup: scan `cases:active`, mark interrupted in Postgres |
