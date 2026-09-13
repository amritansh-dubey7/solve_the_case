"""
Pydantic v2 schemas for "Solve the Case".

These are reused verbatim across every phase of the project. Do not add
extra fields or extra schemas beyond what is defined here — the fixed
project spec calls these out explicitly so that later phases (retrieval,
agents, endpoints, frontend) can all rely on a single, stable contract.
"""

from pydantic import BaseModel


class DocumentMeta(BaseModel):
    document_id: str
    type: str
    timestamp: str | None
    verified: bool
    source: str


class Entity(BaseModel):
    entity_id: str
    name: str
    type: str
    aliases: list[str] = []


class Relationship(BaseModel):
    source_id: str
    target_id: str
    relation: str
    document_id: str


class Citation(BaseModel):
    document_id: str
    claim: str
    verified: bool


class InvestigationResult(BaseModel):
    theory: str
    suspect_id: str
    confidence: float
    citations: list[Citation]
    needs_more_evidence: bool
    retries_used: int
    reasoning_trace: list[str]


class FactCheckResult(BaseModel):
    challenged_theory: str
    contradictions: list[Citation]
    alternative_suspects: list[str]
    weaknesses: list[str]
    confidence_delta: float


class VerdictRequest(BaseModel):
    suspect_id: str
    supporting_citations: list[Citation]


class VerdictResult(BaseModel):
    correct: bool
    score: float
    explanation: str
