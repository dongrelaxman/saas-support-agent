from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.documents import Document
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SupportState(TypedDict):
    """Full state carried through every node of the support graph.

    add_messages reducer appends incoming messages rather than overwriting,
    which is the standard LangGraph pattern for chat history.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    summary: str                                  # rolling summary of trimmed history
    retrieved: list[Document]                     # chunks returned by the last retrieve call
    top_score: float                              # highest similarity score from retrieve
    low_conf_streak: int                          # consecutive low-confidence turns
    human_requested: bool                         # user explicitly asked for a human
    status: Literal["bot", "awaiting_human", "resolved"]
    ticket_id: str | None                         # set when a support ticket is created
