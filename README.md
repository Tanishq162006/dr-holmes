# Dr. Holmes — Multi-Agent Diagnostic Deliberation

> ⚠️ **NOT FOR CLINICAL USE.** Portfolio / learning project. All diagnoses are AI simulation. No real patient data.

A House MD–style diagnostic team built as a multi-agent LLM system. Six AI agents with distinct personalities, specialties, and model providers deliberate over patient cases in real time. A moderator (Dr. Caddick) routes the conversation deterministically. The system grounds reasoning in a real medical knowledge graph, a Bayesian engine over DDXPlus, and vector-retrieved case literature.

```
                   ┌────────────────┐
                   │ Patient case   │
                   └───────┬────────┘
                           ▼
   ┌───────────┬───────────┬───────────┬───────────┬───────────┐
   │  Hauser   │  Forman   │  Carmen   │   Chen    │   Wills   │
   │ (Grok-2)  │ (GPT-4o)  │ (4o-mini) │ (4o-mini) │ (4o-mini) │
   │ rare      │ common    │ autoimm.  │ surgical  │ malign.   │
   └─────┬─────┴─────┬─────┴─────┬─────┴─────┬─────┴─────┬─────┘
         └───────────┴───────────┼───────────┴───────────┘
                                 ▼
                       ┌──────────────────┐
                       │ Caddick (mod)    │ ── deterministic routing
                       │ GPT-4o synthesis │ ── synthesis only
                       └──────────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────────┐
                │  Medical Intelligence Layer (MI)   │
                │  Neo4j ▪ Bayesian SQLite ▪ ChromaDB │
                └────────────────────────────────────┘
```

---

## What's Built

| Phase | Status | What |
|---|---|---|
| **1** | ✅ done | 2-agent CLI (Holmes + Foreman) using LangGraph; Anthropic-compatible streaming |
| **2** | ✅ done | Medical Intelligence layer (Neo4j + Bayesian engine + ChromaDB), 9 structured tools, OpenAI tool-calling |
| **3** | ✅ done | Full 6-agent team, Caddick moderator with deterministic routing, mock-LLM mode, 3 fixture cases, rich CLI |
| **4** | ✅ done | FastAPI + WebSocket backend, audit log, Redis Streams, Postgres/SQLite persistence, Prometheus metrics |
| **7** | ✅ done | Eval harness: 5-condition baselines, DDXPlus stratified sampling, calibration analysis (ECE, Brier, reliability bins), bootstrap CIs, deterministic LLM cache, hard budget cap, markdown reports + matplotlib charts |
| 5 | next | Next.js + Tailwind frontend (talks to Phase 4 WebSocket) |
| 6 | future | Human-in-the-loop interrupts, evidence injection mid-case |
| 8 | future | Trace replay UI, demo recording |

**Test coverage:** `70 tests, all passing` (22 orchestration unit + 11 Phase 3 E2E + 14 Phase 4 API + 23 Phase 7 eval).

---

## Quick Start

```bash
# 1. Clone
git clone git@github.com:Tanishq162006/dr-holmes.git
cd dr-holmes

# 2. Install
brew install neo4j redis postgresql      # native (no Docker needed)
brew services start neo4j redis postgresql
uv pip install --system -r requirements.txt   # or: pip install -e .

# 3. Set Neo4j password (first time only)
/usr/local/Cellar/neo4j/*/bin/neo4j-admin dbms set-initial-password drholmes123

# 4. Set up env
cp .env.example .env
# fill in OPENAI_API_KEY and XAI_API_KEY (optional for mock mode)

# 5. Load datasets (one-time, ~5 min)
python3 scripts/load_ddxplus.py        # Bayesian priors → SQLite (49 dx, 882 likelihoods)
python3 scripts/load_hetionet.py       # Knowledge graph → Neo4j (8K nodes, 154K edges)
python3 scripts/build_rag.py           # Vector index → ChromaDB (500 MedQA chunks)

# 6. Verify
python3 scripts/verify.py              # green checks across all 4 datastores

# 7. Run a mock case (no API keys needed)
python3 -m dr_holmes.cli_phase3 --mock --case fixtures/case_01_easy_mi.json
```

---

## Running the API

```bash
python3 -m uvicorn dr_holmes.api.main:app --reload
```

- **OpenAPI docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/healthz
- **Readiness:** http://localhost:8000/readyz (checks DB, Redis, Bayes, Neo4j)
- **Metrics:** http://localhost:8000/metrics (Prometheus)

### Create a mock case

```bash
curl -X POST localhost:8000/api/cases \
  -H 'Content-Type: application/json' \
  -d '{
    "patient_presentation": {"presenting_complaint": "chest pain"},
    "mock_mode": true,
    "fixture_path": "fixtures/case_01_easy_mi.json"
  }'
```

