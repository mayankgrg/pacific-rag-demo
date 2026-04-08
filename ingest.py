"""
Document ingestion pipeline.

Reads docs/ folder, chunks each document, embeds with sentence-transformers,
and stores vectors + permission metadata in ChromaDB.

Run once before starting the server:
    python ingest.py
"""

import json
import os
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

DOCS_DIR = Path(__file__).parent / "docs"
DB_DIR = Path(__file__).parent / "db"
COLLECTION_NAME = "acme_docs"
CHUNK_SIZE = 512       # characters (approximate; not tokens)
CHUNK_OVERLAP = 80


def load_documents() -> list[dict]:
    """Load all .txt files and their companion .meta.json files."""
    docs = []
    for txt_file in sorted(DOCS_DIR.glob("*.txt")):
        meta_file = txt_file.with_suffix(".meta.json")
        if not meta_file.exists():
            print(f"  WARNING: no meta file for {txt_file.name}, skipping.")
            continue
        text = txt_file.read_text(encoding="utf-8")
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        docs.append({
            "filename": txt_file.stem,
            "text": text,
            "allowed_roles": meta["allowed_roles"],
            "classification": meta["classification"],
        })
    return docs


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping character-based chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end].strip())
        start += size - overlap
    return [c for c in chunks if c]


def ingest():
    print("Loading documents...")
    docs = load_documents()
    print(f"  Found {len(docs)} documents.")

    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print("Connecting to ChromaDB...")
    DB_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_DIR))

    # Wipe and recreate collection for idempotency
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    total_chunks = 0
    for doc in docs:
        chunks = chunk_text(doc["text"])
        embeddings = model.encode(chunks, show_progress_bar=False).tolist()

        ids = [f"{doc['filename']}_chunk_{i}" for i in range(len(chunks))]

        # ChromaDB metadata values must be str/int/float/bool — store roles as
        # individual boolean flags so we can filter with $eq later.
        metadatas = []
        for _ in chunks:
            m: dict = {
                "source": doc["filename"],
                "classification": doc["classification"],
            }
            # Store each role as a boolean flag: role_hr, role_finance, etc.
            for role in ["admin", "hr", "finance", "engineer", "intern"]:
                m[f"role_{role}"] = role in doc["allowed_roles"]
            metadatas.append(m)

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )
        print(f"  {doc['filename']}: {len(chunks)} chunks ingested  [{doc['classification']}]")
        total_chunks += len(chunks)

    print(f"\nDone. {total_chunks} total chunks stored in ChromaDB.")


if __name__ == "__main__":
    ingest()
