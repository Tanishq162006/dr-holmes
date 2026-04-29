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
   │ (Grok)    │ (GPT-4o)  │ (Sonnet)  │ (4o-mini) │ (Haiku)   │
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
| 5 | next | Next.js + Tailwind frontend (talks to Phase 4 WebSocket) |
| 6 | future | Human-in-the-loop interrupts, evidence injection mid-case |
| 7 | future | Calibration eval against known-outcome cases, DSPy/prompt iteration |
| 8 | future | Trace replay UI, demo recording |

**Test coverage:** `47 tests, all passing` (22 orchestration unit + 11 E2E mock + 14 API integration).

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
# fill in OPENAI_API_KEY, XAI_API_KEY, ANTHROPIC_API_KEY (optional for mock mode)

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
| **Carmen** | Anthropic | `claude-3-5-sonnet` | Immunology | autoimmune | Empathetic, rigorous on serology |
| **Chen** | OpenAI | `gpt-4o-mini` | Surgical / ICU | procedural | Action-oriented, time-critical |
| **Wills** | Anthropic | `claude-3-5-haiku` | Oncology | malignancy | Measured, rules malignancy in/out |
| **Caddick** | OpenAI | `gpt-4o` | Moderator | n/a | Deterministic routing + synthesis |

Model diversity is intentional — different training distributions → genuine reasoning diversity, not just personality theater.

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

## Running tests

```bash
python3 -m pytest tests/ -v
```

```
22 phase-3 orchestration unit tests   (routing, convergence, aggregation)
11 phase-3 E2E mock fixture tests
14 phase-4 API integration tests       (REST + WebSocket)
─────────────────────────────────────
47 passing
```

---

## License + disclaimer

This is a personal portfolio project for learning multi-agent LLM systems and medical-domain knowledge engineering. Not affiliated with House M.D., Universal, or any medical institution. Strong AI disclaimer: the simulated diagnoses produced by this system are **fictional output** and must never be used to inform real medical decisions.
