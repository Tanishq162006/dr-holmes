# Phase log

This is the build journal. Each phase represents one focused architectural milestone — kept independently testable so regressions stay local.

---

## Phase 1 — 2-agent CLI skeleton ✅

**Goal:** Get two agents (Holmes on Grok, Foreman on GPT-4o) deliberating on a hardcoded case end-to-end with streaming output.

**What landed:**
- `dr_holmes/agents/{base,holmes,foreman}.py` — OpenAI-compatible streaming for both Grok and GPT-4o
- `dr_holmes/graph/{state,nodes,builder}.py` — LangGraph StateGraph with conditional routing
- `dr_holmes/cli.py` — Rich-based CLI with token streaming + human inject prompt
- `dr_holmes/rag/retriever.py` — ChromaDB index over MedQA (500-entry default)
- `dr_holmes/models/core.py` — `PatientCase`, `AgentMessage`, `Differential`, `DiagnosticState`

**Provider note:** No Anthropic key, so Holmes runs on Grok via the OpenAI-compatible xAI endpoint.

---

## Phase 2 — Medical Intelligence Layer ✅

**Goal:** Replace dumb similarity-search RAG with a structured tool API that all agents call. Shared probabilistic ground truth, knowledge graph traversal, specialty-biased queries.

**What landed:**
- `dr_holmes/intelligence/medical.py` — `MedicalIntelligence` class with 9 tools
- `dr_holmes/intelligence/dispatcher.py` — Auto-generates OpenAI tool schemas from Pydantic input models
- `dr_holmes/db/{schema,bayes}.py` — SQLAlchemy 2.0 Bayesian engine (log-space, LR cap = 50)
- `scripts/load_ddxplus.py` — 1.025M rows → 49 disease priors + 882 symptom likelihoods
- `scripts/load_hetionet.py` — 8,263 nodes + 154,077 edges into Neo4j (Disease, Symptom, Compound, Anatomy, SideEffect)
- Renamed agents to `Hauser`/`Forman` to avoid Holmes/Foreman name collision in show canon

**Tool API:**
1. `get_differentials_for_symptoms(symptoms, demographics, bias)` — biased ranked Ddx
2. `get_discriminating_tests(differentials)` — info-gain ranked tests
3. `update_probabilities(prior_dx, evidence)` — Bayesian posterior
4. `get_typical_presentation(disease)` — graph-derived feature list
5. `get_drug_interactions(meds)` — from Hetionet Compound-INTERACTS-Compound
6. `get_red_flags(symptoms)` — curated don't-miss list (PE, MI, sepsis, AAA, meningitis, stroke, …)
7. `search_case_reports(query)` — vector retrieval
8. `get_disease_relationships(disease)` — full subgraph (mimics, complications, treatments)
9. `explain_result(test, value, demographics)` — reference range + interpretation

**Calibration data points:** Bayesian update on `[fever, cough, sore throat]` over the 49-disease priors yields URTI 56%, Influenza 11%, Bronchitis 7% — clinically reasonable.

---

## Phase 3 — Full team + orchestration ✅

**Goal:** Six agents, deterministic routing, mock-LLM mode, convergence + dissent logic.

### Locked thresholds
```
CONVERGENCE_PROB  = 0.80
AGREEMENT_COUNT   = 3 / 5
AGREEMENT_PROB    = 0.50
STABILITY_DELTA   = 0.05
MAX_ROUNDS        = 6
HAUSER_INTERRUPTS_PER_CASE = 1
STAGNATION_DELTA  = 0.02
STAGNATION_ROUNDS = 2
```

### Caddick routing (pure Python, deterministic)
1. Hauser interrupt privilege (1× per case)
2. Floor requests (`request_floor=True` from any agent)
3. Unaddressed challenges → call on the targeted agent
4. Specialty match (top dx → SPECIALTY_LOOKUP)
5. Highest confidence delta from previous round
6. Round-robin among silent specialists

LLM only writes the synthesis paragraph. Routing is testable code.

### Convergence check
All four must hold:
- top dx probability ≥ 0.80
- ≥ 3 of 5 specialists have it in top-3 with prob > 0.50
- last round delta < 0.05
- 0 active unresolved challenges

A challenge is resolved when its target agent speaks in a later round.

### Aggregation: noisy-OR for ≥3-specialist agreement
When 3+ specialists agree on a dx (each with prob > 0.4), team probability uses noisy-OR:
```
team_prob = 1 − ∏(1 − p_i)   capped at 0.97
```
Otherwise weighted mean. Rationale: 3 doctors at 60% confidence each is collectively much stronger evidence than any one alone.

### Hauser dissent preservation
Even at team consensus, if Hauser's last top dx ≠ team consensus (token-set mismatch), his position is captured in `FinalReport.hauser_dissent` and rendered as a dedicated yellow CLI panel.

### Mock mode
- `MockSpecialistAgent` replays canned `AgentResponse` dicts from a fixture file
- The full LangGraph state machine, routing module, Bayesian aggregation, and CLI rendering all execute on real code
- Only the LLM call is stubbed
- Three fixtures: `case_01_easy_mi.json`, `case_02_atypical_sle.json`, `case_03_zebra_whipples.json`

### Tests
- `tests/test_phase3_orchestration.py` — 22 unit tests on routing/convergence/aggregation
- `tests/test_phase3_e2e.py` — 11 integration tests across all 3 fixtures

---

