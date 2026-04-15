"""
schemas.py — Deterministic JSON contract for all API inputs and outputs.
All validation lives here; views stay thin.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ──────────────────────────────────────────────
# Inbound schemas
# ──────────────────────────────────────────────

class Transaction(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    payee: Optional[str] = Field(None, max_length=200)
    amount: Optional[float] = None
    currency: Optional[str] = Field(None, max_length=3)
    date: Optional[str] = None          # ISO-8601 string; not used in logic, kept for context


class HistoricalTransaction(BaseModel):
    description: str
    payee: Optional[str] = None
    amount: Optional[float] = None
    category: str                        # ground-truth label from historical record


class CategorizationRequest(BaseModel):
    transaction: Transaction
    company_id: str = Field(..., min_length=1, max_length=100)
    industry: str = Field(..., min_length=1, max_length=100)
    chart_of_accounts: List[str] = Field(..., min_length=1)
    historical_transactions: List[HistoricalTransaction] = Field(default_factory=list)

    @field_validator("chart_of_accounts")
    @classmethod
    def accounts_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("chart_of_accounts must contain at least one account.")
        return [a.strip() for a in v if a.strip()]

    @field_validator("historical_transactions")
    @classmethod
    def cap_history(cls, v: List[HistoricalTransaction]) -> List[HistoricalTransaction]:
        """Silently truncate to last 20 to keep prompt size predictable."""
        return v[-20:]


# ──────────────────────────────────────────────
# Outbound schemas
# ──────────────────────────────────────────────

class CategorySuggestion(BaseModel):
    category: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str


class CategorizationResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    transaction_description: str
    payee: Optional[str]
    suggested_category: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_label: str               # HIGH / MEDIUM / LOW
    alternative_categories: List[CategorySuggestion]
    reasoning: str
    model_used: str
    provider: str

    @classmethod
    def confidence_label_from_score(cls, score: float) -> str:
        if score >= 0.80:
            return "HIGH"
        if score >= 0.50:
            return "MEDIUM"
        return "LOW"


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