### Subscribe to live event stream

```bash
websocat ws://localhost:8000/ws/cases/{case_id}
```

Or replay a completed case:

```bash
websocat 'ws://localhost:8000/ws/cases/{case_id}?replay=true'
```

---

## The Agent Team

| Agent | Provider | Model | Specialty | Bias | Personality |
|---|---|---|---|---|---|
| **Hauser** | xAI | `grok-2-1212` | Lead diagnostician | rare | Contrarian, hunts zebras, blunt |
| **Forman** | OpenAI | `gpt-4o` | Internal med / Neuro | common | Evidence-based, methodical |
| **Carmen** | OpenAI | `gpt-4o-mini` | Immunology | autoimmune | Empathetic, rigorous on serology |
| **Chen** | OpenAI | `gpt-4o-mini` | Surgical / ICU | procedural | Action-oriented, time-critical |
| **Wills** | OpenAI | `gpt-4o-mini` | Oncology | malignancy | Measured, rules malignancy in/out |
| **Caddick** | OpenAI | `gpt-4o` | Moderator | n/a | Deterministic routing + synthesis |

**Two providers required: OpenAI + xAI** (Grok). Cross-provider diversity comes from `Hauser` running on Grok against the OpenAI-family majority — different training distribution, different failure modes. The remaining differentiation comes from system prompts + specialty-biased tool calls, not model choice.

---

## Architecture

```
dr_holmes/
├── agents/                  # Agent classes + system prompts
│   ├── specialist_base.py   # SpecialistAgent + MockSpecialistAgent
│   ├── hauser.py forman.py  # Phase 1/2 agents (live OpenAI tool-calling)
│   ├── carmen.py chen.py wills.py  # Phase 3 specialist skeletons
│   └── caddick.py           # Moderator (synthesis-only LLM)
├── orchestration/           # Phase 3 multi-agent coordination
│   ├── builder.py           # LangGraph StateGraph + Send fan-out
│   ├── routing.py           # Deterministic Caddick routing rules
│   ├── convergence.py       # Cross-specialist agreement check
│   ├── aggregation.py       # Per-specialist Ddx → team Ddx (noisy-OR)
│   ├── mock_agents.py       # Fixture loader for mock mode
│   └── constants.py         # CONVERGENCE_PROB=0.80, MAX_ROUNDS=6, etc.
├── intelligence/            # Phase 2 Medical Intelligence Layer
│   ├── medical.py           # 9-tool API (Bayes + Neo4j + ChromaDB)
│   └── dispatcher.py        # OpenAI tool-call schema generator
├── db/                      # Bayesian engine + SQLAlchemy schema
│   ├── bayes.py             # Log-space Bayesian update + info gain
│   └── schema.py            # Disease priors / symptom likelihoods
├── rag/retriever.py         # ChromaDB vector retrieval
├── schemas/responses.py     # AgentResponse, FinalReport, etc.
├── api/                     # Phase 4 FastAPI server
│   ├── main.py              # App factory + middleware + metrics
│   ├── routes/
│   │   ├── cases.py         # REST: case CRUD
│   │   ├── agents.py        # REST: agent metadata
│   │   ├── intel.py         # REST: MI debug
│   │   └── ws.py            # WebSocket: live + replay
│   ├── runner.py            # Background case executor
│   ├── translator.py        # LangGraph events → WSEvents
│   ├── persistence.py       # SQLAlchemy async (Postgres or SQLite)
│   └── redis_client.py      # Streams + pub/sub fan-out
├── cli.py                   # Phase 1/2 CLI
└── cli_phase3.py            # Phase 3 6-agent CLI with rich rendering
fixtures/                    # Mock case scripts (3 cases)
scripts/                     # Data loaders + verify
tests/                       # 47 tests across all phases
docs/                        # Phase-by-phase architecture docs
```

---

## Key Design Decisions

- **Deterministic routing.** Caddick's choice of next speaker is pure Python (`orchestration/routing.py`). The LLM only writes the synthesis paragraph. This is testable, reproducible, and not flaky.
- **Cross-specialist convergence.** A team converges when ≥3 of 5 specialists list the same dx in their top-3 with prob > 0.50, **and** team probability ≥ 0.80, **and** the last round had no big delta, **and** no challenges remain unresolved.
- **Hauser dissent.** Even at consensus, if Hauser's top dx differs, his dissent is preserved in `FinalReport.hauser_dissent` and rendered in a dedicated yellow CLI panel — never collapsed.
- **Anti-stagnation.** Two consecutive rounds with no probability movement and no new evidence flag a stagnation hint to Caddick to propose a discriminating test.
- **Mock-mode runs the real state machine.** Fixture files only stub the LLM call; routing, Bayesian aggregation, and convergence checks all execute on real code paths. Test asserting Phase 3 behavior all use mock mode → 0 API costs in CI.