## Phase 4 — FastAPI + WebSocket backend ✅

**Goal:** Wrap the engine in a web service so Phase 5 (frontend) has something to talk to. Clean separation: engine vs. interface.

### Stack
- FastAPI + uvicorn (async)
- SQLAlchemy 2.0 async ORM, Postgres or SQLite (auto-fallback)
- Redis for live state, Streams for replay buffer (cap 500 events), pub/sub for fan-out
- Prometheus metrics via `prometheus-client`

### Routes
| Method | Path | Notes |
|---|---|---|
| POST | `/api/cases` | Create case, schedules background run |
| GET | `/api/cases` | List with filter + pagination |
| GET | `/api/cases/{id}` | Detail + final_report |
| DELETE | `/api/cases/{id}` | Cleanup |
| GET | `/api/cases/{id}/transcript` | Full audit log |
| GET | `/api/cases/{id}/differentials` | Latest Bayesian update payload |
| GET | `/api/cases/{id}/report` | Final report (409 if not concluded) |
| POST | `/api/cases/{id}/{pause,resume,conclude,evidence}` | Phase 6 hooks scaffolded |
| GET | `/api/agents` | Six profiles (provider, model, specialty, bias) |
| GET | `/api/intel/{health,diseases/{name}}` | MI debug |
| WS | `/ws/cases/{id}` | Live event stream + handshake + replay |
| GET | `/{healthz,readyz,metrics}` | Ops |

### WebSocket protocol v1
- Handshake first: `{type: handshake, server_version, accepted_commands, …}`
- Then events: `{protocol_version, sequence, case_id, event_type, timestamp, payload}`
- Reconnection: `?from_sequence=N` replays buffered events
- Replay: `?replay=true` plays full audit log from Postgres

17 event types: `case_started`, `round_started`, `agent_thinking`, `agent_response`, `tool_call`, `tool_result`, `bayesian_update`, `challenge_raised`, `challenge_resolved`, `caddick_routing`, `convergence_check`, `case_paused`, `case_resumed`, `evidence_injected`, `case_converged`, `final_report`, `error`.

### Concurrency
- One asyncio task per case; `MAX_CONCURRENT_CASES=5` semaphore
- Each case takes a Redis NX lock (single-leader for the graph executor)
- Multi-client: pub/sub fan-out per case_id
- Client disconnect ≠ case stop

### Tests
- `tests/test_phase4_api.py` — 14 subprocess-based integration tests covering REST + WS replay + WS live tail

### Known follow-ups for Phase 4.5
- CLI `--api-url` mode (CLI-via-WebSocket)
- JWT auth (Phase 5+ when frontend lands)
- Real `evidence_injected` handling (Phase 6)

---

## Phase 7 — Eval harness ✅

**Goal:** Measure the system against single-agent baselines on DDXPlus. Reordered ahead of Phase 5 because resume value is quantitative, not visual.

### Five baseline conditions
1. `gpt4o_solo` — single GPT-4o call, no tools, no team
2. `grok_solo` — single Grok call, no tools (cross-provider sanity check)
3. `gpt4o_rag` — GPT-4o + ChromaDB retrieval
4. `gpt4o_mi_layer` — GPT-4o + 9-tool MI dispatcher (no team) ← isolates "does the team add value beyond the tools?"
5. `full_team` — Phase 3 multi-agent system

### Metrics
- Top-1/3/5 accuracy with 1000-resample bootstrap 95% CIs
- Mean Reciprocal Rank
- ECE (10-bin) + Brier score + reliability diagrams
- Convergence rate, rounds distribution (mean, median, p95)
- Per-disease accuracy with confidence-when-correct vs wrong
- Failure modes: hallucinated / missed_obvious / premature_convergence / schema_failure
- Hauser dissent rate + correctness when dissented

### Sampling
DDXPlus has 1.025M cases. Stratified sampling with three modes:
- `proportional` (default) — preserves base rates → honest headline
- `uniform_per_disease` — fair per-disease F1
- Difficulty-binned (easy/medium/hard from `n_evidences` + Ddx size)

Three eval tiers: smoke (n=20, ~$5 budget), standard (n=200, ~$40), headline (n=1000, ~$250).

### Cache + budget
SQLite-backed deterministic LLM cache. Key = `sha256(provider, model, prompt_version, messages, tools, temp, max_tokens)`. Re-scoring with fixed metrics costs $0. `prompt_version` hash auto-invalidates on prompt edits.

`CostTracker` enforces a hard budget cap with `BudgetBreach` exception at 95% of limit. Per-case + per-agent + per-condition breakdown.

### Reports
`data/eval_runs/{run_id}/` contains `summary.md`, `metrics.json`, `per_case.csv`, and matplotlib charts (`reliability.png`, `cost.png`, `per_disease.png`, `accuracy_by_condition.png`).

### Tests
- `tests/test_phase7_eval.py` — 23 tests covering cache, cost, sampler, metrics normalization, calibration (perfect + overconfident edge cases), bootstrap CI envelopes, top-5 parser robustness, and end-to-end pipeline using `full_team` mock fixture (no LLM keys needed).

### What's NOT in Phase 7
- Live LLM-driven runs across all 5 conditions (requires API keys for OpenAI + xAI + Anthropic)
- Per-agent ablation study (run team without each agent in turn) — deferred to Phase 7.5
- Statistical significance test between conditions (paired bootstrap) — deferred
