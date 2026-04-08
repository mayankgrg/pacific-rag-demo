"""
Permission-gated retrieval layer.

Queries ChromaDB using role-based metadata filters so only chunks the user
is authorized to see are returned. The filter is enforced at the DB layer —
no restricted chunks are loaded into memory at all.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

import chromadb
from sentence_transformers import SentenceTransformer

from roles import expand_roles

DB_DIR = Path(__file__).parent / "db"
COLLECTION_NAME = "acme_docs"
TOP_K = 6

_model: Optional[SentenceTransformer] = None
_client: Optional[chromadb.PersistentClient] = None
_collection = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(DB_DIR))
        _collection = _client.get_collection(COLLECTION_NAME)
    return _collection


@dataclass
class RetrievalResult:
    chunks: list[str]
    sources: list[str]
    scores: list[float]
    chunks_blocked: int


def retrieve(query: str, user_roles: list[str]) -> RetrievalResult:
    """
    Return top-k chunks visible to the user's roles.

    The permission filter runs inside ChromaDB — no restricted content
    is returned to the application layer at any point.
    """
    expanded = expand_roles(user_roles)
    collection = _get_collection()
    model = _get_model()

    query_embedding = model.encode([query]).tolist()

    # Build a ChromaDB $or filter: match any role the user holds.
    # Each role is stored as a boolean flag (role_hr, role_finance, etc.)
    role_conditions = [
        {f"role_{role}": {"$eq": True}}
        for role in expanded
    ]
    where_filter = {"$or": role_conditions} if len(role_conditions) > 1 else role_conditions[0]

    # Fetch allowed chunks
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=TOP_K,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    chunks = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    # Cosine distance → similarity score (1 - distance)
    scores = [round(1 - d, 4) for d in distances]
    sources = [m["source"] for m in metadatas]

    # Estimate blocked chunks: total in collection minus what was returned
    total_in_db = collection.count()
    chunks_blocked = max(0, total_in_db - len(chunks))

    return RetrievalResult(
        chunks=chunks,
        sources=sources,
        scores=scores,
        chunks_blocked=chunks_blocked,
    )
