"""Node functions and routing functions for the support graph.

Phase 1 nodes   : retrieve, answer
Phase 2 adds    : hedged_reply, confidence_router, streak_check
Phase 3 adds    : intent_check, holding_reply, route_entry, intent_router

LangSmith tracing:
  - LangGraph auto-traces every node as a child span of the graph run.
  - @traceable adds an explicit named span inside each node so the
    Weaviate query and the LLM call appear as separate sub-spans.
  - Routing functions are NOT decorated — they are pure conditional logic
    and do not need their own trace spans.
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path

import yaml
import weaviate
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langsmith import traceable
from weaviate.classes.init import Auth
from weaviate.classes.query import Filter, MetadataQuery

from .prompts import ANSWER_PROMPT, HEDGED_PROMPT
from .state import SupportState

# ── Config ────────────────────────────────────────────────────────────────────
_cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())

# ── LLMs ──────────────────────────────────────────────────────────────────────
_llm = ChatOpenAI(
    model=_cfg["models"]["chat"],
    temperature=0,
    streaming=True,
)

_intent_llm = ChatOpenAI(
    model=_cfg["models"]["intent"],
    temperature=0,
)

# ── Embeddings (reused for every query) ───────────────────────────────────────
_embeddings = OpenAIEmbeddings(model=_cfg["models"]["embeddings"])

# ── Weaviate client (lazy singleton) ──────────────────────────────────────────
_weaviate_client: weaviate.WeaviateClient | None = None


def _get_weaviate_client() -> weaviate.WeaviateClient:
    global _weaviate_client
    if _weaviate_client is None or not _weaviate_client.is_connected():
        _weaviate_client = weaviate.connect_to_weaviate_cloud(
            cluster_url=os.environ["WEAVIATE_URL"],
            auth_credentials=Auth.api_key(os.environ["WEAVIATE_API_KEY"]),
            skip_init_checks=True,
        )
        atexit.register(_weaviate_client.close)
    return _weaviate_client


# ── Intent classification prompt ──────────────────────────────────────────────

_INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a binary classifier.\n"
     "Does the user message ask to be connected to a human support agent or representative?\n"
     "Reply with exactly one word: YES or NO.\n\n"
     "Examples:\n"
     "  'I need help with my invoice'          → NO\n"
     "  'Can I speak with someone?'            → YES\n"
     "  'Get me a real person'                 → YES\n"
     "  'How do I reset my password?'          → NO\n"
     "  'I want to escalate this'              → YES\n"
     "  'Do you offer a free trial?'           → NO"),
    ("human", "{question}"),
])

_HUMAN_TRIGGERS = frozenset([
    "agent", "human", "representative", "speak to someone", "real person",
    "talk to someone", "connect me", "support agent", "live chat",
    "live support", "talk to a person", "speak with someone",
    "get me a human", "talk to human", "real agent", "speak to a human",
    "escalate", "i want a person", "need a person",
])


# ── Node: intent_check ────────────────────────────────────────────────────────

@traceable(name="intent_check")
def intent_check(state: SupportState) -> dict:
    """Detect explicit human-handoff requests.

    Fast keyword scan first; LLM classifier only when no keyword matches.
    """
    question = state["messages"][-1].content
    lower = question.lower()

    if any(trigger in lower for trigger in _HUMAN_TRIGGERS):
        return {"human_requested": True}

    response = _intent_llm.invoke(
        _INTENT_PROMPT.format_messages(question=question)
    )
    requested = response.content.strip().upper().startswith("YES")
    return {"human_requested": requested}


# ── Node: holding_reply ───────────────────────────────────────────────────────

@traceable(name="holding_reply")
def holding_reply(state: SupportState) -> dict:
    """Acknowledge messages sent while status == awaiting_human."""
    return {
        "messages": [AIMessage(
            content=(
                "A support agent has been notified and will join shortly. "
                "Your message has been added to the ticket."
            )
        )]
    }


# ── Node: retrieve ────────────────────────────────────────────────────────────

@traceable(name="retrieve")
def retrieve(state: SupportState) -> dict:
    """Embed the user question and query Weaviate for the top-k closest chunks."""
    question = state["messages"][-1].content

    query_vector = _embeddings.embed_query(question)

    client     = _get_weaviate_client()
    collection = client.collections.get(_cfg["weaviate"]["collection"])

    response = collection.query.near_vector(
        near_vector=query_vector,
        limit=_cfg["retrieval"]["top_k"],
        filters=Filter.by_property("archived").equal(False),
        return_metadata=MetadataQuery(certainty=True),
        return_properties=["text", "source", "archived"],
    )

    if not response.objects:
        return {"retrieved": [], "top_score": 0.0}

    docs_with_scores: list[tuple[Document, float]] = []
    for obj in response.objects:
        doc = Document(
            page_content=obj.properties["text"],
            metadata={
                "source":   obj.properties.get("source", ""),
                "archived": obj.properties.get("archived", False),
            },
        )
        score = obj.metadata.certainty if obj.metadata.certainty is not None else 0.0
        docs_with_scores.append((doc, score))

    docs, scores = zip(*docs_with_scores)
    return {
        "retrieved": list(docs),
        "top_score": float(max(scores)),
    }


# ── Node: answer ──────────────────────────────────────────────────────────────

@traceable(name="answer")
def answer(state: SupportState) -> dict:
    """Generate a grounded answer strictly from retrieved chunks.

    Resets low_conf_streak to 0 — a confident answer breaks the streak.
    """
    question = state["messages"][-1].content
    docs: list[Document] = state.get("retrieved", [])

    context = "\n\n".join(
        f"[Source: {doc.metadata.get('source', 'unknown')}]\n{doc.page_content}"
        for doc in docs
    )

    chain    = ANSWER_PROMPT | _llm
    response = chain.invoke({"context": context, "question": question})

    return {
        "messages":        [response],
        "low_conf_streak": 0,
    }


# ── Node: hedged_reply ────────────────────────────────────────────────────────

@traceable(name="hedged_reply")
def hedged_reply(state: SupportState) -> dict:
    """Low-confidence path: best-effort answer with explicit uncertainty notice.

    Increments low_conf_streak. When streak reaches streak_limit (default 3),
    streak_check routes to the handoff subgraph.
    """
    question = state["messages"][-1].content
    docs: list[Document] = state.get("retrieved", [])

    context = "\n\n".join(
        f"[Source: {doc.metadata.get('source', 'unknown')}]\n{doc.page_content}"
        for doc in docs
    ) if docs else "No relevant documents found."

    chain    = HEDGED_PROMPT | _llm
    response = chain.invoke({"context": context, "question": question})

    streak = state.get("low_conf_streak", 0)

    return {
        "messages":        [response],
        "low_conf_streak": streak + 1,
    }


# ── Routing: route_entry ──────────────────────────────────────────────────────

def route_entry(state: SupportState) -> str:
    """Check status before any routing — hold the user if already awaiting a human."""
    if state.get("status") == "awaiting_human":
        return "holding"
    return "proceed"


# ── Routing: intent_router ────────────────────────────────────────────────────

def intent_router(state: SupportState) -> str:
    """Route to handoff if the user explicitly requested a human, else retrieve."""
    if state.get("human_requested", False):
        return "handoff"
    return "retrieve"


# ── Routing: confidence_router ────────────────────────────────────────────────

def confidence_router(state: SupportState) -> str:
    """Route to answer if top_score meets the threshold, else hedged_reply."""
    threshold = _cfg["retrieval"]["threshold"]
    if state.get("top_score", 0.0) >= threshold:
        return "answer"
    return "hedged_reply"


# ── Routing: streak_check ─────────────────────────────────────────────────────

def streak_check(state: SupportState) -> str:
    """Escalate after streak_limit consecutive low-confidence turns.

    Returns 'trim' (not END) so the turn passes through trim_summarize before closing.
    """
    streak = state.get("low_conf_streak", 0)
    if streak >= _cfg["escalation"]["streak_limit"]:
        return "escalate"
    return "trim"
