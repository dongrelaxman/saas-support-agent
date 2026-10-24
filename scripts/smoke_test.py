"""Phase 1 smoke test — verify retrieve + answer works end-to-end.

Checks:
  1. top_score >= 0.50 for all 5 in-scope questions
  2. Each answer contains at least one [Source: ...] citation
  3. Key facts appear in the answers

Run from the project root:
    python scripts/smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage
from backend import graph

QUESTIONS = [
    {
        "q": "What is the API rate limit on the Pro plan?",
        "expect": "600",
    },
    {
        "q": "Can I get a refund on an annual plan?",
        "expect": "14",
    },
    {
        "q": "How do I enable two-factor authentication?",
        "expect": "Settings",
    },
    {
        "q": "What iOS version does the mobile app require?",
        "expect": "15",
    },
    {
        "q": "What happens if my payment fails?",
        "expect": "retry",
    },
]

print("=" * 65)
print("Phase 1 Smoke Test")
print("=" * 65)

passed = 0
failed = 0

for item in QUESTIONS:
    config = {"configurable": {"thread_id": f"smoke-{item['q'][:20]}"}}
    result = graph.invoke(
        {"messages": [HumanMessage(content=item["q"])]},
        config=config,
    )

    answer  = result["messages"][-1].content
    score   = result["top_score"]
    has_citation = "[Source:" in answer
    has_fact     = item["expect"].lower() in answer.lower()

    status = "PASS" if (score >= 0.50 and has_citation and has_fact) else "FAIL"
    if status == "PASS":
        passed += 1
    else:
        failed += 1

    print(f"\n[{status}] {item['q']}")
    print(f"  score     : {score:.4f}  (threshold 0.50)")
    print(f"  citation  : {'yes' if has_citation else 'MISSING'}")
    print(f"  fact '{item['expect']}': {'found' if has_fact else 'MISSING'}")
    print(f"  answer    : {answer[:180].strip()} ...")

print("\n" + "=" * 65)
print(f"Result: {passed}/{len(QUESTIONS)} passed,  {failed} failed")
print("=" * 65)

if failed:
    sys.exit(1)
