"""FastAPI backend — Phase 6.

Endpoints:
    POST  /api/chat                   stream response (SSE)
    POST  /api/resume                 agent resumes a paused thread
    GET   /api/threads                list all conversation threads
    POST  /api/threads                save a new thread title
    GET   /api/threads/{thread_id}    full thread state + escalation context
    GET   /api/tickets                open support tickets (REST fallback)
    WS    /ws/console                 real-time ticket push for agent console
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path

import yaml
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from backend.graph import get_all_conversations, get_open_tickets, graph, save_conversation

load_dotenv()

_cfg       = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())
_threshold = _cfg["retrieval"]["threshold"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    asyncio.create_task(_broadcast_ticket_updates())
    yield


app = FastAPI(title="TaskPilot Support API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    thread_id: str
    message: str

class ResumeRequest(BaseModel):
    thread_id: str
    agent_message: str
    resolved: bool = False

class SaveThreadRequest(BaseModel):
    thread_id: str
    title: str


# ── WebSocket console — real-time ticket push ─────────────────────────────────

_ws_clients: list[WebSocket] = []


async def _broadcast_ticket_updates() -> None:
    """Poll Postgres every 3 s; push the full ticket list when it changes."""
    known_ids: set[str] = set()
    while True:
        await asyncio.sleep(3)
        if not _ws_clients:
            continue
        try:
            tickets    = await asyncio.to_thread(get_open_tickets)
            current    = {t["ticket_id"] for t in tickets}
            if current == known_ids:
                continue
            known_ids  = current
            dead: list[WebSocket] = []
            for ws in list(_ws_clients):
                try:
                    await ws.send_json({"type": "tickets", "tickets": tickets})
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _ws_clients.remove(ws)
        except Exception:
            pass


@app.websocket("/ws/console")
async def console_ws(ws: WebSocket) -> None:
    await ws.accept()
    _ws_clients.append(ws)
    # Push current state immediately on connect
    try:
        tickets = await asyncio.to_thread(get_open_tickets)
        await ws.send_json({"type": "tickets", "tickets": tickets})
    except Exception:
        pass
    try:
        while True:
            await ws.receive_text()       # client sends "ping" keep-alives
    except WebSocketDisconnect:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ── SSE streaming helper ──────────────────────────────────────────────────────

_VISIBLE_NODES = {"answer", "hedged_reply", "holding_reply", "pause"}


async def _stream_graph(thread_id: str, message: str):
    event_q: queue.Queue = queue.Queue()

    def _run():
        try:
            config = {"configurable": {"thread_id": thread_id}}
            for msg, metadata in graph.stream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                stream_mode="messages",
            ):
                node = metadata.get("langgraph_node", "")
                if node not in _VISIBLE_NODES:
                    continue
                if hasattr(msg, "content") and msg.content:
                    event_q.put({"type": "token", "content": msg.content, "node": node})
        except Exception as exc:
            event_q.put({"type": "error", "content": str(exc)})
        finally:
            event_q.put(None)

    threading.Thread(target=_run, daemon=True).start()

    loop = asyncio.get_event_loop()
    while True:
        item = await loop.run_in_executor(None, event_q.get)
        if item is None:
            break
        yield f"data: {json.dumps(item)}\n\n"

    try:
        snap = await asyncio.to_thread(graph.get_state, {"configurable": {"thread_id": thread_id}})
        vals = snap.values
        yield f"data: {json.dumps({'type': 'state', 'status': vals.get('status', 'bot'), 'ticket_id': vals.get('ticket_id')})}\n\n"
    except Exception:
        pass

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ── HTTP endpoints ────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        _stream_graph(request.thread_id, request.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/resume")
async def resume(request: ResumeRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    result = await asyncio.to_thread(
        graph.invoke,
        Command(resume={"agent_message": request.agent_message, "resolved": request.resolved}),
        config,
    )
    last_msg = result["messages"][-1].content if result.get("messages") else ""
    return {"status": result.get("status", "awaiting_human"), "message": last_msg}


@app.get("/api/threads")
async def list_threads():
    return {"threads": await asyncio.to_thread(get_all_conversations)}


@app.post("/api/threads")
async def create_thread(request: SaveThreadRequest):
    await asyncio.to_thread(save_conversation, request.thread_id, request.title)
    return {"ok": True}


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snap = await asyncio.to_thread(graph.get_state, config)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    vals = snap.values
    messages = [
        {
            "role": (
                "human"  if m.__class__.__name__ == "HumanMessage"  else
                "system" if m.__class__.__name__ == "SystemMessage" else
                "ai"
            ),
            "content": m.content,
            "id":      getattr(m, "id", None),
        }
        for m in vals.get("messages", [])
    ]
    return {
        "thread_id":       thread_id,
        "status":          vals.get("status", "bot"),
        "ticket_id":       vals.get("ticket_id"),
        "summary":         vals.get("summary", ""),
        "top_score":       round(vals.get("top_score", 0.0), 4),
        "low_conf_streak": vals.get("low_conf_streak", 0),
        "threshold":       _threshold,
        "messages":        messages,
    }


@app.get("/api/tickets")
async def list_tickets():
    return {"tickets": await asyncio.to_thread(get_open_tickets)}
