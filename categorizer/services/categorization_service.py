"""
categorization_service.py — Orchestrates the full categorization pipeline.

Pipeline:
  1. Build structured prompt  (context_builder)
  2. Invoke LLM               (llm_client)
  3. Parse & validate output  (response_formatter)
"""
from __future__ import annotations

import logging

from categorizer.schemas import CategorizationRequest, CategorizationResponse
from categorizer.services.context_builder import build_prompts
from categorizer.services.llm_client import LLMClientFactory
from categorizer.services.response_formatter import parse_and_format

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

    # Step 1: Build prompt
    system_prompt, user_prompt = build_prompts(request)

    # Step 2: Invoke LLM (provider resolved from settings)
    client = LLMClientFactory.get()
    raw_response = client.complete(system_prompt, user_prompt)

    # Step 3: Parse, validate, format
    response = parse_and_format(raw_response, request, client)

    logger.info(
        "Categorization complete | category=%s confidence=%.2f label=%s",
        response.suggested_category,
        response.confidence_score,
        response.confidence_label,
    )
    return response
