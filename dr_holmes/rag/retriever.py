from __future__ import annotations
import os
import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from datasets import load_dataset
from rich.progress import track


COLLECTION_NAME = "medqa"
INDEX_LIMIT = 500  # first run is fast; bump to ~10k after first index


def _get_client(chroma_path: str) -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=chroma_path)


def _embedder():
    # ONNX-backed all-MiniLM, ships with chromadb. No torch / sentence-transformers needed.
    return DefaultEmbeddingFunction()


def build_index(chroma_path: str, force: bool = False) -> chromadb.Collection:
    client = _get_client(chroma_path)
    ef = _embedder()

    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing and not force:
        return client.get_collection(COLLECTION_NAME, embedding_function=ef)

    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(COLLECTION_NAME, embedding_function=ef)

    print(f"Loading MedQA dataset (first {INDEX_LIMIT} entries)...")
    ds = load_dataset("GBaker/MedQA-USMLE-4-options", split="train")

    docs, ids, metas = [], [], []
    for i, row in enumerate(ds):
        if i >= INDEX_LIMIT:
            break
        question = row.get("question", "")
        options = row.get("options", {})
        answer_key = row.get("answer_idx", "")
        answer_text = options.get(answer_key, "") if isinstance(options, dict) else ""
        doc = f"Q: {question}\nA: {answer_text}"
        docs.append(doc)
        ids.append(f"medqa_{i}")
        metas.append({"source": "medqa_usmle", "idx": i})

    print(f"Indexing {len(docs)} documents...")
    batch_size = 50
    for start in track(range(0, len(docs), batch_size), description="Indexing"):
        end = min(start + batch_size, len(docs))
        collection.add(
            documents=docs[start:end],
            ids=ids[start:end],
            metadatas=metas[start:end],
        )

    print(f"Index built: {len(docs)} docs in ChromaDB at {chroma_path}")
    return collection


def get_retriever(chroma_path: str):
    client = _get_client(chroma_path)
    ef = _embedder()
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME not in existing:
        return None
    return client.get_collection(COLLECTION_NAME, embedding_function=ef)


def retrieve(collection, query: str, top_k: int = 5) -> str:
    if collection is None:
        return ""
    results = collection.query(query_texts=[query], n_results=top_k)
    docs = results.get("documents", [[]])[0]
    return "\n---\n".join(docs)
