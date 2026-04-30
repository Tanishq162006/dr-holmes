# Running Dr. Holmes

## Prerequisites

- Python 3.11+
- Homebrew (Mac) or apt/yum equivalents
- ~2GB free disk for datasets + Neo4j heap

## One-time setup

### 1. Install services natively

```bash
brew install neo4j redis postgresql
brew services start neo4j redis postgresql
```

### 2. Set Neo4j password (first time only)

```bash
/usr/local/Cellar/neo4j/*/bin/neo4j-admin dbms set-initial-password drholmes123
brew services restart neo4j
```

### 3. Install Python deps

```bash
uv pip install --system -e .
# or:
pip install -e .
```

### 4. Configure env

```bash
cp .env.example .env
# fill in API keys (optional for mock mode):
#   OPENAI_API_KEY=sk-...
#   XAI_API_KEY=xai-...
```

### 5. Load datasets (~5 min total)

```bash
python3 scripts/load_ddxplus.py     # 49 disease priors + 882 symptom likelihoods → SQLite
python3 scripts/load_hetionet.py    # 8K nodes + 154K edges → Neo4j
python3 scripts/build_rag.py        # 500 MedQA chunks → ChromaDB
```

### 6. Verify

```bash
python3 scripts/verify.py
```

You should see green checks across SQLite (49 diseases), Neo4j (137 disease nodes, 154K edges), ChromaDB (500 chunks), and Redis.

---

## Running modes

### CLI mock mode — no API keys needed

```bash
python3 -m dr_holmes.cli_phase3 --mock --case fixtures/case_01_easy_mi.json
python3 -m dr_holmes.cli_phase3 --mock --case fixtures/case_02_atypical_sle.json
python3 -m dr_holmes.cli_phase3 --mock --case fixtures/case_03_zebra_whipples.json
```

Three pre-built cases:
- `case_01_easy_mi` — anterior STEMI; converges round 3
- `case_02_atypical_sle` — autoimmune debate (Carmen vs Forman)
- `case_03_zebra_whipples` — late vindication of Hauser

### CLI live mode — requires API keys

```bash
python3 -m dr_holmes.cli            # 2-agent (Phase 1/2) live with Hauser + Forman
python3 -m dr_holmes.cli_phase3     # 6-agent live (pending Anthropic SDK wiring)
```

### API server

```bash
python3 -m uvicorn dr_holmes.api.main:app --reload
```

- OpenAPI: http://localhost:8000/docs
- Health: http://localhost:8000/healthz
- Readiness: http://localhost:8000/readyz
- Metrics: http://localhost:8000/metrics

#### REST: create a mock case

```bash
curl -X POST localhost:8000/api/cases \
  -H 'Content-Type: application/json' \
  -d '{
    "patient_presentation": {"presenting_complaint": "chest pain"},
    "mock_mode": true,
    "fixture_path": "fixtures/case_01_easy_mi.json"
  }'
```

#### REST: get transcript

```bash
curl localhost:8000/api/cases/{case_id}/transcript | jq
```

#### WS: live tail

```bash
brew install websocat
websocat ws://localhost:8000/ws/cases/{case_id}
```

#### WS: replay completed case

```bash
websocat 'ws://localhost:8000/ws/cases/{case_id}?replay=true'
```

---

## Tests

```bash
python3 -m pytest tests/ -v
```

47 tests across all phases. Mock mode means no API spend in CI.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OPENAI_API_KEY not set` | Edit `.env`. For mock mode you don't need keys. |
| `Neo4j ServiceUnavailable` | `brew services restart neo4j`; wait 30s for boot |
| `Redis ConnectionRefusedError` | `brew services start redis` |
| `module 'sentence_transformers'` import error | `python3 -m pip install --upgrade sentence-transformers` |
| `audit_log NOT NULL constraint` | Delete `data/cases.db` and let it recreate on next run |
| Tests hang on lifespan_context | Phase 4 tests use subprocess-based server, not in-process |
