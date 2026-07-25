"""
AgentForge — ChromaDB Vector Store Manager
Stores document chunks with embeddings for semantic search (RAG).
Uses sentence-transformers locally — no API key required.
"""

import os
import uuid
import textwrap
from typing import List, Dict

# ─────────────────────────────────────────────────────────────────────────────
# Lazy-loaded singletons (avoid heavy imports at startup)
# ─────────────────────────────────────────────────────────────────────────────
_chroma_client = None
_embedding_fn  = None


def _get_chroma():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "chroma_db"
        )
        _chroma_client = chromadb.PersistentClient(path=db_path)
    return _chroma_client


from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from sklearn.feature_extraction.text import HashingVectorizer


class FastTFIDFEmbeddingFunction(EmbeddingFunction):
    """
    Lightweight, high-performance embedding function based on HashingVectorizer.
    Avoids native C++ DLL dependencies (like PyTorch or ONNX runtime DLL errors).
    """

    def __init__(self, n_features: int = 384):
        self.vectorizer = HashingVectorizer(
            n_features=n_features,
            alternate_sign=False,
            norm="l2",
            stop_words="english",
        )

    def __call__(self, input: Documents) -> Embeddings:
        matrix = self.vectorizer.transform(input)
        return matrix.toarray().tolist()


def _get_embedding_fn():
    """Get the robust API/DLL-free embedding function."""
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = FastTFIDFEmbeddingFunction(n_features=384)
    return _embedding_fn


# ─────────────────────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split text into overlapping chunks of approximately `chunk_size` words.
    Overlap ensures context isn't lost at boundaries.
    """
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def store_document(doc_id: str, text: str, metadata: dict) -> int:
    """
    Chunk the extracted text and store it in a ChromaDB collection.

    Args:
        doc_id:   Unique ID for this document (becomes the collection name).
        text:     Full extracted text from the file.
        metadata: Additional metadata to attach to every chunk.

    Returns:
        Number of chunks stored.
    """
    client = _get_chroma()
    ef     = _get_embedding_fn()

    # Each document gets its own collection for clean isolation
    collection_name = f"doc_{doc_id.replace('-', '_')}"

    # Delete old collection if it exists (re-upload scenario)
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    chunks = _chunk_text(text)
    if not chunks:
        return 0

    ids       = [str(uuid.uuid4()) for _ in chunks]
    metadatas = [{**metadata, "chunk_index": i} for i in range(len(chunks))]

    collection.add(documents=chunks, ids=ids, metadatas=metadatas)
    return len(chunks)


def query_document(doc_id: str, question: str, top_k: int = 5) -> List[Dict]:
    """
    Perform a semantic similarity search against a stored document.

    Args:
        doc_id:   The document ID to search within.
        question: The user's natural language question.
        top_k:    Number of top matching chunks to return.

    Returns:
        List of dicts with 'text', 'score', and 'metadata' keys.
    """
    client = _get_chroma()
    ef     = _get_embedding_fn()

    collection_name = f"doc_{doc_id.replace('-', '_')}"

    try:
        collection = client.get_collection(
            name=collection_name,
            embedding_function=ef,
        )
    except Exception:
        return []

    results = collection.query(
        query_texts=[question],
        n_results=min(top_k, collection.count()),
        include=["documents", "distances", "metadatas"],
    )

    output = []
    if results and results.get("documents"):
        for doc, dist, meta in zip(
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0],
        ):
            output.append({
                "text":     doc,
                "score":    round(1 - dist, 4),   # cosine similarity
                "metadata": meta,
            })
    return output


def delete_document(doc_id: str) -> bool:
    """Delete a document's ChromaDB collection."""
    client = _get_chroma()
    collection_name = f"doc_{doc_id.replace('-', '_')}"
    try:
        client.delete_collection(collection_name)
        return True
    except Exception:
        return False


def list_documents() -> List[str]:
    """Return all stored document collection names."""
    client = _get_chroma()
    return [c.name for c in client.list_collections()]
