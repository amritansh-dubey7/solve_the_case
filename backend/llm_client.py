"""
Single wrapper module for all LLM calls in this project.

Per the fixed project spec, every LLM call in the backend is routed through
this file, with the API key read from .env (not hardcoded). Later phases
(Investigator agent, Fact-Checker agent, /interrogate endpoint) will add
their own functions here (e.g. call_llm_theory, call_llm_judge,
call_llm_persona) but should follow the same pattern established by
call_llm_extract below: a plain function that takes a prompt/text and
returns structured data, with the actual provider call isolated inside it.

call_llm_extract() now makes a real Anthropic API call (previously a
stub). It sends a chunk of document text, asks the model to return
entities and relationships as JSON, parses and validates that JSON against
the Entity / Relationship Pydantic schemas, and returns plain dicts to the
caller (ingestion.py). If the call or parsing fails for any reason, it
logs a warning and returns an empty extraction result rather than crashing
the ingestion pipeline for the whole corpus.
"""

import json
import logging
import os

import requests
from dotenv import load_dotenv
from pydantic import ValidationError

from schemas import Entity, Relationship

load_dotenv()

# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------
# LLM_PROVIDER picks which backend every call_llm_* function in this file
# uses. Every function below still calls the single shared helper
# _call_llm_json() — only that helper knows about provider differences, so
# nothing else in the codebase (agents, main.py, ingestion.py) needs to
# change when you switch providers.
#
#   LLM_PROVIDER=anthropic  (default) — needs ANTHROPIC_API_KEY, paid
#   LLM_PROVIDER=groq                 — needs GROQ_API_KEY, has a free tier
#
# Get a free Groq key at https://console.groq.com/keys (no credit card).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Kept for backwards compatibility with any code that still imports this name.
EXTRACTION_MODEL = ANTHROPIC_MODEL

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = """You extract named entities and relationships \
from a single paragraph of a detective-case document (witness statement, \
police report, email, diary entry, phone log, forensic report, anonymous \
tip, or news article).

Return ONLY a JSON object, no preamble, no markdown code fences, no \
explanation. The JSON must have exactly this shape:

{
  "entities": [
    {"entity_id": "string", "name": "string", "type": "string", "aliases": ["string", ...]}
  ],
  "relationships": [
    {"source_id": "string", "target_id": "string", "relation": "string"}
  ]
}

Rules:
- entity_id must be a short, stable, lowercase snake_case slug derived from \
the entity's name (e.g. "marcus_whitfield", "wpd_precinct_4"). Reuse the \
same entity_id for the same real-world entity if it is mentioned more than \
once in this paragraph, so relationships can reference it consistently.
- type should be a short category: "person", "organization", "location", \
"object", "vehicle", or similar.
- aliases should list any other names/nicknames/titles used for this \
entity in this paragraph (may be empty).
- relationships: source_id and target_id must each match an entity_id from \
the entities list in this same response. relation should be a short \
lowercase phrase describing the connection (e.g. "employed_by", \
"married_to", "witnessed", "suspected_of", "owns", "called").
- Do not invent facts not stated or clearly implied in the text.
- If the paragraph contains no clear entities or relationships, return \
{"entities": [], "relationships": []}.
- Do NOT include a document_id field on relationships — the caller adds \
that itself from context you don't have.
"""


