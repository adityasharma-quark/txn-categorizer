"""
llm_client.py — Model-agnostic LLM abstraction layer.

Adding a new provider: subclass BaseLLMClient, implement `complete()`,
then register in LLMClientFactory.get().
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict

from django.conf import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Base contract
# ──────────────────────────────────────────────

class BaseLLMClient(ABC):
    """All LLM providers must satisfy this interface."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return a raw text completion."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable identifier for logging."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier (openai / huggingface / anthropic)."""


# ──────────────────────────────────────────────
# OpenAI (and OpenAI-compatible) provider
# ──────────────────────────────────────────────

class OpenAIClient(BaseLLMClient):
    def __init__(self) -> None:
        from openai import OpenAI  # lazy import — not a hard dep if unused

        kwargs: Dict[str, Any] = {"api_key": settings.LLM_API_KEY}
        if settings.LLM_BASE_URL:
            kwargs["base_url"] = settings.LLM_BASE_URL   # supports HuggingFace TGI, vLLM, etc.

        self._client = OpenAI(**kwargs)
        self._model = settings.LLM_MODEL

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        logger.debug("LLM request | provider=openai model=%s", self._model)
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        logger.debug("LLM response received | length=%d", len(text))
        return text


# ──────────────────────────────────────────────
# HuggingFace / custom OpenAI-compatible endpoint
# (reuses OpenAIClient with a custom base_url)
# ──────────────────────────────────────────────

class HuggingFaceClient(OpenAIClient):
    """
    HuggingFace Inference Endpoints expose an OpenAI-compatible API.
    Set LLM_BASE_URL to your endpoint and LLM_API_KEY to your HF token.
    """

    @property
    def provider_name(self) -> str:
        return "huggingface"


# ──────────────────────────────────────────────
# Anthropic provider
# ──────────────────────────────────────────────

class AnthropicClient(BaseLLMClient):
    def __init__(self) -> None:
        import anthropic  # lazy import

        self._client = anthropic.Anthropic(api_key=settings.LLM_API_KEY)
        self._model = settings.LLM_MODEL or "claude-haiku-4-5-20251001"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        logger.debug("LLM request | provider=anthropic model=%s", self._model)
        message = self._client.messages.create(
            model=self._model,
            max_tokens=settings.LLM_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = message.content[0].text if message.content else ""
        logger.debug("LLM response received | length=%d", len(text))
        return text


# ──────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────

class LLMClientFactory:
    _REGISTRY: Dict[str, type] = {
        "openai": OpenAIClient,
        "huggingface": HuggingFaceClient,
        "anthropic": AnthropicClient,
    }

    @classmethod
    def get(cls) -> BaseLLMClient:
        provider = (settings.LLM_PROVIDER or "openai").lower()
        client_cls = cls._REGISTRY.get(provider)
        if not client_cls:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{provider}'. "
                f"Valid options: {list(cls._REGISTRY.keys())}"
            )
        return client_cls()


# ──────────────────────────────────────────────
# JSON extraction helper (shared utility)
# ──────────────────────────────────────────────

def extract_json_block(raw: str) -> Dict[str, Any]:
    """
    Safely extract a JSON object from an LLM response that may contain
    markdown fences or surrounding prose.
    """
    # Try to find ```json ... ``` block first
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    # Fall back to first { ... } in the string
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        return json.loads(brace.group(0))

    raise ValueError(f"No JSON object found in LLM response: {raw[:200]!r}")
