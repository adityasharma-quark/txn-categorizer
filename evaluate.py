"""
evaluate.py — Simple evaluation script.

Metrics:
  - Top-1 category match (exact match against expected category)
  - Confidence score distribution
  - Per-sample pass/fail summary

Usage:
  python evaluate.py

Requires LLM_API_KEY to be set in .env or environment.
"""
from __future__ import annotations

import os
import sys
import json
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

django.setup()

from categorizer.schemas import CategorizationRequest
from categorizer.services.categorization_service import categorize_transaction
from sample_data.mock_data import SAMPLE_REQUESTS


def run_evaluation():
    print("=" * 60)
    print("Transaction Categorization — Evaluation Run")
    print("=" * 60)

    results = []
    top1_hits = 0

    for i, sample in enumerate(SAMPLE_REQUESTS, 1):
        expected_cat = sample.get("_expected_category", "")
        expected_conf_min = sample.get("_expected_confidence_min", 0.0)
        description = sample.get("_description", "")

        # Strip evaluation-only keys before building the request
        request_data = {k: v for k, v in sample.items() if not k.startswith("_")}

        print(f"\n[{i}/{len(SAMPLE_REQUESTS)}] {description}")
        print(f"  Input       : {request_data['transaction']['description']}")
        print(f"  Expected    : {expected_cat}")

        try:
            req = CategorizationRequest(**request_data)
            resp = categorize_transaction(req)

            top1_match = resp.suggested_category == expected_cat
            conf_ok = resp.confidence_score >= expected_conf_min

            if top1_match:
                top1_hits += 1

            status_icon = "✓" if top1_match else "✗"
            conf_icon = "✓" if conf_ok else "✗"

            print(f"  Got         : {resp.suggested_category}  [{status_icon} Top-1]")
            print(f"  Confidence  : {resp.confidence_score:.2f} ({resp.confidence_label})  [{conf_icon} >= {expected_conf_min}]")
            print(f"  Reasoning   : {resp.reasoning[:120]}")

            results.append({
                "sample": i,
                "description": request_data["transaction"]["description"],
                "expected": expected_cat,
                "predicted": resp.suggested_category,
                "top1_match": top1_match,
                "confidence": resp.confidence_score,
                "confidence_label": resp.confidence_label,
                "confidence_ok": conf_ok,
            })

        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({
                "sample": i,
                "expected": expected_cat,
                "predicted": None,
                "top1_match": False,
                "error": str(exc),
            })

    # ── Summary ──────────────────────────────────────────────────────────────
    total = len(SAMPLE_REQUESTS)
    top1_accuracy = top1_hits / total * 100

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  Samples evaluated : {total}")
    print(f"  Top-1 accuracy    : {top1_hits}/{total}  ({top1_accuracy:.0f}%)")

    confidences = [r["confidence"] for r in results if "confidence" in r]
    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        print(f"  Avg confidence    : {avg_conf:.2f}")
        print(f"  Min confidence    : {min(confidences):.2f}")
        print(f"  Max confidence    : {max(confidences):.2f}")

    # Write JSON results
    out_path = "evaluation_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Full results saved to: {out_path}")
    print("=" * 60)

    return top1_accuracy


if __name__ == "__main__":
    accuracy = run_evaluation()
    sys.exit(0 if accuracy >= 60 else 1)
