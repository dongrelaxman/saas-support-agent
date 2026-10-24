"""Phase 3 tests — intent_check, handoff subgraph, interrupt/resume.

Four scenarios:

  1. explicit_request   — "Get me a human" on turn 1 → immediate handoff
                          status becomes awaiting_human, ticket_id is set
                          graph pauses at interrupt()

  2. late_request       — Normal answer then "I want to speak to someone"
                          Handoff fires on turn 2

  3. pause_and_resume   — Explicit request → verify interrupt → resume with
                          agent message → verify message appears + status

  4. holding_reply      — After escalation (status=awaiting_human), send
                          another user message → get holding_reply, not RAG

Run from the project root:
    python scripts/test_phase3.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from backend import graph

RUN_ID = int(time.time())

print("=" * 65)
print("Phase 3 Tests — intent check, handoff, interrupt/resume")
print("=" * 65)

passed = 0
failed = 0


def check(label: str, condition: bool) -> bool:
    mark = "✓" if condition else "✗"
    print(f"   {mark}  {label}")
    return condition


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — explicit human request → immediate handoff
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n── explicit_request ──────────────────────────────────────")

thread_id = f"test-p3-explicit-{RUN_ID}"
config    = {"configurable": {"thread_id": thread_id}}

result = graph.invoke(
    {"messages": [HumanMessage(content="Get me a human agent please")]},
    config=config,
)

status    = result.get("status", "bot")
ticket_id = result.get("ticket_id")
last_msg  = result["messages"][-1].content[:120].replace("\n", " ")

ok1 = all([
    check("status == awaiting_human", status == "awaiting_human"),
    check("ticket_id is set",         bool(ticket_id)),
])

print(f"   status={status}  ticket_id={ticket_id}")
print(f"   last_msg: {last_msg}...")

# Check the graph state — should be interrupted (pending tasks)
state_snapshot = graph.get_state(config)
has_interrupt = bool(state_snapshot.tasks)
check("graph is paused at interrupt()", has_interrupt)
ok1 = ok1 and has_interrupt

print(f"   → {'PASS' if ok1 else 'FAIL'}")
if ok1: passed += 1
else:   failed += 1


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — late human request (normal turn, then handoff)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n── late_request ──────────────────────────────────────────")

thread_id = f"test-p3-late-{RUN_ID}"
config    = {"configurable": {"thread_id": thread_id}}

# Turn 1: in-scope question → should answer normally
r1 = graph.invoke(
    {"messages": [HumanMessage(content="How much is the Pro plan?")]},
    config=config,
)
status1 = r1.get("status", "bot")
ok2_t1 = check("turn 1: status still bot", status1 == "bot")

# Turn 2: explicit human request → should handoff
r2 = graph.invoke(
    {"messages": [HumanMessage(content="I want to speak to a real person")]},
    config=config,
)
status2   = r2.get("status", "bot")
ticket_id2 = r2.get("ticket_id")
ok2_t2 = all([
    check("turn 2: status == awaiting_human", status2 == "awaiting_human"),
    check("turn 2: ticket_id is set",         bool(ticket_id2)),
])

ok2 = ok2_t1 and ok2_t2
print(f"   → {'PASS' if ok2 else 'FAIL'}")
if ok2: passed += 1
else:   failed += 1


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — pause → resume cycle
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n── pause_and_resume ──────────────────────────────────────")

thread_id = f"test-p3-resume-{RUN_ID}"
config    = {"configurable": {"thread_id": thread_id}}

# Step 1: trigger handoff (graph pauses)
graph.invoke(
    {"messages": [HumanMessage(content="Connect me to an agent")]},
    config=config,
)

snap_before = graph.get_state(config)
paused = bool(snap_before.tasks)
ok3_pause = check("graph paused after explicit request", paused)

# Step 2: resume with agent message
agent_reply = "Hi! I'm Sarah from the support team. How can I help you today?"
result_resumed = graph.invoke(
    Command(resume={"agent_message": agent_reply, "resolved": False}),
    config=config,
)

status_after  = result_resumed.get("status", "bot")
messages_after = result_resumed.get("messages", [])
agent_in_history = any(
    agent_reply[:40] in m.content
    for m in messages_after
    if hasattr(m, "content")
)

ok3_resume = all([
    check("status stays awaiting_human after resume", status_after == "awaiting_human"),
    check("agent reply appears in message history",   agent_in_history),
])

ok3 = ok3_pause and ok3_resume
print(f"   → {'PASS' if ok3 else 'FAIL'}")
if ok3: passed += 1
else:   failed += 1


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — holding_reply while awaiting_human
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n── holding_reply ─────────────────────────────────────────")

# Continue on the resumed thread from scenario 3 — it is now awaiting_human
# (resumed but not resolved). Send a new user message.
result_hold = graph.invoke(
    {"messages": [HumanMessage(content="Are you still there?")]},
    config=config,
)

hold_msg = result_hold["messages"][-1].content
ok4 = all([
    check("status still awaiting_human",    result_hold.get("status") == "awaiting_human"),
    check("holding_reply message returned", "agent" in hold_msg.lower() or "shortly" in hold_msg.lower()),
])

print(f"   msg: {hold_msg[:100]}...")
print(f"   → {'PASS' if ok4 else 'FAIL'}")
if ok4: passed += 1
else:   failed += 1


# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print(f"Result: {passed}/4 scenarios passed,  {failed} failed")
print("=" * 65)

if failed:
    sys.exit(1)
