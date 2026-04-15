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


def build_prompts(request: CategorizationRequest) -> tuple[str, str]:
    """
    Returns (system_prompt, user_prompt).
    Separation keeps system instructions stable and user context variable.
    """
    system_prompt = _SYSTEM_TEMPLATE

    chart_block = "\n".join(
        f"  - {account}" for account in request.chart_of_accounts
    )

    historical_block = _format_history(request.historical_transactions)

    user_prompt = _USER_TEMPLATE.format(
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
