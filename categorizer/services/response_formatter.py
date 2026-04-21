"""
response_formatter.py — Parses raw LLM output into a typed CategorizationResponse.

Responsibilities:
  - Extract JSON from raw LLM text (handles fences, prose wrapping)
  - Validate that suggested_category is in the Chart of Accounts
  - Clamp confidence scores to [0.0, 1.0]
  - Build the final CategorizationResponse object
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from categorizer.schemas import (
    CategorizationResponse,
    CategorySuggestion,
    CategorizationRequest,
)
from categorizer.services.llm_client import extract_json_block, BaseLLMClient

logger = logging.getLogger(__name__)


def parse_and_format(
    raw_response: str,
    request: CategorizationRequest,
    client: BaseLLMClient,
    tools_used: List[str] | None = None,
    tier: int = 2,
) -> CategorizationResponse:
    """
    Parses raw LLM text → validates → returns CategorizationResponse.
    Raises ValueError if the output cannot be parsed or the category is invalid.
    """
    data: Dict[str, Any] = extract_json_block(raw_response)

    suggested = _validate_category(
        data.get("suggested_category", ""), request.chart_of_accounts
    )
    confidence = _clamp(float(data.get("confidence", 0.5)))
    reasoning = str(data.get("reasoning", "")).strip() or "No reasoning provided."

    alternatives = _parse_alternatives(
        data.get("alternatives", []), request.chart_of_accounts, suggested
    )

    return CategorizationResponse(
        transaction_description=request.transaction.description,
        payee=request.transaction.payee,
        suggested_category=suggested,
        confidence_score=confidence,
        confidence_label=CategorizationResponse.confidence_label_from_score(confidence),
        alternative_categories=alternatives,
        reasoning=reasoning,
        model_used=client.model_name,
        provider=client.provider_name,
        tools_used=list(dict.fromkeys(tools_used or [])),  # deduplicate, preserve order
        categorization_tier=tier,
    )


# ──────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────

def _validate_category(raw: str, chart_of_accounts: List[str]) -> str:
    """Case-insensitive match against Chart of Accounts; raises if not found."""
    normalised = {c.lower().strip(): c for c in chart_of_accounts}
    key = raw.lower().strip()
    if key not in normalised:
        logger.warning(
            "LLM returned category not in CoA: %r — attempting fuzzy fallback", raw
        )
        # Fuzzy fallback: pick the CoA entry that shares the most words
        best = _fuzzy_match(key, normalised)
        if best:
            logger.info("Fuzzy fallback resolved to: %r", best)
            return best
        raise ValueError(
            f"LLM suggested category '{raw}' is not in the Chart of Accounts. "
            f"Valid options: {chart_of_accounts}"
        )
    return normalised[key]


def _fuzzy_match(target: str, normalised: Dict[str, str]) -> str | None:
    target_words = set(target.split())
    scores = {
        coa_orig: len(target_words & set(coa_lower.split()))
        for coa_lower, coa_orig in normalised.items()
    }
    best_match, best_score = max(scores.items(), key=lambda x: x[1])
    return best_match if best_score > 0 else None


def _parse_alternatives(
    raw_alts: List[Any],
    chart_of_accounts: List[str],
    primary: str,
) -> List[CategorySuggestion]:
    results: List[CategorySuggestion] = []
    for alt in raw_alts[:2]:
        try:
            cat = _validate_category(str(alt.get("category", "")), chart_of_accounts)
            if cat == primary:
                continue  # skip if same as primary
            results.append(
                CategorySuggestion(
                    category=cat,
                    confidence=_clamp(float(alt.get("confidence", 0.3))),
                    reasoning=str(alt.get("reasoning", "")).strip(),
                )
            )
        except (ValueError, TypeError, AttributeError):
            pass  # silently drop malformed alternatives
    return results


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
