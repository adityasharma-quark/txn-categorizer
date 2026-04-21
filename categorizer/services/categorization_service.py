"""
categorization_service.py — Tiered categorization pipeline.

Three tiers, tried in order:

  Tier 1 — Rule Engine (zero LLM cost)
    Check company bank rules for an exact keyword match.
    If a rule matches AND word-overlap maps it to a CoA item → return immediately.
    Typical confidence: 0.92–0.97. Fast, deterministic, auditable.

  Tier 2 — Enriched Single LLM Call
    Pre-fetch bank rule matches + similar historical transactions.
    Inject them as context into a single LLM prompt.
    If confidence ≥ 0.5 → return.

  Tier 3 — Agentic Escalation  (only when Tier 2 confidence < 0.5)
    Give the LLM tool access to explore further on its own.
    The agentic loop runs until stop_reason == "end_turn".
    Only available when LLM_PROVIDER=anthropic.
"""
from __future__ import annotations

import logging
from typing import Optional

from categorizer.schemas import (
    CategorizationRequest,
    CategorizationResponse,
)
from categorizer.services.context_builder import build_prompts
from categorizer.services.llm_client import BaseLLMClient, LLMClientFactory
from categorizer.services.response_formatter import parse_and_format
from categorizer.services.tools import (
    TOOL_DEFINITIONS,
    build_enrichment_context,
    execute_tool,
    get_matching_rules,
    map_rule_to_coa,
)

logger = logging.getLogger(__name__)

_LOW_CONFIDENCE_THRESHOLD = 0.5


def categorize_transaction(request: CategorizationRequest) -> CategorizationResponse:
    """
    Entry point. Tries tiers in order; returns as soon as a tier succeeds.
    Raises ValueError on unrecoverable LLM/parse errors.
    """
    logger.info(
        "Categorization started | company=%s industry=%s",
        request.company_id,
        request.industry,
    )

    client = LLMClientFactory.get()

    # ── TIER 1: Deterministic rule engine ─────────────────────────────────────
    tier1 = _try_tier1(request, client)
    if tier1 is not None:
        logger.info(
            "Tier 1 hit | category=%s confidence=%.2f",
            tier1.suggested_category,
            tier1.confidence_score,
        )
        return tier1

    # ── TIER 2: Single enriched LLM call ──────────────────────────────────────
    enrichment = build_enrichment_context(
        request.company_id,
        request.transaction.description,
        request.transaction.payee or "",
        request.chart_of_accounts,
    )
    system_prompt, user_prompt = build_prompts(
        request, agentic=False, enrichment_context=enrichment
    )
    raw = client.complete(system_prompt, user_prompt)
    tier2 = parse_and_format(raw, request, client, tier=2)

    logger.info(
        "Tier 2 result | category=%s confidence=%.2f label=%s",
        tier2.suggested_category,
        tier2.confidence_score,
        tier2.confidence_label,
    )

    if tier2.confidence_score >= _LOW_CONFIDENCE_THRESHOLD:
        return tier2

    # ── TIER 3: Agentic escalation ─────────────────────────────────────────────
    if not client.supports_tools():
        logger.info(
            "Tier 3 skipped | provider '%s' does not support tools — returning Tier 2 result",
            client.provider_name,
        )
        return tier2

    logger.info(
        "Escalating to Tier 3 | Tier 2 confidence too low (%.2f < %.1f)",
        tier2.confidence_score,
        _LOW_CONFIDENCE_THRESHOLD,
    )
    system_agentic, user_agentic = build_prompts(
        request, agentic=True, enrichment_context=enrichment
    )
    raw_agentic = client.complete_agentic(
        system_agentic, user_agentic, TOOL_DEFINITIONS, execute_tool
    )
    tier3 = parse_and_format(
        raw_agentic,
        request,
        client,
        tools_used=list(client.last_tools_used),
        tier=3,
    )

    logger.info(
        "Tier 3 result | category=%s confidence=%.2f label=%s tools=%s",
        tier3.suggested_category,
        tier3.confidence_score,
        tier3.confidence_label,
        client.last_tools_used or "none",
    )
    return tier3


# ─── Tier 1 helper ────────────────────────────────────────────────────────────

def _try_tier1(
    request: CategorizationRequest,
    client: BaseLLMClient,
) -> Optional[CategorizationResponse]:
    """
    Checks bank rules deterministically. Returns a CategorizationResponse if
    a rule matches the description AND can be word-overlap-mapped to a CoA item.
    Returns None to signal fall-through to Tier 2.
    """
    matching_rules = get_matching_rules(
        request.company_id, request.transaction.description
    )
    if not matching_rules:
        return None

    for rule in matching_rules:
        result = map_rule_to_coa(rule, request.chart_of_accounts)
        if result is None:
            continue
        category, confidence = result
        return CategorizationResponse(
            transaction_description=request.transaction.description,
            payee=request.transaction.payee,
            suggested_category=category,
            confidence_score=confidence,
            confidence_label=CategorizationResponse.confidence_label_from_score(confidence),
            alternative_categories=[],
            reasoning=(
                f'Bank rule "{rule["title"]}" matched keyword '
                f'"{rule["matched_keyword"]}" in the transaction description.'
            ),
            model_used="rule-engine",
            provider="heuristics",
            tools_used=[],
            categorization_tier=1,
        )

    # Rules matched but none mapped to a CoA item — fall through
    logger.debug(
        "Tier 1 miss | %d rule(s) matched but none mapped to CoA", len(matching_rules)
    )
    return None
