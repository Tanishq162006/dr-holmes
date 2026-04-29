"""Run this once to pre-build the RAG index before starting the CLI."""
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

chroma_path = os.getenv("CHROMA_PATH", "./data/chroma")

from dr_holmes.rag.retriever import build_index
build_index(chroma_path, force=True)
print("Done.")
