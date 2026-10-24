"""Phase 2 tests — confidence router, streak counter, escalation.

Tests three scenarios from conversations.json:
  1. happy_path      — 3 in-scope questions, streak stays 0, no escalation
  2. slow_failure    — 3 out-of-scope questions, streak → 1 → 2 → 3 → escalate
  3. streak_reset    — miss, miss, hit, miss → streak → 1 → 2 → 0 → 1, no escalation

Run from the project root:
    python scripts/test_phase2.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage
from backend import graph

SCENARIOS = [
    {
        "id": "happy_path",
        "desc": "3 in-scope questions — streak stays 0, status stays bot",
        "turns": [
            "How much is the Pro plan per month?",
            "How do I enable 2FA?",
            "What are your support hours?",
        ],
        "expected_streaks": [0, 0, 0],
        "expected_status":  "bot",
    },
    {
        "id": "slow_failure",
        "desc": "3 out-of-scope questions — streak → 1,2,3 → status awaiting_human",
        "turns": [
            "Do you offer a lifetime deal?",
            "Do you offer discounts for nonprofits?",
            "Can you sign a HIPAA BAA?",
        ],
        "expected_streaks": [1, 2, 3],
        "expected_status":  "awaiting_human",
    },
    {
        "id": "streak_reset",
        "desc": "miss, miss, hit, miss → streak → 1,2,0,1 — no escalation",
        "turns": [
            "Do you offer a lifetime deal?",
            "What's the weather like in Berlin today?",
            "How long is the password reset link valid?",
            "Do you offer discounts for nonprofits?",
        ],
        "expected_streaks": [1, 2, 0, 1],
        "expected_status":  "bot",
    },
]

print("=" * 65)
print("Phase 2 Tests — routing, streak counter, escalation")
print("=" * 65)

passed = 0
failed = 0

for scenario in SCENARIOS:
    print(f"\n── {scenario['id']} ──────────────────────────────")
    print(f"   {scenario['desc']}")

    thread_id = f"test-p2-{scenario['id']}-{int(time.time())}"
    config    = {"configurable": {"thread_id": thread_id}}

    scenario_ok = True

    for i, (turn, expected_streak) in enumerate(
        zip(scenario["turns"], scenario["expected_streaks"])
    ):
        result = graph.invoke(
            {"messages": [HumanMessage(content=turn)]},
            config=config,
        )

        actual_streak = result.get("low_conf_streak", 0)
        actual_status = result.get("status", "bot")
        score         = result.get("top_score", 0.0)
        last_msg      = result["messages"][-1].content[:100].replace("\n", " ")

        streak_ok = actual_streak == expected_streak
        if not streak_ok:
            scenario_ok = False

        mark = "✓" if streak_ok else "✗"
        print(f"\n   turn {i+1}: {mark}  streak={actual_streak} "
              f"(expected {expected_streak})  score={score:.3f}  status={actual_status}")
        print(f"   Q: {turn}")
        print(f"   A: {last_msg}...")

    # Check final status
    final_status_ok = actual_status == scenario["expected_status"]
    if not final_status_ok:
        scenario_ok = False

    status_mark = "✓" if final_status_ok else "✗"
    print(f"\n   final status: {status_mark}  "
          f"got='{actual_status}'  expected='{scenario['expected_status']}'")

    result_label = "PASS" if scenario_ok else "FAIL"
    print(f"   → {result_label}")

    if scenario_ok:
        passed += 1
    else:
        failed += 1

print("\n" + "=" * 65)
print(f"Result: {passed}/{len(SCENARIOS)} scenarios passed,  {failed} failed")
print("=" * 65)

if failed:
    sys.exit(1)