def _strip_code_fences(raw: str) -> str:
    """Defensively strip ```json ... ``` fences if the model adds them
    despite being told not to."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _call_anthropic(system_prompt: str, user_content: str, max_tokens: int) -> str | None:
    """Call Claude via the Anthropic SDK. Returns raw text, or None on failure."""
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — skipping LLM call.")
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
    except Exception as e:
        logger.warning("Anthropic API call failed: %s", e)
        return None


def _call_groq(system_prompt: str, user_content: str, max_tokens: int) -> str | None:
    """
    Call a Groq-hosted model and return the final text response.

    Retries with backoff on 429 (rate limit) responses — but capped hard:
    a single interactive request (interrogate, investigate, etc.) must not
    block long enough for Render's own proxy to kill it as unresponsive,
    which shows up to the frontend as a bare connection failure (looks like
    a CORS error, but isn't one) rather than a clean error response. So
    this caps both the number of retries and the wait per retry — better
    to fail fast and return None (caller already handles that gracefully)
    than to hang past the platform's timeout.
    """
    import re
    import time

    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set — skipping LLM call.")
        return None

    max_retries = 2
    max_wait_seconds = 8.0
    response = None

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,

                    "max_completion_tokens": max_tokens,

                    # Disable unnecessary reasoning for these structured tasks
                    "reasoning_effort": "none",

                    # Make sure reasoning is NOT mixed into message content
                    "reasoning_format": "hidden",

                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_content,
                        },
                    ],
                },
                timeout=30,
            )

            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

        except requests.exceptions.HTTPError as e:
            is_rate_limit = response is not None and response.status_code == 429
            if is_rate_limit and attempt < max_retries:
                wait_seconds = 3.0 * (attempt + 1)  # fallback fixed backoff
                try:
                    body = response.json()
                    match = re.search(
                        r"try again in ([\d.]+)s", body["error"]["message"]
                    )
                    if match:
                        wait_seconds = float(match.group(1)) + 0.5
                except Exception:
                    pass
                wait_seconds = min(wait_seconds, max_wait_seconds)
                logger.warning(
                    "Groq rate-limited (attempt %d/%d), waiting %.1fs before retry",
                    attempt + 1, max_retries, wait_seconds,
                )
                time.sleep(wait_seconds)
                continue
            logger.warning(
                "Groq API call failed: %s | Response: %s",
                e,
                response.text if response is not None else "No response",
            )
            return None

        except Exception as e:
            logger.warning("Groq API call failed: %s", e)
            return None

    return None


def _call_llm_json(system_prompt: str, user_content: str, max_tokens: int = 1024) -> dict | None:
    """
    Shared helper: call whichever provider LLM_PROVIDER selects with a
    system prompt that demands a bare JSON object back, strip stray code
    fences, and json.loads it.

    Returns the parsed dict, or None if the API call failed or the response
    wasn't valid JSON. Callers are responsible for validating/using the
    parsed structure — this helper only handles the API+JSON mechanics
    common to every LLM call in this file.
    """
    if LLM_PROVIDER == "groq":
        raw_text = _call_groq(system_prompt, user_content, max_tokens)
    elif LLM_PROVIDER == "anthropic":
        raw_text = _call_anthropic(system_prompt, user_content, max_tokens)
    else:
        logger.warning("Unknown LLM_PROVIDER=%r — expected 'anthropic' or 'groq'.", LLM_PROVIDER)
        return None

    if raw_text is None:
        return None

    try:
        return json.loads(_strip_code_fences(raw_text))
    except json.JSONDecodeError as e:
        logger.warning(
            "LLM call returned invalid JSON: %s | Raw response: %r",
            e,
            raw_text
    )
        return None


# Backwards-compatible alias — older code in this file (and any external
# callers) referring to the previous Anthropic-only helper name still works.
_call_claude_json = _call_llm_json


_THEORY_SYSTEM_PROMPT = """You are the Investigator agent in a detective-case \
RAG system. You are given an overview of the case evidence gathered so far \
and (if available) a summary of the entity graph extracted from the case \
documents. Your job is to name ONE suspect and propose a rough hypothesis \
(theory of the crime) grounded ONLY in what's in the evidence you were \
given — never invent facts not present in it.

Return ONLY a JSON object, no preamble, no markdown fences:
{
  "suspect_id": "string",
  "suspect_name": "string",
  "theory": "string — 2-4 sentences: your rough hypothesis of what happened and why this suspect",
  "initial_query": "string — a short search-engine-style query (not a full sentence) to retrieve evidence supporting this theory, e.g. 'Elena Rodriguez motive financial dispute'"
}

Rules:
- If a list of candidate suspect entity_ids is provided, suspect_id MUST be \
exactly one of those ids. suspect_name should be that entity's name.
- If no candidate list is provided, invent a suspect_id as a lowercase \
snake_case slug of the suspect's name (e.g. "elena_rodriguez"), based only \
on a name that actually appears in the evidence given to you.
- Do not treat any passage marked (verified: False) as established fact — \
you may treat it only as an unverified lead, and should not name a suspect \
based solely on unverified evidence.
"""

_JUDGE_SYSTEM_PROMPT = """You are the evidence-sufficiency judge for the \
Investigator agent in a detective-case RAG system. You are given a \
suspect_id, a rough theory, and a list of newly retrieved evidence \
candidates (each with document_id, text, and a verified flag). Your job is \
twofold:

1. For each candidate that is genuinely relevant to the theory against this \
specific suspect, classify it into exactly one category: "motive", \
"means", or "opportunity" (or "irrelevant" if it doesn't meaningfully \
support any of those three for this suspect — omit irrelevant ones from \
your output entirely).
2. Decide whether the *verified* evidence collected so far (see "already \
covered categories" below, which reflects verified evidence from prior \
rounds) plus what you just classified now covers all three of motive, \
means, and opportunity with at least one VERIFIED (verified: true) \
citation each. Unverified (verified: false) evidence must NOT count toward \
sufficiency, even if you tag it with a category — it may only be surfaced \
as an unverified lead.

Return ONLY a JSON object, no preamble, no markdown fences:
{
  "tagged": [
    {"document_id": "string", "claim": "string — a short 1-2 sentence paraphrase of what this evidence shows", "category": "motive" | "means" | "opportunity"}
  ],
  "sufficient": true or false,
  "missing_categories": ["motive", ...],
  "next_query": "string or null — if not sufficient, a short search-engine-style query targeting the missing category/categories specifically for this suspect; null if sufficient"
}

Only tag document_ids that literally appear in the candidates you were \
given — never invent a document_id.
"""


def call_llm_theory(case_overview: str, graph_summary: str, candidate_suspects: list[str] | None) -> dict | None:
    """
    Ask the LLM to form an initial theory: name a suspect_id + rough
    hypothesis, grounded in the given case overview and graph summary.

    Args:
        case_overview: text summary of the most relevant case evidence
            (e.g. top hybrid_search hits for a broad case query).
        graph_summary: text summary of the entity graph (person entities
            and their relationships), or "" if the graph is empty.
        candidate_suspects: optional list of valid suspect entity_ids to
            constrain the LLM's choice to (graph person-entity ids).

    Returns a dict {"suspect_id", "suspect_name", "theory", "initial_query"},
    or None if the call/parsing failed.
    """
    user_content = f"CASE OVERVIEW:\n{case_overview}\n\nENTITY GRAPH SUMMARY:\n{graph_summary or '(graph is empty — no entities extracted yet)'}\n\n"
    if candidate_suspects:
        user_content += f"CANDIDATE SUSPECT IDS (you must pick one of these): {candidate_suspects}\n"
    else:
        user_content += "CANDIDATE SUSPECT IDS: none provided — name a suspect based on a person mentioned in the case overview.\n"

    parsed = _call_claude_json(_THEORY_SYSTEM_PROMPT, user_content, max_tokens=512)
    if not parsed:
        return None
    if not all(k in parsed for k in ("suspect_id", "suspect_name", "theory", "initial_query")):
        logger.warning("call_llm_theory: response missing required keys: %s", parsed)
        return None
    return parsed


def call_llm_judge_evidence(
    theory: str,
    suspect_id: str,
    candidates: list[dict],
    covered_categories: list[str],
) -> dict | None:
    """
    Ask the LLM to (a) tag each retrieved evidence candidate with a
    motive/means/opportunity category (or drop it as irrelevant), and (b)
    judge whether motive/means/opportunity are now all covered by verified
    evidence, proposing a reformulated query for whatever's still missing.

    Args:
        theory: the Investigator's current rough hypothesis.
        suspect_id: the suspect this theory is about.
        candidates: list of {document_id, text, verified} dicts, i.e. the
            raw hybrid_search results from this retrieval round.
        covered_categories: motive/means/opportunity categories already
            satisfied by VERIFIED citations from prior rounds.

    Returns a dict {"tagged", "sufficient", "missing_categories",
    "next_query"}, or None if the call/parsing failed.
    """
    candidates_text = "\n".join(
        f"- document_id={c['document_id']} verified={c['verified']}: {c['text'][:400]}"
        for c in candidates
    )
    user_content = (
        f"SUSPECT: {suspect_id}\n"
        f"THEORY: {theory}\n"
        f"ALREADY-COVERED CATEGORIES (from verified evidence in prior rounds): {covered_categories or 'none yet'}\n\n"
        f"NEWLY RETRIEVED CANDIDATES:\n{candidates_text if candidates_text else '(none)'}\n"
    )

    parsed = _call_claude_json(_JUDGE_SYSTEM_PROMPT, user_content, max_tokens=1024)
    if not parsed:
        return None
    if not all(k in parsed for k in ("tagged", "sufficient", "missing_categories", "next_query")):
        logger.warning("call_llm_judge_evidence: response missing required keys: %s", parsed)
        return None
    return parsed


_PERSONA_SYSTEM_PROMPT = """You are role-playing as a suspect being interrogated \
in a detective-case RAG system. You are given the suspect's name, a set of \
retrieved case documents that mention or relate to them (each flagged \
verified true/false), and the conversation so far. Answer the detective's \
latest message IN CHARACTER as this suspect.

Hard rules — follow all of them:
- You may state as fact ONLY what is actually contained in the "RETRIEVED \
DOCUMENTS" given to you below. Never invent facts, dates, names, or events \
not present there.
- Treat documents marked (verified: False) as things you would NOT confirm \
or admit to — you may vaguely acknowledge a rumor exists ("I've heard \
people say...") but never confirm it as true, since it isn't established.
- Stay in character: a plausible human suspect, not an AI assistant. Do not \
break character, do not mention "documents" or "retrieval" explicitly to \
the detective.
- If your motive/involvement make a topic uncomfortable, you may be \
evasive, defensive, change the subject, or answer partially — that's \
realistic, not a rule violation. You do not have to volunteer damaging \
information.
- If asked about something with NO support in the retrieved documents, say \
you don't know, don't remember, or deflect — do not fabricate an answer.
- Keep replies conversational: 1-4 sentences, like real interrogation-room \
dialogue, not an essay.

Return ONLY a JSON object, no preamble, no markdown fences:
{
  "reply": "string — the suspect's in-character spoken reply"
}
"""


def call_llm_interrogate(
    suspect_name: str,
    user_message: str,
    grounding_documents: list[dict],
    conversation_history: list[dict],
) -> dict | None:
    """
    Ask the LLM to answer, in character as `suspect_name`, the detective's
    latest `user_message`, grounded ONLY in `grounding_documents` (list of
    {document_id, text, verified} — the suspect-biased hybrid_search hits
    for this turn) and aware of `conversation_history` (list of
    {role: "detective"|"suspect", "content": str}, oldest first).

    Returns a dict {"reply": str}, or None if the call/parsing failed.
    """
    docs_text = "\n".join(
        f"- document_id={d['document_id']} verified={d['verified']}: {d['text'][:400]}"
        for d in grounding_documents
    ) or "(no relevant documents retrieved for this message)"

    history_text = "\n".join(
        f"{turn['role'].upper()}: {turn['content']}" for turn in conversation_history
    ) or "(this is the first message of the interrogation)"

    user_content = (
        f"SUSPECT NAME: {suspect_name}\n\n"
        f"RETRIEVED DOCUMENTS (only source of facts you may use):\n{docs_text}\n\n"
        f"CONVERSATION SO FAR:\n{history_text}\n\n"
        f"DETECTIVE'S LATEST MESSAGE: {user_message}\n"
    )

    parsed = _call_claude_json(_PERSONA_SYSTEM_PROMPT, user_content, max_tokens=400)
    if not parsed:
        return None
    if "reply" not in parsed:
        logger.warning("call_llm_interrogate: response missing 'reply' key: %s", parsed)
        return None
    return parsed


def call_llm_extract(text: str) -> dict:
    """
    LLM-based entity/relationship extraction from a document chunk.

    Sends `text` to Claude with a prompt instructing it to identify named
    entities and relationships between them, asks for the result as JSON,
    parses and validates that JSON against the Entity / Relationship
    Pydantic schemas from schemas.py, and returns the validated data as
    plain dicts.

    Args:
        text: A single chunk of document text (paragraph-level) to extract
              entities and relationships from.

    Returns:
        A dict with the shape {"entities": [...], "relationships": [...]}
        where each item is a plain dict matching the Entity / Relationship
        schema fields (relationships omit document_id — the caller,
        ingestion.py, fills that in from context). On any API, parsing, or
        validation failure, returns {"entities": [], "relationships": []}
        and logs a warning rather than raising, so one bad chunk doesn't
        abort ingestion for the whole corpus.
    """
    if not text.strip():
        return {"entities": [], "relationships": []}

    parsed = _call_claude_json(_EXTRACTION_SYSTEM_PROMPT, text, max_tokens=700)
    if parsed is None:
        return {"entities": [], "relationships": []}

    validated_entities: list[dict] = []
    seen_entity_ids: set[str] = set()
    for raw_entity in parsed.get("entities", []):
        try:
            entity = Entity(**raw_entity)
        except ValidationError as e:
            logger.warning("Skipping invalid entity from LLM output: %s", e)
            continue
        validated_entities.append(entity.model_dump())
        seen_entity_ids.add(entity.entity_id)

    validated_relationships: list[dict] = []
    for raw_relationship in parsed.get("relationships", []):
        # document_id is filled in by the caller (ingestion.py); supply a
        # placeholder here purely so the Relationship schema validates —
        # the caller overwrites this field unconditionally.
        candidate = {**raw_relationship, "document_id": "__pending__"}
        try:
            relationship = Relationship(**candidate)
        except ValidationError as e:
            logger.warning("Skipping invalid relationship from LLM output: %s", e)
            continue
        # Only keep relationships whose endpoints are entities this same
        # response actually returned — prevents dangling references.
        if (
            relationship.source_id not in seen_entity_ids
            or relationship.target_id not in seen_entity_ids
        ):
            logger.warning(
                "Skipping relationship with unknown endpoint(s): %s -> %s",
                relationship.source_id,
                relationship.target_id,
            )
            continue
        rel_dict = relationship.model_dump()
        del rel_dict["document_id"]  # caller sets this itself
        validated_relationships.append(rel_dict)

    return {"entities": validated_entities, "relationships": validated_relationships}
