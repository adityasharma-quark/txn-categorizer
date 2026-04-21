"""
context_builder.py — Constructs the structured prompt sent to the LLM.

Responsibilities:
  - Format historical examples as few-shot context
  - Embed the Chart of Accounts as the constrained label set
  - Inject industry context
  - Produce a deterministic system prompt + user prompt pair
"""
from __future__ import annotations

from typing import List

from categorizer.schemas import CategorizationRequest, HistoricalTransaction

_SYSTEM_TEMPLATE = """\
You are a financial transaction categorization assistant.

Your job is to classify a transaction into exactly ONE category from the \
provided Chart of Accounts.

Rules:
1. You MUST pick a category that exists in the Chart of Accounts — no exceptions.
2. Return ONLY valid JSON — no markdown fences, no prose outside the JSON block.
3. Confidence score must be a float between 0.0 and 1.0.
4. Provide up to 2 alternative categories with their own confidence scores.
5. Keep reasoning concise (1–2 sentences).

Response JSON schema (strict):
{{
  "suggested_category": "<exact string from Chart of Accounts>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<brief explanation>",
  "alternatives": [
    {{"category": "<CoA string>", "confidence": <float>, "reasoning": "<brief>"}},
    {{"category": "<CoA string>", "confidence": <float>, "reasoning": "<brief>"}}
  ]
}}
"""

_AGENTIC_SYSTEM_TEMPLATE = """\
You are a financial transaction categorization agent with access to tools.

Your goal is to classify a transaction into exactly ONE category from the \
provided Chart of Accounts with the highest possible accuracy.

Decision strategy — follow this order:
1. Call `lookup_bank_rules` first. A matching rule is an explicit bookkeeper \
preference and should be treated as ground truth — assign HIGH confidence (≥ 0.90).
2. If no bank rule matches, call `lookup_similar_transactions` to find how \
this company categorized similar past transactions.
3. Optionally call `get_chart_of_accounts` if you need to understand the \
company's GL structure in more detail.
4. After gathering context, reason over what you found and produce your final answer.

Hard constraints:
- You MUST pick a category that exists in the Chart of Accounts supplied in the \
request — no exceptions, even if the tools suggest a different account name.
- Return ONLY valid JSON as your final message — no markdown fences, no prose.
- Confidence score must be a float between 0.0 and 1.0.
- Provide up to 2 alternative categories.
- Keep reasoning concise (1–2 sentences), referencing any evidence from tools.

Response JSON schema (strict):
{{
  "suggested_category": "<exact string from Chart of Accounts>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<brief explanation referencing any tool evidence>",
  "alternatives": [
    {{"category": "<CoA string>", "confidence": <float>, "reasoning": "<brief>"}},
    {{"category": "<CoA string>", "confidence": <float>, "reasoning": "<brief>"}}
  ]
}}
"""

_USER_TEMPLATE = """\
## Company Context
- Company ID : {company_id}
- Industry   : {industry}

## Chart of Accounts (valid categories)
{chart_of_accounts}

## Historical Examples (few-shot)
{historical_block}

## Transaction to Categorize
- Description : {description}
- Payee/Vendor: {payee}
- Amount      : {amount}

Classify this transaction. Return ONLY the JSON object.
"""

_USER_TEMPLATE_ENRICHED = """\
## Company Context
- Company ID : {company_id}
- Industry   : {industry}

## Chart of Accounts (valid categories)
{chart_of_accounts}

## Historical Examples (few-shot)
{historical_block}

## Heuristic Context (retrieved from company data — use as strong evidence)
{enrichment_context}

## Transaction to Categorize
- Description : {description}
- Payee/Vendor: {payee}
- Amount      : {amount}

Classify this transaction. Return ONLY the JSON object.
"""


def build_prompts(
    request: CategorizationRequest,
    agentic: bool = False,
    enrichment_context: str = "",
) -> tuple[str, str]:
    """
    Returns (system_prompt, user_prompt).
    - agentic=True      → tool-aware system prompt (Tier 3)
    - enrichment_context → pre-fetched heuristics injected into user prompt (Tier 2)
    """
    system_prompt = _AGENTIC_SYSTEM_TEMPLATE if agentic else _SYSTEM_TEMPLATE

    chart_block = "\n".join(
        f"  - {account}" for account in request.chart_of_accounts
    )
    historical_block = _format_history(request.historical_transactions)

    common = dict(
        company_id=request.company_id,
        industry=request.industry,
        chart_of_accounts=chart_block,
        historical_block=historical_block,
        description=request.transaction.description,
        payee=request.transaction.payee or "N/A",
        amount=(
            f"{request.transaction.currency or ''} {request.transaction.amount}"
            if request.transaction.amount is not None
            else "N/A"
        ),
    )

    if enrichment_context:
        user_prompt = _USER_TEMPLATE_ENRICHED.format(
            **common, enrichment_context=enrichment_context
        )
    else:
        user_prompt = _USER_TEMPLATE.format(**common)

    return system_prompt, user_prompt


def _format_history(transactions: List[HistoricalTransaction]) -> str:
    if not transactions:
        return "  (no historical data provided)"

    lines = []
    for i, txn in enumerate(transactions, 1):
        payee_part = f" | Payee: {txn.payee}" if txn.payee else ""
        amount_part = f" | Amount: {txn.amount}" if txn.amount is not None else ""
        lines.append(
            f"  {i}. Description: {txn.description}{payee_part}{amount_part}"
            f"\n     → Category: {txn.category}"
        )
    return "\n".join(lines)
