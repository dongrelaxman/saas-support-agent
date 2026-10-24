"""Support graph — Phase 4.

Graph topology:

    START
      │
      ▼
    route_entry  (checks status)
      ├── awaiting_human ──► holding_reply ──► END
      └── bot/resolved   ──► intent_check
                                  │
                     ┌────────────┴────────────┐
                     ▼ human_requested=False    ▼ human_requested=True
                  retrieve                  handoff_entry
                     │                          │
                     ▼                        notify
               confidence_router               │
                 │           │               pause ──► END
                 ▼           ▼
              answer    hedged_reply
                 │           │
                 └─────┬─────┘ streak < limit
                       ▼
                 trim_summarize ──► END
                            (streak ≥ limit branches to handoff_entry before trim)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from .db import checkpointer_conn, conn, setup_schema
from .handoff import handoff_entry, notify, pause
from .memory import trim_summarize
from .nodes import (
    answer,
    confidence_router,
    hedged_reply,
    holding_reply,
    intent_check,
    intent_router,
    retrieve,
    route_entry,
    streak_check,
)
from .state import SupportState

load_dotenv()


# ── Graph definition ──────────────────────────────────────────────────────────

def _build_graph(checkpointer=None):
    builder = StateGraph(SupportState)

    # ── nodes ──
    builder.add_node("intent_check",    intent_check)
    builder.add_node("holding_reply",   holding_reply)
    builder.add_node("retrieve",        retrieve)
    builder.add_node("answer",          answer)
    builder.add_node("hedged_reply",    hedged_reply)
    builder.add_node("trim_summarize",  trim_summarize)
    builder.add_node("handoff_entry",   handoff_entry)
    builder.add_node("notify",          notify)
    builder.add_node("pause",           pause)

    # ── entry: check status before anything ──
    builder.add_conditional_edges(
        START,
        route_entry,
        {"holding": "holding_reply", "proceed": "intent_check"},
    )

    # ── holding_reply always ends the turn ──
    builder.add_edge("holding_reply", END)

    # ── intent gate: explicit request → handoff, normal → retrieve ──
    builder.add_conditional_edges(
        "intent_check",
        intent_router,
        {"handoff": "handoff_entry", "retrieve": "retrieve"},
    )

    # ── confidence gate ──
    builder.add_conditional_edges(
        "retrieve",
        confidence_router,
        {"answer": "answer", "hedged_reply": "hedged_reply"},
    )

    # ── answer → trim → END ──
    builder.add_edge("answer",         "trim_summarize")
    builder.add_edge("trim_summarize", END)

    # ── streak gate: too many misses → handoff, otherwise trim → END ──
    builder.add_conditional_edges(
        "hedged_reply",
        streak_check,
        {"escalate": "handoff_entry", "trim": "trim_summarize"},
    )

    # ── handoff chain ──
    builder.add_edge("handoff_entry", "notify")
    builder.add_edge("notify",        "pause")
    builder.add_edge("pause",         END)

    return builder.compile(checkpointer=checkpointer)


# ── Schema and checkpointer setup ─────────────────────────────────────────────

setup_schema()

_checkpointer = PostgresSaver(checkpointer_conn)
_checkpointer.setup()


# ── Helpers (reused by frontend) ──────────────────────────────────────────────

def save_conversation(thread_id: str, title: str) -> None:
    conn.execute(
        "INSERT INTO conversation_titles (thread_id, title) VALUES (%s, %s)"
        " ON CONFLICT DO NOTHING",
        (thread_id, title),
    )


def get_all_conversations() -> list[dict]:
    rows = conn.execute(
        "SELECT thread_id, title FROM conversation_titles ORDER BY created_at DESC"
    ).fetchall()
    return [{"thread_id": r[0], "title": r[1]} for r in rows]


def get_open_tickets() -> list[dict]:
    rows = conn.execute(
        "SELECT ticket_id, thread_id, summary, created_at "
        "FROM support_tickets WHERE status = 'open' ORDER BY created_at DESC"
    ).fetchall()
    return [
        {"ticket_id": r[0], "thread_id": r[1], "summary": r[2], "created_at": str(r[3])}
        for r in rows
    ]


# ── Compiled graph ────────────────────────────────────────────────────────────

graph = _build_graph(checkpointer=_checkpointer)
