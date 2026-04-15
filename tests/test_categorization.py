"""
tests/test_categorization.py — Unit & integration tests.

Run with: python manage.py test tests
or:        pytest tests/
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("LLM_API_KEY", "test-key")
django.setup()

from categorizer.schemas import (
    CategorizationRequest,
    CategorizationResponse,
    Transaction,
    HistoricalTransaction,
)
from categorizer.services.context_builder import build_prompts
from categorizer.services.response_formatter import parse_and_format
from categorizer.services.llm_client import extract_json_block


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

CHART_OF_ACCOUNTS = [
    "Software & Subscriptions",
    "Travel & Lodging",
    "Meals & Entertainment",
    "Office Supplies",
    "Professional Services",
    "Miscellaneous",
]

HISTORY = [
    HistoricalTransaction(
        description="AWS bill",
        payee="Amazon",
        amount=200.0,
        category="Software & Subscriptions",
    ),
    HistoricalTransaction(
        description="Hotel NYC",
        payee="Hilton",
        amount=350.0,
        category="Travel & Lodging",
    ),
]

SAMPLE_REQUEST = CategorizationRequest(
    transaction=Transaction(
        description="Monthly Notion Pro subscription",
        payee="Notion Labs",
        amount=16.00,
        currency="USD",
    ),
    company_id="test-company",
    industry="Technology",
    chart_of_accounts=CHART_OF_ACCOUNTS,
    historical_transactions=HISTORY,
)

MOCK_LLM_RESPONSE = json.dumps({
    "suggested_category": "Software & Subscriptions",
    "confidence": 0.93,
    "reasoning": "Notion is a SaaS tool; subscription charges map to Software & Subscriptions.",
    "alternatives": [
        {
            "category": "Miscellaneous",
            "confidence": 0.05,
            "reasoning": "Catch-all fallback.",
        }
    ],
})


# ──────────────────────────────────────────────
# Schema validation tests
# ──────────────────────────────────────────────

class TestSchemaValidation(unittest.TestCase):

    def test_valid_request_parses(self):
        req = SAMPLE_REQUEST
        self.assertEqual(req.company_id, "test-company")
        self.assertEqual(req.transaction.description, "Monthly Notion Pro subscription")

    def test_empty_chart_of_accounts_raises(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            CategorizationRequest(
                transaction=Transaction(description="Test txn"),
                company_id="co",
                industry="Tech",
                chart_of_accounts=[],
            )

    def test_history_capped_at_20(self):
        many_history = [
            HistoricalTransaction(description=f"txn {i}", category="Miscellaneous")
            for i in range(30)
        ]
        req = CategorizationRequest(
            transaction=Transaction(description="Test"),
            company_id="co",
            industry="Tech",
            chart_of_accounts=["Miscellaneous"],
            historical_transactions=many_history,
        )
        self.assertEqual(len(req.historical_transactions), 20)

    def test_confidence_label_thresholds(self):
        self.assertEqual(CategorizationResponse.confidence_label_from_score(0.9), "HIGH")
        self.assertEqual(CategorizationResponse.confidence_label_from_score(0.65), "MEDIUM")
        self.assertEqual(CategorizationResponse.confidence_label_from_score(0.3), "LOW")


# ──────────────────────────────────────────────
# Context builder tests
# ──────────────────────────────────────────────

class TestContextBuilder(unittest.TestCase):

    def test_prompts_contain_company_context(self):
        system_prompt, user_prompt = build_prompts(SAMPLE_REQUEST)
        self.assertIn("test-company", user_prompt)
        self.assertIn("Technology", user_prompt)

    def test_prompts_contain_chart_of_accounts(self):
        _, user_prompt = build_prompts(SAMPLE_REQUEST)
        for account in CHART_OF_ACCOUNTS:
            self.assertIn(account, user_prompt)

    def test_prompts_contain_historical_examples(self):
        _, user_prompt = build_prompts(SAMPLE_REQUEST)
        self.assertIn("AWS bill", user_prompt)
        self.assertIn("Software & Subscriptions", user_prompt)

    def test_prompts_contain_transaction_description(self):
        _, user_prompt = build_prompts(SAMPLE_REQUEST)
        self.assertIn("Monthly Notion Pro subscription", user_prompt)

    def test_system_prompt_instructs_json_only(self):
        system_prompt, _ = build_prompts(SAMPLE_REQUEST)
        self.assertIn("JSON", system_prompt)

    def test_no_history_gracefully_handled(self):
        req = CategorizationRequest(
            transaction=Transaction(description="Random charge"),
            company_id="co",
            industry="Retail",
            chart_of_accounts=["Miscellaneous"],
            historical_transactions=[],
        )
        _, user_prompt = build_prompts(req)
        self.assertIn("no historical data", user_prompt)


# ──────────────────────────────────────────────
# JSON extraction tests
# ──────────────────────────────────────────────

class TestExtractJsonBlock(unittest.TestCase):

    def test_plain_json(self):
        raw = '{"key": "value"}'
        self.assertEqual(extract_json_block(raw), {"key": "value"})

    def test_fenced_json(self):
        raw = '```json\n{"key": "value"}\n```'
        self.assertEqual(extract_json_block(raw), {"key": "value"})

    def test_json_with_prose(self):
        raw = 'Here is the result:\n{"key": "value"}\nThat is all.'
        self.assertEqual(extract_json_block(raw), {"key": "value"})

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            extract_json_block("No JSON here at all.")


# ──────────────────────────────────────────────
# Response formatter tests
# ──────────────────────────────────────────────

class TestResponseFormatter(unittest.TestCase):

    def _mock_client(self):
        client = MagicMock()
        client.model_name = "gpt-4o-mini"
        client.provider_name = "openai"
        return client

    def test_valid_response_parsed(self):
        result = parse_and_format(MOCK_LLM_RESPONSE, SAMPLE_REQUEST, self._mock_client())
        self.assertEqual(result.suggested_category, "Software & Subscriptions")
        self.assertAlmostEqual(result.confidence_score, 0.93)
        self.assertEqual(result.confidence_label, "HIGH")
        self.assertEqual(len(result.alternative_categories), 1)

    def test_category_not_in_coa_raises(self):
        bad_response = json.dumps({
            "suggested_category": "Totally Made Up Category",
            "confidence": 0.8,
            "reasoning": "test",
            "alternatives": [],
        })
        with self.assertRaises(ValueError):
            parse_and_format(bad_response, SAMPLE_REQUEST, self._mock_client())

    def test_confidence_clamped(self):
        resp = json.dumps({
            "suggested_category": "Software & Subscriptions",
            "confidence": 1.5,   # out of range
            "reasoning": "test",
            "alternatives": [],
        })
        result = parse_and_format(resp, SAMPLE_REQUEST, self._mock_client())
        self.assertLessEqual(result.confidence_score, 1.0)

    def test_case_insensitive_category_match(self):
        resp = json.dumps({
            "suggested_category": "software & subscriptions",  # lowercase
            "confidence": 0.7,
            "reasoning": "test",
            "alternatives": [],
        })
        result = parse_and_format(resp, SAMPLE_REQUEST, self._mock_client())
        self.assertEqual(result.suggested_category, "Software & Subscriptions")

    def test_model_and_provider_populated(self):
        result = parse_and_format(MOCK_LLM_RESPONSE, SAMPLE_REQUEST, self._mock_client())
        self.assertEqual(result.model_used, "gpt-4o-mini")
        self.assertEqual(result.provider, "openai")


# ──────────────────────────────────────────────
# Full pipeline integration test (LLM mocked)
# ──────────────────────────────────────────────

class TestCategorizationServiceIntegration(unittest.TestCase):

    @patch("categorizer.services.categorization_service.LLMClientFactory.get")
    def test_pipeline_end_to_end(self, mock_factory):
        mock_client = MagicMock()
        mock_client.model_name = "gpt-4o-mini"
        mock_client.provider_name = "openai"
        mock_client.complete.return_value = MOCK_LLM_RESPONSE
        mock_factory.return_value = mock_client

        from categorizer.services.categorization_service import categorize_transaction

        result = categorize_transaction(SAMPLE_REQUEST)

        self.assertEqual(result.suggested_category, "Software & Subscriptions")
        self.assertEqual(result.confidence_label, "HIGH")
        mock_client.complete.assert_called_once()

    @patch("categorizer.services.categorization_service.LLMClientFactory.get")
    def test_llm_failure_raises_value_error(self, mock_factory):
        mock_client = MagicMock()
        mock_client.complete.side_effect = Exception("Network timeout")
        mock_factory.return_value = mock_client

        from categorizer.services.categorization_service import categorize_transaction

        with self.assertRaises(Exception):
            categorize_transaction(SAMPLE_REQUEST)


if __name__ == "__main__":
    unittest.main()
