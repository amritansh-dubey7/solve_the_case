"""
Ingestion pipeline for "Solve the Case".

Loads the case corpus (corpus_manifest.json + document text files), chunks
each document at the paragraph level, runs each chunk through the LLM
extraction stub (llm_client.call_llm_extract) to pull out Entity and
Relationship objects, and assembles a networkx.MultiDiGraph:
  - nodes  = entities (keyed by entity_id)
  - edges  = relationships, carrying document_id provenance and a
             `verified` flag copied from that relationship's source
             document's manifest entry

The resulting graph is saved to /corpus/case_001/graph.json via
networkx.node_link_data.

This phase does NOT implement retrieval or agents — those are separate
files added in later phases.
"""

import json
import os

import networkx as nx

from llm_client import call_llm_extract
from schemas import DocumentMeta, Entity, Relationship

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "corpus", "case_001")
DOCUMENTS_DIR = os.path.join(CORPUS_DIR, "documents")
MANIFEST_PATH = os.path.join(CORPUS_DIR, "corpus_manifest.json")
GRAPH_OUTPUT_PATH = os.path.join(CORPUS_DIR, "graph.json")


def load_manifest() -> list[DocumentMeta]:
    """Load and validate corpus_manifest.json into DocumentMeta objects."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [DocumentMeta(**entry) for entry in raw]


def load_document_text(document_id: str) -> str:
    """Load the raw text of a single document by its document_id."""
    path = os.path.join(DOCUMENTS_DIR, f"{document_id}.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def chunk_document(text: str) -> list[str]:
    """
    Chunk a document's text at the paragraph level.

    Paragraphs are split on blank lines. Empty/whitespace-only chunks are
    dropped. This is intentionally simple (no overlap, no token-based
    splitting) per the fixed spec's "keep it small and clean" rule.
    """
    raw_paragraphs = text.split("\n\n")
    chunks = [p.strip() for p in raw_paragraphs if p.strip()]
    return chunks


def extract_entities_and_relationships(
    document_id: str, chunks: list[str]
) -> tuple[list[Entity], list[Relationship]]:
    """
    Run the LLM extraction stub over every chunk of a document and collect
    the resulting Entity / Relationship objects.

    Since ingestion makes one LLM call per chunk across every document in
    the corpus, a small delay between calls is added below to stay under
    free-tier provider rate limits (Groq's free tier in particular has a
    low tokens-per-minute cap) — without it, most calls in a full ingestion
    run get rate-limited and silently return empty results (see
    llm_client._call_groq's retry/backoff for the other half of this fix).
    """
    import time

    entities: dict[str, Entity] = {}
    relationships: list[Relationship] = []

    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(1.5)
        result = call_llm_extract(chunk)

        for raw_entity in result.get("entities", []):
            entity = Entity(**raw_entity)
            # De-duplicate by entity_id, merging aliases if seen again.
            if entity.entity_id in entities:
                existing = entities[entity.entity_id]
                merged_aliases = list(set(existing.aliases) | set(entity.aliases))
                entities[entity.entity_id] = existing.model_copy(
                    update={"aliases": merged_aliases}
                )
            else:
                entities[entity.entity_id] = entity

        for raw_relationship in result.get("relationships", []):
            # Ensure provenance always points at the document being processed.
            raw_relationship = {**raw_relationship, "document_id": document_id}
            relationships.append(Relationship(**raw_relationship))

    return list(entities.values()), relationships


def build_graph(
    manifest: list[DocumentMeta],
) -> tuple[nx.MultiDiGraph, int, int]:
    """
    Run extraction across every document in the manifest and assemble a
    networkx.MultiDiGraph.

    - Nodes: one per unique entity_id, with entity fields as node attributes.
    - Edges: one per relationship, attributed with `relation`, `document_id`
      provenance, and a `verified` flag copied from that relationship's
      source document's manifest entry (DocumentMeta.verified).

    Returns the graph plus counts of documents processed, entities, and
    relationships (for the /ingest endpoint summary).
    """
    graph = nx.MultiDiGraph()

    verified_by_doc_id = {doc.document_id: doc.verified for doc in manifest}

    all_entities: dict[str, Entity] = {}
    total_relationships = 0

    for doc in manifest:
        text = load_document_text(doc.document_id)
        chunks = chunk_document(text)
        entities, relationships = extract_entities_and_relationships(
            doc.document_id, chunks
        )

        for entity in entities:
            if entity.entity_id not in all_entities:
                all_entities[entity.entity_id] = entity
                graph.add_node(
                    entity.entity_id,
                    name=entity.name,
                    type=entity.type,
                    aliases=entity.aliases,
                )

        for rel in relationships:
            # Make sure both endpoints exist as nodes even if entity
            # extraction only surfaced one side of the relationship.
            if rel.source_id not in graph:
                graph.add_node(rel.source_id, name=rel.source_id, type="unknown", aliases=[])
            if rel.target_id not in graph:
                graph.add_node(rel.target_id, name=rel.target_id, type="unknown", aliases=[])

            graph.add_edge(
                rel.source_id,
                rel.target_id,
                relation=rel.relation,
                document_id=rel.document_id,
                verified=verified_by_doc_id.get(rel.document_id, False),
            )
            total_relationships += 1

    return graph, len(all_entities), total_relationships


def save_graph(graph: nx.MultiDiGraph) -> str:
    """Save the graph to /corpus/case_001/graph.json via node_link_data."""
    data = nx.node_link_data(graph, edges="edges")
    with open(GRAPH_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return GRAPH_OUTPUT_PATH


def run_ingestion() -> dict:
    """
    Run the full ingestion pipeline end to end:
      load manifest -> chunk + extract per document -> build graph -> save.

    Returns a summary dict: number of documents processed, number of
    entities, number of relationships. Used directly by POST /ingest.
    """
    manifest = load_manifest()
    graph, entity_count, relationship_count = build_graph(manifest)
    save_graph(graph)

    return {
        "documents_processed": len(manifest),
        "entities": entity_count,
        "relationships": relationship_count,
        "graph_path": os.path.abspath(GRAPH_OUTPUT_PATH),
    }


if __name__ == "__main__":
    summary = run_ingestion()
    print(json.dumps(summary, indent=2))
