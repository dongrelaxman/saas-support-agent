"""Memory management — Phase 4.

trim_summarize runs after every normal turn (answer or non-escalating hedged_reply).
When the message list exceeds memory.message_window (default 20), the oldest
memory.summary_keep (default 10) messages are compressed into a rolling summary and
removed from the active window.  A SystemMessage containing the summary is prepended
so the LLM always has context of the earlier conversation.

Why rolling summary instead of hard truncation:
  Truncation loses context that the user might reference later ("as I mentioned at
  the start…").  Rolling summary compresses without discarding — the trade-off is
  that LLM interpretation can subtly distort facts.  For support use cases, the KB
  provides ground truth, so this risk is acceptable.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from langchain_core.messages import RemoveMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from .state import SupportState

_cfg    = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())
_window = _cfg["memory"]["message_window"]
_keep   = _cfg["memory"]["summary_keep"]

_llm = ChatOpenAI(model=_cfg["models"]["chat"], temperature=0)

_SUMMARIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a support-conversation summarizer.\n"
     "Produce a concise factual summary (under 200 words).\n"
     "Focus on: what the user asked, what was answered, any open issues.\n"
     "If an existing summary is provided, incorporate it — do not discard earlier facts."),
    ("human", "{content}"),
])


@traceable(name="trim_summarize")
def trim_summarize(state: SupportState) -> dict:
    """Compress the oldest messages into a rolling summary when the window fills up.

    Returns an empty dict (no-op) when the window has not been exceeded.
    Uses RemoveMessage so the add_messages reducer removes the old entries by ID.
    """
    messages = state["messages"]

    if len(messages) <= _window:
        return {}

    # Identify the oldest slice to compress
    to_compress = messages[:_keep]

    # Build the LLM prompt content
    convo_lines = "\n".join(
        f"{type(m).__name__}: {m.content}"
        for m in to_compress
    )
    old_summary = state.get("summary", "") or ""
    content = (
        f"Existing summary:\n{old_summary}\n\n" if old_summary else ""
    ) + f"Conversation to compress:\n{convo_lines}"

    response = _llm.invoke(_SUMMARIZE_PROMPT.format_messages(content=content))
    new_summary: str = response.content

    # RemoveMessage tells add_messages to delete each message by its ID
    remove_ops = [RemoveMessage(id=m.id) for m in to_compress]
    summary_msg = SystemMessage(content=f"[Conversation summary]\n{new_summary}")

    return {
        "messages": remove_ops + [summary_msg],
        "summary":  new_summary,
    }
