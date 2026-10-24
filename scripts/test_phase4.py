"""Phase 4 tests — rolling summary memory.

Tests three scenarios:

  1. no_trim        — fewer messages than the window; summary stays empty
  2. trim_fires     — exceed the window; oldest messages replaced by SystemMessage summary
  3. summary_builds — second trim incorporates the previous summary

The test temporarily lowers memory.message_window to 6 and memory.summary_keep to 4
so we need only 4 turns to trigger a trim (4 turns × 2 messages = 8 > 6).
The monkeypatch touches only the backend.memory module-level globals and is
reverted after each scenario via a context manager.

Run from the project root:
    python scripts/test_phase4.py
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import backend.memory as _mem_module
from langchain_core.messages import HumanMessage, SystemMessage
from backend import graph

RUN_ID = int(time.time())

# ── Patch helper ──────────────────────────────────────────────────────────────

@contextmanager
def small_window(window: int = 6, keep: int = 4):
    """Temporarily lower the memory window so tests don't need 11 real turns."""
    old_w, old_k = _mem_module._window, _mem_module._keep
    _mem_module._window, _mem_module._keep = window, keep
    try:
        yield
    finally:
        _mem_module._window, _mem_module._keep = old_w, old_k


# ── Shared questions ──────────────────────────────────────────────────────────

QUESTIONS = [
    "How much is the Pro plan per month?",
    "How do I enable 2FA?",
    "What are your support hours?",
    "How do I reset my password?",
    "What payment methods do you accept?",
    "How do I export my data?",
]

print("=" * 65)
print("Phase 4 Tests — rolling summary memory")
print("=" * 65)

passed = 0
failed = 0


def check(label: str, condition: bool) -> bool:
    mark = "✓" if condition else "✗"
    print(f"   {mark}  {label}")
    return condition


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — window not exceeded → no summary, message count unchanged
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n── no_trim ───────────────────────────────────────────────")

with small_window(window=6, keep=4):
    thread_id = f"test-p4-notrim-{RUN_ID}"
    config    = {"configurable": {"thread_id": thread_id}}

    # Send 3 turns → 6 messages (equals window, not > window)
    for q in QUESTIONS[:3]:
        graph.invoke({"messages": [HumanMessage(content=q)]}, config=config)

    state = graph.get_state(config)
    summary  = state.values.get("summary", "")
    n_msgs   = len(state.values.get("messages", []))

    ok1 = all([
        check("summary is empty (no trim fired)",  not summary),
        check("message count == 6",                n_msgs == 6),
    ])

print(f"   summary={repr(summary[:60])}")
print(f"   message_count={n_msgs}")
print(f"   → {'PASS' if ok1 else 'FAIL'}")
if ok1: passed += 1
else:   failed += 1


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — exceed window → oldest messages trimmed, summary set
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n── trim_fires ────────────────────────────────────────────")

with small_window(window=6, keep=4):
    thread_id = f"test-p4-trim-{RUN_ID}"
    config    = {"configurable": {"thread_id": thread_id}}

    # Send 4 turns → 8 messages (8 > 6, trim fires on turn 4)
    for q in QUESTIONS[:4]:
        graph.invoke({"messages": [HumanMessage(content=q)]}, config=config)

    state    = graph.get_state(config)
    summary  = state.values.get("summary", "")
    n_msgs   = len(state.values.get("messages", []))
    msgs     = state.values.get("messages", [])
    has_sys  = any(isinstance(m, SystemMessage) for m in msgs)

    # After trim: 8 - 4 (keep) + 1 (summary SystemMessage) = 5
    ok2 = all([
        check("summary is not empty",           bool(summary)),
        check("message count reduced (< 8)",    n_msgs < 8),
        check("SystemMessage summary present",  has_sys),
    ])

print(f"   summary={repr(summary[:80])}")
print(f"   message_count={n_msgs}  (was 8 before trim)")
print(f"   → {'PASS' if ok2 else 'FAIL'}")
if ok2: passed += 1
else:   failed += 1


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — second trim incorporates first summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n── summary_builds ────────────────────────────────────────")

with small_window(window=6, keep=4):
    thread_id = f"test-p4-build-{RUN_ID}"
    config    = {"configurable": {"thread_id": thread_id}}

    # First trim on turn 4 (messages: 8 → 5)
    for q in QUESTIONS[:4]:
        graph.invoke({"messages": [HumanMessage(content=q)]}, config=config)

    summary_after_first = graph.get_state(config).values.get("summary", "")

    # Add more turns to trigger a second trim
    # After first trim: 5 messages. Need 2 more turns (4 more messages) → 9 > 6 → second trim
    for q in QUESTIONS[4:6]:
        graph.invoke({"messages": [HumanMessage(content=q)]}, config=config)

    state2   = graph.get_state(config)
    summary2 = state2.values.get("summary", "")
    n_msgs2  = len(state2.values.get("messages", []))

    ok3 = all([
        check("first summary was set",               bool(summary_after_first)),
        check("second summary is set",               bool(summary2)),
        check("second summary differs from first",   summary2 != summary_after_first),
        check("message count still bounded",         n_msgs2 < 10),
    ])

print(f"   summary_1={repr(summary_after_first[:60])}")
print(f"   summary_2={repr(summary2[:60])}")
print(f"   message_count={n_msgs2}")
print(f"   → {'PASS' if ok3 else 'FAIL'}")
if ok3: passed += 1
else:   failed += 1


# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print(f"Result: {passed}/3 scenarios passed,  {failed} failed")
print("=" * 65)

if failed:
    sys.exit(1)
