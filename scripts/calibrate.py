"""Calibrate the confidence threshold using the 50-question eval set.

For each question in eval_set.csv, we query Weaviate and record top_score.
We then sweep thresholds from 0.50 to 0.90 and find the value that
maximises F1 between in_scope (should pass) and out_of_scope (should fail).

Only in_scope and out_of_scope questions are used.
human_request questions bypass retrieval entirely (handled by intent_check).

Run after ingestion:
    python scripts/calibrate.py

Updates config.yaml with the best threshold found.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import yaml
import weaviate
from langchain_openai import OpenAIEmbeddings
from weaviate.classes.init import Auth
from weaviate.classes.query import Filter, MetadataQuery

# ── Config and paths ──────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
cfg       = yaml.safe_load((ROOT / "config.yaml").read_text())
EVAL_PATH = ROOT / "eval" / "eval_set.csv"
COLLECTION = cfg["weaviate"]["collection"]

# ── Load eval questions (skip human_request — not a retrieval decision) ───────
rows = [
    r for r in csv.DictReader(EVAL_PATH.open())
    if r["category"] in ("in_scope", "out_of_scope")
]
print(f"Loaded {len(rows)} questions ({sum(1 for r in rows if r['category']=='in_scope')} in_scope, "
      f"{sum(1 for r in rows if r['category']=='out_of_scope')} out_of_scope)")

# ── Connect ────────────────────────────────────────────────────────────────────
client = weaviate.connect_to_weaviate_cloud(
    cluster_url=os.environ["WEAVIATE_URL"],
    auth_credentials=Auth.api_key(os.environ["WEAVIATE_API_KEY"]),
)
collection = client.collections.get(COLLECTION)
embeddings = OpenAIEmbeddings(model=cfg["models"]["embeddings"])

# ── Score every question ───────────────────────────────────────────────────────
print("\nQuerying Weaviate for scores...")
scored: list[dict] = []

for i, row in enumerate(rows, 1):
    vec      = embeddings.embed_query(row["question"])
    response = collection.query.near_vector(
        near_vector=vec,
        limit=1,
        filters=Filter.by_property("archived").equal(False),
        return_metadata=MetadataQuery(certainty=True),
    )
    score = (
        response.objects[0].metadata.certainty
        if response.objects and response.objects[0].metadata.certainty is not None
        else 0.0
    )
    scored.append({"id": row["id"], "category": row["category"], "score": score,
                   "question": row["question"][:55]})
    print(f"  [{i:02d}/{len(rows)}] {row['id']}  {score:.4f}  {row['category']}")

client.close()

# ── Separate by category ───────────────────────────────────────────────────────
in_scope    = [r for r in scored if r["category"] == "in_scope"]
out_of_scope = [r for r in scored if r["category"] == "out_of_scope"]

# ── Score distribution summary ────────────────────────────────────────────────
in_scores  = [r["score"] for r in in_scope]
out_scores = [r["score"] for r in out_of_scope]

print(f"\nIn-scope  scores  — min: {min(in_scores):.4f}  max: {max(in_scores):.4f}  "
      f"mean: {sum(in_scores)/len(in_scores):.4f}")
print(f"Out-scope scores  — min: {min(out_scores):.4f}  max: {max(out_scores):.4f}  "
      f"mean: {sum(out_scores)/len(out_scores):.4f}")

# ── Sweep thresholds ──────────────────────────────────────────────────────────
print(f"\n{'Threshold':>10} {'Precision':>10} {'Recall':>8} {'F1':>8}  note")
print("-" * 55)

best_t  = cfg["retrieval"]["threshold"]
best_f1 = 0.0
results = []

for t_int in range(50, 91, 5):
    t = t_int / 100

    tp = sum(1 for r in in_scope    if r["score"] >= t)   # in_scope above threshold
    fp = sum(1 for r in out_of_scope if r["score"] >= t)  # out_of_scope above threshold
    fn = len(in_scope) - tp                               # in_scope below threshold

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / len(in_scope) if len(in_scope) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)

    note = ""
    if t == cfg["retrieval"]["threshold"]:
        note = "<-- current config"
    if f1 > best_f1:
        best_f1 = f1
        best_t  = t

    results.append((t, precision, recall, f1))
    print(f"  {t:>6.2f}    {precision:>8.3f}   {recall:>6.3f}  {f1:>6.3f}  {note}")

# Mark the best
print(f"\nBest threshold : {best_t:.2f}  (F1 = {best_f1:.3f})")
print(f"Current config : {cfg['retrieval']['threshold']:.2f}")

# ── Update config.yaml ────────────────────────────────────────────────────────
if best_t != cfg["retrieval"]["threshold"]:
    cfg["retrieval"]["threshold"] = best_t
    (ROOT / "config.yaml").write_text(yaml.dump(cfg, default_flow_style=False))
    print(f"Updated config.yaml  →  threshold = {best_t}")
else:
    print("config.yaml unchanged — current threshold is already optimal.")
