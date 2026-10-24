"""Handoff nodes — Phase 3.

Node chain executed when a conversation is escalated to a human agent:

    handoff_entry  →  notify  →  pause  →  END

handoff_entry  creates a support ticket in Postgres and sets status.
notify         posts a Slack alert via Incoming Webhook (skipped if no URL is set).
pause          calls interrupt() — graph execution halts until an agent resumes.
               On resume, the agent's message is appended and status may become resolved.

Why notify and pause are separate nodes:
    LangGraph replays the paused node from its first line when the graph resumes.
    If the Slack call lived inside pause it would fire twice. Keeping the side effect
    in notify (the node before interrupt) guarantees exactly-once delivery.
"""
from __future__ import annotations

import json
import os
import urllib.request
import uuid

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable
from langgraph.types import interrupt

from .db import conn
from .state import SupportState


# ── Node: handoff_entry ───────────────────────────────────────────────────────

@traceable(name="handoff_entry")
def handoff_entry(state: SupportState, config: RunnableConfig) -> dict:
    """Create a support ticket and flip status to awaiting_human."""
    ticket_id = str(uuid.uuid4())
    thread_id = config["configurable"].get("thread_id", "unknown")

    summary = (
        state.get("summary")
        or state["messages"][-1].content[:400]
    )

    conn.execute(
        "INSERT INTO support_tickets (ticket_id, thread_id, summary) VALUES (%s, %s, %s)",
        (ticket_id, thread_id, summary[:500]),
    )

    return {
        "ticket_id": ticket_id,
        "status":    "awaiting_human",
    }


# ── Node: notify ──────────────────────────────────────────────────────────────

@traceable(name="notify")
def notify(state: SupportState, config: RunnableConfig) -> dict:
    """Post a Slack alert. Silently skips if SLACK_WEBHOOK_URL is not set."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        return {}

    thread_id  = config["configurable"].get("thread_id", "unknown")
    ticket_id  = state.get("ticket_id", "N/A")
    last_msg   = state["messages"][-1].content if state["messages"] else ""
    summary    = state.get("summary") or "No summary yet."
    score      = state.get("top_score", 0.0)
    streak     = state.get("low_conf_streak", 0)

    text = (
        f"*:sos: Support escalation*\n"
        f"*Ticket:* `{ticket_id}`\n"
        f"*Thread:* `{thread_id}`\n"
        f"*Last message:* {last_msg[:300]}\n"
        f"*Summary:* {summary[:400]}\n"
        f"*Top score:* {score:.3f}  |  *Streak:* {streak}"
    )

    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # notification failure must not block the handoff

    return {}


# ── Node: pause ───────────────────────────────────────────────────────────────

def pause(state: SupportState) -> dict:
    """Halt graph execution until an agent resumes with Command(resume=payload).

    interrupt() checkpoints the full graph state. On resume, execution continues
    from after the interrupt() call. The agent's message is appended here and
    status is flipped to resolved if the payload says so.

    Not decorated with @traceable — interrupt() raises internally and traceable
    would not capture the span cleanly across the pause/resume boundary.
    """
    resume_payload = interrupt({
        "ticket_id": state.get("ticket_id"),
        "message":   "Waiting for human agent",
    })

    if isinstance(resume_payload, dict):
        agent_msg = resume_payload.get("agent_message", "")
        resolved  = resume_payload.get("resolved", False)
    else:
        agent_msg = str(resume_payload)
        resolved  = False

    new_status = "resolved" if resolved else state.get("status", "awaiting_human")

    if resolved:
        conn.execute(
            "UPDATE support_tickets SET status = 'resolved', resolved_at = NOW() "
            "WHERE ticket_id = %s",
            (state.get("ticket_id"),),
        )

    return {
        "messages": [AIMessage(content=agent_msg)],
        "status":   new_status,
    }
