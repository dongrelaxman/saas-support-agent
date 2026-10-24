"""Phase 7 — Evaluation suite for the TaskPilot support graph.

Runs:
  • 50 single-turn questions from eval/eval_set.csv
  • 6 multi-turn conversation scenarios from eval/conversations.json

Metrics:
  • Per-question pass/fail
  • Precision / Recall / F1 for the confidence router (in_scope vs out_of_scope)
  • Intent accuracy for human-request questions
  • Conversation scenario accuracy (streak + final status)

Exit codes:
  0  — F1 >= F1_GATE (eval passes, PR can merge)
  1  — F1 <  F1_GATE (eval fails, PR is blocked)

Usage:
    python scripts/eval.py
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import yaml
from langchain_core.messages import HumanMessage

from backend.graph import graph

# ── Config ────────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).parent.parent
cfg       = yaml.safe_load((ROOT / "config.yaml").read_text())
THRESHOLD = cfg["retrieval"]["threshold"]
F1_GATE   = 0.80

RUN_ID = int(time.time())

# ── Load eval data ────────────────────────────────────────────────────────────

eval_rows = list(csv.DictReader(open(ROOT / "eval" / "eval_set.csv", newline="")))
scenarios = json.loads((ROOT / "eval" / "conversations.json").read_text())

# ── Helpers ───────────────────────────────────────────────────────────────────

def _invoke(thread_id: str, question: str) -> dict:
    """Invoke the graph for one turn and return the full state dict."""
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )


def _get_state_values(thread_id: str) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    snap = graph.get_state(config)
    return snap.values


def _actual_behavior(result: dict) -> str:
    """Map graph state to one of the three expected_behavior labels."""
    if result.get("status") == "awaiting_human":
        return "immediate_handoff"
    if result.get("top_score", 0.0) >= THRESHOLD:
        return "answer"
    return "low_confidence_hedge"


def _keywords_present(text: str, keywords: str) -> tuple[bool, list[str]]:
    """Return (all_present, missing_list) for a semicolon-separated keyword string."""
    if not keywords:
        return True, []
    missing = [kw.strip() for kw in keywords.split(";")
               if kw.strip() and kw.strip().lower() not in text.lower()]
    return len(missing) == 0, missing


# ── Header ────────────────────────────────────────────────────────────────────

W = 70
print("=" * W)
print("Phase 7 — TaskPilot Support Agent Evaluation")
print(f"Threshold: {THRESHOLD}  |  F1 gate: {F1_GATE}  |  {datetime.now():%Y-%m-%d %H:%M:%S}")
print("=" * W)

# ── Single-turn questions ─────────────────────────────────────────────────────

print(f"\n── Single-turn questions ({len(eval_rows)}) {'─' * (W - 27)}")

q_results: list[dict] = []

for row in eval_rows:
    qid      = row["id"]
    question = row["question"]
    category = row["category"]
    expected = row["expected_behavior"]
    keywords = row.get("expected_answer_keywords", "")

    thread_id = f"eval-q-{qid}-{RUN_ID}"
    passed    = False
    actual    = "error"
    note      = ""

    try:
        result = _invoke(thread_id, question)

        actual    = _actual_behavior(result)
        top_score = result.get("top_score", 0.0)
        last_msg  = result["messages"][-1].content if result.get("messages") else ""

        behavior_ok = (actual == expected)

        # Secondary: keyword check for in_scope answers
        kw_ok, missing = _keywords_present(last_msg, keywords)
        if not kw_ok:
            note = f"missing keywords: {missing}"

        passed = behavior_ok and kw_ok

        mark      = "✓" if passed else "✗"
        score_str = f"score={top_score:.2f}" if category != "human_request" else "(no-retrieve)"
        note_str  = f"  ← {note}" if note else ""
        print(f"  {mark} [{qid}] {category:<15} "
              f"expected={expected:<24} actual={actual:<24} {score_str}{note_str}")

    except Exception as exc:
        print(f"  ✗ [{qid}] ERROR: {exc}")
        actual = "error"
        passed = False

    q_results.append({
        "id":       qid,
        "category": category,
        "expected": expected,
        "actual":   actual,
        "passed":   passed,
    })

# ── Multi-turn conversation scenarios ────────────────────────────────────────

print(f"\n── Conversation scenarios ({len(scenarios)}) {'─' * (W - 29)}")

conv_results: list[dict] = []

for scenario in scenarios:
    sid              = scenario["id"]
    description      = scenario.get("description", "")
    turns            = scenario["turns"]
    expected_streaks = scenario.get("expected_streak_after_each_turn", [])
    expected_status  = scenario.get("expected_final_status", "bot")
    answer_kws       = scenario.get("expected_answer_keywords", [])
    forbidden_kws    = scenario.get("forbidden_answer_keywords", [])

    thread_id = f"eval-conv-{sid}-{RUN_ID}"
    print(f"\n  [{sid}] {description}")

    scenario_passed = True
    last_result: dict = {}

    for i, turn in enumerate(turns):
        try:
            result      = _invoke(thread_id, turn)
            last_result = result

            streak = result.get("low_conf_streak", 0)
            status = result.get("status", "bot")

            # Check streak expectation for this turn
            if i < len(expected_streaks):
                exp_streak = expected_streaks[i]
                streak_ok  = (streak == exp_streak)
                if not streak_ok:
                    scenario_passed = False
                mark = "✓" if streak_ok else "✗"
                print(f"    {mark} turn {i + 1}: streak={streak} (expected {exp_streak})")

        except Exception as exc:
            print(f"    ✗ turn {i + 1}: ERROR — {exc}")
            scenario_passed = False

    # Final status check (read directly from graph state for accuracy)
    try:
        vals         = _get_state_values(thread_id)
        final_status = vals.get("status", "bot")
    except Exception:
        final_status = last_result.get("status", "bot")

    status_ok = (final_status == expected_status)
    if not status_ok:
        scenario_passed = False
    mark = "✓" if status_ok else "✗"
    print(f"    {mark} final status: {final_status} (expected {expected_status})")

    # Keyword checks (for stale_doc_trap)
    if last_result.get("messages"):
        last_msg = last_result["messages"][-1].content
        for kw in answer_kws:
            if kw.lower() not in last_msg.lower():
                scenario_passed = False
                print(f"    ✗ expected keyword missing in answer: '{kw}'")
        for kw in forbidden_kws:
            if kw.lower() in last_msg.lower():
                scenario_passed = False
                print(f"    ✗ forbidden keyword found in answer: '{kw}'")

    mark = "PASS" if scenario_passed else "FAIL"
    print(f"    → {mark}")

    conv_results.append({"id": sid, "passed": scenario_passed})

# ── F1 (confidence router: in_scope vs out_of_scope) ─────────────────────────

print(f"\n── F1 Score (confidence router) {'─' * (W - 32)}")

router = [r for r in q_results if r["category"] in ("in_scope", "out_of_scope")]

TP = sum(1 for r in router if r["category"] == "in_scope"    and r["actual"] == "answer")
FP = sum(1 for r in router if r["category"] == "out_of_scope" and r["actual"] == "answer")
FN = sum(1 for r in router if r["category"] == "in_scope"    and r["actual"] != "answer")
TN = sum(1 for r in router if r["category"] == "out_of_scope" and r["actual"] != "answer")

precision = TP / (TP + FP) if (TP + FP) > 0 else 0.0
recall    = TP / (TP + FN) if (TP + FN) > 0 else 0.0
f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

print(f"  TP={TP}  FP={FP}  FN={FN}  TN={TN}")
print(f"  Precision : {precision:.3f}")
print(f"  Recall    : {recall:.3f}")
print(f"  F1        : {f1:.3f}")

# ── Intent accuracy ───────────────────────────────────────────────────────────

human_results = [r for r in q_results if r["category"] == "human_request"]
intent_pass   = sum(1 for r in human_results if r["passed"])
intent_total  = len(human_results)

# ── Summary ───────────────────────────────────────────────────────────────────

q_pass   = sum(1 for r in q_results if r["passed"])
q_total  = len(q_results)
c_pass   = sum(1 for r in conv_results if r["passed"])
c_total  = len(conv_results)

print(f"\n{'=' * W}")
print(f"  Single-turn   : {q_pass}/{q_total} passed")
print(f"    ↳ in_scope    : {TP}/{TP + FN} answered confidently")
print(f"    ↳ out_of_scope: {TN}/{TN + FP} correctly hedged")
print(f"    ↳ human_req   : {intent_pass}/{intent_total} correctly routed to handoff")
print(f"  Conversations : {c_pass}/{c_total} passed")
print(f"  F1            : {f1:.3f}  (gate: {F1_GATE})")
print("=" * W)

if f1 >= F1_GATE:
    print(f"\n✓  EVAL PASSED — F1 {f1:.3f} ≥ {F1_GATE}\n")
    sys.exit(0)
else:
    print(f"\n✗  EVAL FAILED — F1 {f1:.3f} < {F1_GATE}\n")
    sys.exit(1)
