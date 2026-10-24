"""Ingest the TaskPilot knowledge base into Weaviate using the native v4 client.

Why native v4 instead of langchain-weaviate:
  langchain-weaviate 0.0.8 is incompatible with weaviate-client 4.9+.
  The native v4 API is stable, explicit, and recommended in official Weaviate docs.

Run from the project root:
    python scripts/ingest.py

Required env vars (copy .env.example to .env):
    OPENAI_API_KEY, WEAVIATE_URL, WEAVIATE_API_KEY
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import yaml
import weaviate
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from weaviate.classes.config import DataType, Property
from weaviate.classes.init import Auth

# ── Config ────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
KB_DIR     = ROOT / "kb"
cfg        = yaml.safe_load((ROOT / "config.yaml").read_text())
COLLECTION = cfg["weaviate"]["collection"]   # "TaskpilotKB"

# ── Step 1: chunk KB markdown files ──────────────────────────────────────────
HEADERS_TO_SPLIT = [("#", "title"), ("##", "section")]

md_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=HEADERS_TO_SPLIT,
    strip_headers=False,
)
char_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

raw_docs = []
for path in sorted(KB_DIR.glob("*.md")):
    for chunk in md_splitter.split_text(path.read_text(encoding="utf-8")):
        chunk.metadata["source"]   = path.name
        chunk.metadata["archived"] = "ARCHIVED" in path.name
        raw_docs.append(chunk)

docs = char_splitter.split_documents(raw_docs)
print(f"Loaded {len(list(KB_DIR.glob('*.md')))} files -> {len(docs)} chunks")

# ── Step 2: embed all chunks with OpenAI ─────────────────────────────────────
embeddings = OpenAIEmbeddings(model=cfg["models"]["embeddings"])
vectors    = embeddings.embed_documents([doc.page_content for doc in docs])
print(f"Embedded {len(vectors)} chunks")

# ── Step 3: connect to Weaviate Cloud (official v4 pattern) ──────────────────
client = weaviate.connect_to_weaviate_cloud(
    cluster_url=os.environ["WEAVIATE_URL"],
    auth_credentials=Auth.api_key(os.environ["WEAVIATE_API_KEY"]),
)

# ── Step 4: recreate the collection ──────────────────────────────────────────
if client.collections.exists(COLLECTION):
    client.collections.delete(COLLECTION)
    print(f"Dropped existing collection '{COLLECTION}'")

# Create collection with properties only — no vector config.
# Weaviate Cloud free tier uses hfresh (flat) index by default.
# We supply our own OpenAI vectors on insert (BYOV pattern).
client.collections.create(
    name=COLLECTION,
    properties=[
        Property(name="text",     data_type=DataType.TEXT),
        Property(name="source",   data_type=DataType.TEXT),
        Property(name="archived", data_type=DataType.BOOL),
    ],
)
print(f"Created collection '{COLLECTION}'")

# ── Step 5: batch insert ──────────────────────────────────────────────────────
collection = client.collections.get(COLLECTION)

with collection.batch.dynamic() as batch:
    for doc, vector in zip(docs, vectors):
        batch.add_object(
            properties={
                "text":     doc.page_content,
                "source":   doc.metadata.get("source", ""),
                "archived": doc.metadata.get("archived", False),
            },
            vector=vector,   # plain list — no named vector config needed
        )

print(f"Ingested {len(docs)} chunks into '{COLLECTION}'")
client.close()
