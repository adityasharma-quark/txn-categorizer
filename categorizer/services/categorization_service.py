"""
categorization_service.py — Orchestrates the full categorization pipeline.

Pipeline (agentic path — Anthropic with tools):
  1. Build structured prompt           (context_builder)
  2. Invoke LLM with tool access       (llm_client — agentic loop)
     └─ Model calls tools as needed:
        • lookup_bank_rules
        • lookup_similar_transactions
        • get_chart_of_accounts
     └─ Loop exits when stop_reason == "end_turn"
  3. Parse & validate output           (response_formatter)

Pipeline (standard path — OpenAI / HuggingFace):
  1. Build structured prompt           (context_builder)
  2. Single LLM call                   (llm_client)
  3. Parse & validate output           (response_formatter)
"""
from __future__ import annotations

import logging

from categorizer.schemas import CategorizationRequest, CategorizationResponse
from categorizer.services.context_builder import build_prompts
from categorizer.services.llm_client import LLMClientFactory
from categorizer.services.response_formatter import parse_and_format
from categorizer.services.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)


def categorize_transaction(request: CategorizationRequest) -> CategorizationResponse:
    """
    Entry point for the categorization agent.
    Raises ValueError on unrecoverable LLM/parse errors.
    """
    logger.info(
        "Categorization started | company=%s industry=%s",
        request.company_id,
        request.industry,
    )

    client = LLMClientFactory.get()

    if client.supports_tools():
        # Agentic path: model can call tools before committing to a category.
        system_prompt, user_prompt = build_prompts(request, agentic=True)
        raw_response = client.complete_agentic(
            system_prompt, user_prompt, TOOL_DEFINITIONS, execute_tool
        )
        tools_used = list(client.last_tools_used)
    else:
        # Standard single-turn path for non-Anthropic providers.
        system_prompt, user_prompt = build_prompts(request, agentic=False)
        raw_response = client.complete(system_prompt, user_prompt)
        tools_used = []

    response = parse_and_format(raw_response, request, client, tools_used=tools_used)

    logger.info(
        "Categorization complete | category=%s confidence=%.2f label=%s tools=%s",
        response.suggested_category,
        response.confidence_score,
        response.confidence_label,
        tools_used or "none",
    )
    return response