See `docs/` for full architecture docs per phase.

---

## Benchmarks

> **Status:** harness shipped, full numbers pending live runs.
> Re-run any time with `python3 -m dr_holmes.eval --tier standard --all-conditions --budget 25`.

### Headline (placeholder — to be populated by `headline_v1` run)

Eval against 200 stratified DDXPlus cases. Numbers below are **not yet measured** — they're the result fields the harness produces:

| System | Top-1 | Top-3 | Top-5 | MRR | ECE | Cost/case |
|---|---|---|---|---|---|---|
| `gpt4o_solo` | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| `grok_solo` (cross-provider) | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| `gpt4o_rag` | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| `gpt4o_mi_layer` | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |
| **`full_team` (Dr. Holmes)** | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |

All headline numbers reported with bootstrapped 95% CIs (1000 resamples). Full report lands at `eval_runs/headline_v1/summary.md` once first live run completes.

### Run it yourself

```bash
# Smoke test (3 cases, no LLM cost — uses full_team mock fixture)
python3 -m dr_holmes.eval --tier smoke --conditions full_team \
  --full-team-mock-fixture fixtures/case_01_easy_mi.json --n 3

# Standard eval (200 stratified DDXPlus cases × all 5 baselines)
# Budget covers ~$25 worth of OpenAI + xAI tokens; cache amortizes re-runs.
python3 -m dr_holmes.eval --tier standard --all-conditions --budget 25

# Re-render report from a completed run (zero LLM cost)
python3 -m dr_holmes.eval --report --run-id <run_id>
```

**Five baseline conditions** for honest comparison:
| # | Condition | What it measures |
|---|---|---|
| 1 | `gpt4o_solo` | Single GPT-4o call, no tools, no team |
| 2 | `grok_solo` | Single Grok call, no tools — cross-provider sanity check |
| 3 | `gpt4o_rag` | GPT-4o + ChromaDB retrieval |
| 4 | `gpt4o_mi_layer` | GPT-4o + full 9-tool MI layer (no team) — isolates "does the team add value beyond the tools?" |
| 5 | `full_team` | Phase 3 multi-agent system |

The critical comparison is **#4 vs #5**. If `gpt4o_mi_layer ≈ full_team`, the multi-agent overhead isn't paying off — and that's what the harness will tell you. **Honest reporting policy:** if the team underperforms, README will say so.

### Cost projection for live runs

| Tier | Cases | Est. cost (cold) | Re-run cost |
|---|---|---|---|
| smoke | 20 | ~$2 | <$1 |
| standard | 200 | ~$25 | <$2 |
| headline | 1000 | ~$140 | <$10 |

**Metrics** computed for every run:
- Top-1, Top-3, Top-5 accuracy with 1000-resample bootstrapped 95% CIs
- Mean Reciprocal Rank
- Expected Calibration Error (10-bin), Brier score, reliability diagrams
- Convergence rate + rounds distribution
- Per-disease accuracy heatmap (top 10 by sample count + worst 5 by accuracy)
- Failure-mode breakdown: hallucinated, missed_obvious, premature_convergence, schema_failure
- Hauser dissent rate + correctness when he dissented

**Cost discipline:** every LLM call goes through a deterministic SQLite cache keyed by `sha256(provider, model, prompt_version, messages, tools)`. Re-running metrics on cached responses is free. Hard `BudgetBreach` exception when you cross 95% of the cap.

Run artifacts land in `data/eval_runs/{run_id}/`:
```
summary.md          ← human-readable, paste-ready for resume
metrics.json        ← machine-readable run record (config, git_sha, prompt_version)
per_case.csv        ← one row per case, every metric
charts/
  ├── reliability.png         ← reliability diagram with ECE annotated
  ├── cost.png                ← cost-per-case distribution
  ├── per_disease.png         ← per-disease accuracy bar chart
  └── accuracy_by_condition.png  (when multiple conditions)
```

## Running tests

```bash
python3 -m pytest tests/ -v
```

```
22 phase-3 orchestration unit tests   (routing, convergence, aggregation)
11 phase-3 E2E mock fixture tests
14 phase-4 API integration tests       (REST + WebSocket)
23 phase-7 eval pipeline tests         (cache, cost, metrics, calibration, e2e)
─────────────────────────────────────
70 passing
```

---

## License + disclaimer

This is a personal portfolio project for learning multi-agent LLM systems and medical-domain knowledge engineering. Not affiliated with House M.D., Universal, or any medical institution. Strong AI disclaimer: the simulated diagnoses produced by this system are **fictional output** and must never be used to inform real medical decisions.
