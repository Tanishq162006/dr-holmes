"""
Load Hetionet into Neo4j — batched UNWIND for speed.

Loads:
  Nodes: Disease, Symptom, Compound, Anatomy, SideEffect
  Edges: PRESENTS_WITH, RESEMBLES, CAUSES, TREATS, INTERACTS_WITH,
         CAUSES_SIDE_EFFECT, LOCALIZES_TO

Run after Neo4j is up and password is set.
"""
import os
import sys
import json
import bz2
import urllib.request
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

NEO4J_URI  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "drholmes123")
HETIONET_URL = "https://github.com/hetio/hetionet/raw/main/hetnet/json/hetionet-v1.0.json.bz2"
LOCAL_BZ2  = "./data/hetionet-v1.0.json.bz2"
LOCAL_JSON = "./data/hetionet-v1.0.json"

WANTED_NODE_KINDS = {"Disease", "Symptom", "Compound", "Anatomy", "Side Effect"}
NODE_LABEL_MAP = {"Side Effect": "SideEffect"}

# Hetionet edge "kind" is just the verb (e.g. "presents", "treats").
# We reconstruct (src_kind, verb, tgt_kind) from source_id/target_id tuples.
# Map (src_kind, verb, tgt_kind) → (src_label, tgt_label, neo4j_rel_name)
EDGE_REL_MAP = {
    ("Disease",  "presents",  "Symptom"):     ("Disease",  "Symptom",    "PRESENTS_WITH"),
    ("Disease",  "resembles", "Disease"):     ("Disease",  "Disease",    "RESEMBLES"),
    ("Compound", "treats",    "Disease"):     ("Compound", "Disease",    "TREATS"),
    ("Compound", "palliates", "Disease"):     ("Compound", "Disease",    "PALLIATES"),
    ("Compound", "causes",    "Side Effect"): ("Compound", "SideEffect", "CAUSES_SIDE_EFFECT"),
    ("Compound", "resembles", "Compound"):    ("Compound", "Compound",   "RESEMBLES"),
    ("Disease",  "localizes", "Anatomy"):     ("Disease",  "Anatomy",    "LOCALIZES_TO"),
}


def download_hetionet():
    if os.path.exists(LOCAL_JSON):
        print(f"Using cached {LOCAL_JSON}")
        with open(LOCAL_JSON) as f:
            return json.load(f)
    if not os.path.exists(LOCAL_BZ2):
        print(f"Downloading Hetionet (~75 MB)...")
        urllib.request.urlretrieve(HETIONET_URL, LOCAL_BZ2)
    print("Decompressing...")
    with bz2.open(LOCAL_BZ2) as f:
        data = json.loads(f.read().decode("utf-8"))
    with open(LOCAL_JSON, "w") as f:
        json.dump(data, f)
    print("Hetionet cached.")
    return data


def _bulk_create_nodes(session, label: str, nodes: list[dict], batch_size: int = 5000):
    if not nodes:
        return
    for i in range(0, len(nodes), batch_size):
        chunk = nodes[i:i + batch_size]
        session.run(
            f"UNWIND $rows AS row "
            f"MERGE (n:{label} {{hetio_id: row.id}}) "
            f"SET n.name = row.name",
            rows=chunk,
        )
        print(f"  {label}: {min(i + batch_size, len(nodes)):,}/{len(nodes):,}", flush=True)


def _bulk_create_edges(session, src_label: str, tgt_label: str, rel: str,
                       edges: list[dict], batch_size: int = 5000):
    if not edges:
        return
    for i in range(0, len(edges), batch_size):
        chunk = edges[i:i + batch_size]
        session.run(
            f"UNWIND $rows AS row "
            f"MATCH (a:{src_label} {{hetio_id: row.src}}), "
            f"      (b:{tgt_label} {{hetio_id: row.tgt}}) "
            f"MERGE (a)-[r:{rel}]->(b) "
            f"SET r += row.props",
            rows=chunk,
        )
        print(f"  {rel}: {min(i + batch_size, len(edges)):,}/{len(edges):,}", flush=True)


def main():
    os.makedirs("./data", exist_ok=True)
    data = download_hetionet()

    # ── Group nodes by label ───────────────────────────────────────────────
    nodes_by_label: dict[str, list[dict]] = defaultdict(list)
    nodes_id_to_label: dict[str, str] = {}
    for node in data["nodes"]:
        kind = node["kind"]
        if kind not in WANTED_NODE_KINDS:
            continue
        label = NODE_LABEL_MAP.get(kind, kind)
        nodes_by_label[label].append({
            "id":   node["identifier"],
            "name": node["name"],
        })
        nodes_id_to_label[str(node["identifier"])] = label

    print(f"Wanted nodes: {sum(len(v) for v in nodes_by_label.values()):,} "
          f"({', '.join(f'{k}={len(v)}' for k, v in nodes_by_label.items())})")

    # ── Group edges by relation type ───────────────────────────────────────
    # Edges are: source_id=[kind, id], target_id=[kind, id], kind=verb
    edges_by_rel: dict[tuple, list[dict]] = defaultdict(list)
    for edge in data["edges"]:
        src = edge["source_id"]
        tgt = edge["target_id"]
        if not (isinstance(src, list) and isinstance(tgt, list)):
            continue
        src_kind, src_id = src[0], src[1]
        tgt_kind, tgt_id = tgt[0], tgt[1]
        verb = edge["kind"]

        key = (src_kind, verb, tgt_kind)
        if key not in EDGE_REL_MAP:
            continue
        # Verify both nodes were loaded
        if str(src_id) not in nodes_id_to_label or str(tgt_id) not in nodes_id_to_label:
            continue
        edges_by_rel[key].append({
            "src":   src_id,
            "tgt":   tgt_id,
            "props": edge.get("data", {}) or {},
        })

    print(f"Wanted edges: {sum(len(v) for v in edges_by_rel.values()):,} "
          f"({', '.join(f'{k[1]}={len(v)}' for k, v in edges_by_rel.items())})")

    # ── Connect to Neo4j and load ──────────────────────────────────────────
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    with driver.session() as session:
        print("\nCreating constraints + indices...")
        for label in ("Disease", "Symptom", "Compound", "Anatomy", "SideEffect"):
            session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
                f"REQUIRE n.hetio_id IS UNIQUE"
            )
        for label in ("Disease", "Symptom", "Compound"):
            try:
                session.run(
                    f"CREATE FULLTEXT INDEX {label.lower()}_name IF NOT EXISTS "
                    f"FOR (n:{label}) ON EACH [n.name]"
                )
            except Exception:
                pass

        print("\nLoading nodes...")
        for label, nodes in nodes_by_label.items():
            _bulk_create_nodes(session, label, nodes)

        print("\nLoading edges...")
        for key, edges in edges_by_rel.items():
            src_label, tgt_label, rel = EDGE_REL_MAP[key]
            _bulk_create_edges(session, src_label, tgt_label, rel, edges)

        # ── Final stats ────────────────────────────────────────────────────
        n_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        n_edges = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"\nNeo4j now has {n_nodes:,} nodes, {n_edges:,} edges.")

    driver.close()
    print("Done.")


if __name__ == "__main__":
    main()
