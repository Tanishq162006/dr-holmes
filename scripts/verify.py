"""
Pre-flight verification. Run before starting the CLI.
Checks: SQLite row counts, Neo4j connectivity, ChromaDB, Redis.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

OK = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m~\033[0m"

db_path     = os.getenv("SQLITE_PATH",   "./data/bayes.db")
chroma_path = os.getenv("CHROMA_PATH",   "./data/chroma")
neo4j_uri   = os.getenv("NEO4J_URI",     "bolt://localhost:7687")
neo4j_user  = os.getenv("NEO4J_USER",    "neo4j")
neo4j_pass  = os.getenv("NEO4J_PASSWORD","drholmes123")
redis_url   = os.getenv("REDIS_URL",     "redis://localhost:6379")

issues = []

# ── 1. SQLite Bayesian tables ──────────────────────────────────────────────
try:
    from dr_holmes.db.schema import get_engine, get_session
    from dr_holmes.db.schema import DiseasePrior, SymptomLikelihood, TestCharacteristic
    engine  = get_engine(db_path)
    session = get_session(engine)
    n_diseases  = session.query(DiseasePrior).count()
    n_symptoms  = session.query(SymptomLikelihood).count()
    n_tests     = session.query(TestCharacteristic).count()
    session.close()
    sym = OK if n_diseases > 0 else FAIL
    print(f"  {sym} SQLite — diseases: {n_diseases}, symptom_likelihoods: {n_symptoms}, test_chars: {n_tests}")
    if n_diseases == 0:
        issues.append("DDXPlus not loaded — run: python3 scripts/load_ddxplus.py")
    if n_symptoms == 0:
        issues.append("Symptom likelihoods missing — Bayesian updates will be flat")
except Exception as e:
    print(f"  {FAIL} SQLite — {e}")
    issues.append(f"SQLite error: {e}")

# ── 2. Neo4j ───────────────────────────────────────────────────────────────
try:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
    with driver.session() as s:
        n_diseases = s.run("MATCH (n:Disease) RETURN count(n) AS c").single()["c"]
        n_symptoms = s.run("MATCH (n:Symptom) RETURN count(n) AS c").single()["c"]
        n_edges    = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    driver.close()
    sym = OK if n_diseases > 0 else WARN
    print(f"  {sym} Neo4j — diseases: {n_diseases}, symptoms: {n_symptoms}, edges: {n_edges}")
    if n_diseases == 0:
        issues.append("Hetionet not loaded — run: python3 scripts/load_hetionet.py")
except Exception as e:
    print(f"  {WARN} Neo4j — {e} (graph tools will be disabled)")

# ── 3. ChromaDB ────────────────────────────────────────────────────────────
try:
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    client = chromadb.PersistentClient(path=chroma_path)
    ef = DefaultEmbeddingFunction()
    existing = [c.name for c in client.list_collections()]
    if "medqa" in existing:
        col = client.get_collection("medqa", embedding_function=ef)
        n = col.count()
        sym = OK if n > 0 else WARN
        print(f"  {sym} ChromaDB — medqa chunks: {n}")
        if n == 0:
            issues.append("ChromaDB empty — run: python3 scripts/build_rag.py")
    else:
        print(f"  {WARN} ChromaDB — medqa collection not found")
        issues.append("ChromaDB not indexed — run: python3 scripts/build_rag.py")
except Exception as e:
    print(f"  {WARN} ChromaDB — {e}")

# ── 4. Redis ───────────────────────────────────────────────────────────────
try:
    import redis
    r = redis.from_url(redis_url)
    r.ping()
    print(f"  {OK} Redis — connected")
except Exception as e:
    print(f"  {WARN} Redis — {e} (session memory disabled, not fatal)")

# ── 5. Tool schema generation ──────────────────────────────────────────────
try:
    from dr_holmes.db.schema import get_engine, get_session
    from dr_holmes.intelligence.medical import MedicalIntelligence
    from dr_holmes.intelligence.dispatcher import ToolDispatcher
    engine  = get_engine(db_path)
    session = get_session(engine)
    mi = MedicalIntelligence(session)
    d  = ToolDispatcher(mi)
    n_tools = len(d.tool_schemas())
    session.close()
    print(f"  {OK} ToolDispatcher — {n_tools} tool schemas generated")
except Exception as e:
    print(f"  {FAIL} ToolDispatcher — {e}")
    issues.append(f"ToolDispatcher broken: {e}")

# ── Summary ────────────────────────────────────────────────────────────────
print()
if issues:
    print("Issues to fix before running:")
    for i in issues:
        print(f"  ! {i}")
    sys.exit(1)
else:
    print("All checks passed. Ready to run: python3 -m dr_holmes.cli")
