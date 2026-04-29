"""Direct Medical Intelligence layer queries (admin / debug)."""
from fastapi import APIRouter, HTTPException
from dr_holmes.api.schemas.requests import HealthResponse

router = APIRouter(prefix="/api/intel", tags=["intel"])


@router.get("/health", response_model=HealthResponse)
async def intel_health():
    components = {}

    # SQLite/Postgres
    try:
        from dr_holmes.api.persistence import get_sessionmaker
        from sqlalchemy import text
        sm = get_sessionmaker()
        async with sm() as s:
            await s.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception as e:
        components["database"] = f"error: {e}"

    # Redis
    from dr_holmes.api.redis_client import get_redis
    r = get_redis()
    if r is None:
        components["redis"] = "unavailable"
    else:
        try:
            await r.ping()
            components["redis"] = "ok"
        except Exception as e:
            components["redis"] = f"error: {e}"

    # Bayesian (sync)
    try:
        from dr_holmes.db.schema import get_engine, get_session, DiseasePrior
        engine = get_engine()
        sess = get_session(engine)
        n = sess.query(DiseasePrior).count()
        sess.close()
        components["bayes_db"] = f"{n} disease priors"
    except Exception as e:
        components["bayes_db"] = f"error: {e}"

    # Neo4j (sync)
    try:
        import os
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"),
                  os.getenv("NEO4J_PASSWORD", "drholmes123")),
        )
        with driver.session() as s:
            n = s.run("MATCH (n:Disease) RETURN count(n) AS c").single()["c"]
        driver.close()
        components["neo4j"] = f"{n} disease nodes"
    except Exception as e:
        components["neo4j"] = f"error: {e}"

    overall = "ok" if all(v.startswith("ok") or "disease" in v for v in components.values()) else "degraded"
    return HealthResponse(status=overall, components=components, server_version="0.4.0")


@router.get("/diseases/{name}")
async def lookup_disease(name: str):
    """Direct MI graph lookup."""
    try:
        import os
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"),
                  os.getenv("NEO4J_PASSWORD", "drholmes123")),
        )
        with driver.session() as s:
            row = s.run(
                """
                MATCH (d:Disease) WHERE toLower(d.name) CONTAINS toLower($name)
                OPTIONAL MATCH (d)-[:PRESENTS_WITH]->(sym:Symptom)
                OPTIONAL MATCH (drug:Compound)-[:TREATS]->(d)
                RETURN d.name AS name,
                       collect(DISTINCT sym.name)[..10] AS symptoms,
                       collect(DISTINCT drug.name)[..5] AS treatments
                LIMIT 1
                """,
                name=name,
            ).single()
        driver.close()
        if not row:
            raise HTTPException(404, f"No disease matching {name!r}")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"Neo4j unavailable: {e}")
