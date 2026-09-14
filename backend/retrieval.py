"""
Hybrid retrieval layer for "Solve the Case".

Combines:
  - lexical_search: BM25 (rank_bm25) over paragraph-level chunks
  - semantic_search: fastembed "BAAI/bge-small-en-v1.5" embeddings (ONNX
    runtime, no torch) + cosine similarity, computed with plain numpy
    (no vector DB)
  - hybrid_search: fuses both rankings via Reciprocal Rank Fusion (RRF)

All three functions return the same output shape: a list of dicts with
document_id, text, score, verified — so POST /search_evidence (added to
main.py in this phase) can return them directly, reusing the
Citation-shaped fields (document_id, claim/text snippet, verified).

Chunking reuses ingestion.load_manifest / ingestion.load_document_text /
ingestion.chunk_document exactly as built in Phase 2 — this file does not
redefine or duplicate that logic.

Note on the embedding backend: this originally used sentence-transformers
(torch-based). Swapped to fastembed (ONNX runtime, ~100MB, no torch) so the
service fits comfortably inside a 512MB free-tier deployment — the torch
build alone pushed memory usage over that limit on Render's free plan.
Output shape and behavior (normalized embeddings, cosine similarity via
dot product) are unchanged.
"""

import re

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from ingestion import chunk_document, load_document_text, load_manifest

_EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Module-level caches so the corpus is only chunked, tokenized, and embedded
# once per process (not once per request). Populated lazily on first use.
_chunks: list[dict] | None = None
_bm25_index: BM25Okapi | None = None
_embedding_model: TextEmbedding | None = None
_chunk_embeddings: np.ndarray | None = None


def _tokenize(text: str) -> list[str]:
    """Simple lowercase word tokenizer used for BM25."""
    return re.findall(r"\w+", text.lower())


def _load_chunks() -> list[dict]:
    """
    Load the manifest, chunk every document at the paragraph level (reusing
    Phase 2's chunk_document), and return a flat list of chunk records:
    {document_id, text, verified}.
    """
    global _chunks
    if _chunks is not None:
        return _chunks

    manifest = load_manifest()
    verified_by_doc_id = {doc.document_id: doc.verified for doc in manifest}

    chunks: list[dict] = []
    for doc in manifest:
        text = load_document_text(doc.document_id)
        for chunk_text in chunk_document(text):
            chunks.append(
                {
                    "document_id": doc.document_id,
                    "text": chunk_text,
                    "verified": verified_by_doc_id[doc.document_id],
                }
            )

    _chunks = chunks
    return _chunks


def _get_bm25_index() -> BM25Okapi:
    """Build (once) and return the BM25 index over all chunks."""
    global _bm25_index
    if _bm25_index is not None:
        return _bm25_index

    chunks = _load_chunks()
    tokenized_corpus = [_tokenize(c["text"]) for c in chunks]
    _bm25_index = BM25Okapi(tokenized_corpus)
    return _bm25_index


def _get_embedding_model() -> TextEmbedding:
    """Load (once) and return the fastembed (ONNX) embedding model."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding(model_name=_EMBEDDING_MODEL_NAME)
    return _embedding_model


def _embed(model: TextEmbedding, texts: list[str]) -> np.ndarray:
    """Run fastembed over a batch of texts and stack results into an array.

    fastembed's .embed() returns a generator of 1D numpy arrays — this
    materializes it into a single 2D array, matching the shape
    sentence-transformers' .encode(..., convert_to_numpy=True) used to
    return, so callers below are unchanged.
    """
    return np.array(list(model.embed(texts)))


def _get_chunk_embeddings() -> np.ndarray:
    """Compute (once) and return embeddings for every chunk, L2-normalized."""
    global _chunk_embeddings
    if _chunk_embeddings is not None:
        return _chunk_embeddings

    chunks = _load_chunks()
    model = _get_embedding_model()
    embeddings = _embed(model, [c["text"] for c in chunks])
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # avoid division by zero for a degenerate chunk
    _chunk_embeddings = embeddings / norms
    return _chunk_embeddings


def lexical_search(query: str, k: int) -> list[dict]:
    """
    BM25 lexical search over paragraph-level chunks.

    Returns up to k results, each: {document_id, text, score, verified},
    sorted by descending BM25 score.
    """
    chunks = _load_chunks()
    bm25 = _get_bm25_index()

    scores = bm25.get_scores(_tokenize(query))
    ranked_indices = np.argsort(scores)[::-1][:k]

    results = []
    for idx in ranked_indices:
        chunk = chunks[idx]
        results.append(
            {
                "document_id": chunk["document_id"],
                "text": chunk["text"],
                "score": float(scores[idx]),
                "verified": chunk["verified"],
            }
        )
    return results


def semantic_search(query: str, k: int) -> list[dict]:
    """
    Semantic search over paragraph-level chunks using sentence-transformers
    "all-MiniLM-L6-v2" embeddings and cosine similarity (plain numpy, no
    vector DB).

    Returns up to k results, each: {document_id, text, score, verified},
    sorted by descending cosine similarity.
    """
    chunks = _load_chunks()
    model = _get_embedding_model()
    chunk_embeddings = _get_chunk_embeddings()

    query_embedding = _embed(model, [query])[0]
    query_norm = np.linalg.norm(query_embedding)
    if query_norm > 0:
        query_embedding = query_embedding / query_norm

    similarities = chunk_embeddings @ query_embedding
    ranked_indices = np.argsort(similarities)[::-1][:k]

    results = []
    for idx in ranked_indices:
        chunk = chunks[idx]
        results.append(
            {
                "document_id": chunk["document_id"],
                "text": chunk["text"],
                "score": float(similarities[idx]),
                "verified": chunk["verified"],
            }
        )
    return results


def hybrid_search(query: str, k: int) -> list[dict]:
    """
    Fuse lexical_search and semantic_search rankings via Reciprocal Rank
    Fusion (RRF): score(chunk) = sum over each ranking it appears in of
    1 / (rrf_k + rank), where rank is 1-indexed position in that ranking.

    Retrieves a wider candidate pool from each sub-search (2*k, capped at
    the corpus size) so fusion has enough overlap to work with, then
    returns the top k fused results: {document_id, text, score, verified}.
    """
    RRF_K = 60  # standard RRF damping constant

    chunks = _load_chunks()
    pool_size = min(max(k * 2, k), len(chunks))

    lexical_results = lexical_search(query, pool_size)
    semantic_results = semantic_search(query, pool_size)

    # Chunks are uniquely identified by (document_id, text) since a chunk's
    # exact paragraph text is unique within a document in this corpus.
    fused_scores: dict[tuple[str, str], float] = {}
    chunk_lookup: dict[tuple[str, str], dict] = {}

    for ranking in (lexical_results, semantic_results):
        for rank, result in enumerate(ranking, start=1):
            key = (result["document_id"], result["text"])
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            chunk_lookup[key] = result

    ranked_keys = sorted(fused_scores.keys(), key=lambda key: fused_scores[key], reverse=True)

    results = []
    for key in ranked_keys[:k]:
        base = chunk_lookup[key]
        results.append(
            {
                "document_id": base["document_id"],
                "text": base["text"],
                "score": fused_scores[key],
                "verified": base["verified"],
            }
        )
    return results
