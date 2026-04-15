"""
views.py — Thin DRF views. No business logic here.
"""
from __future__ import annotations

import logging

from pydantic import ValidationError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from categorizer.schemas import CategorizationRequest
from categorizer.services import categorize_transaction
from sample_data.mock_data import SAMPLE_REQUESTS

logger = logging.getLogger(__name__)


class CategorizeTransactionView(APIView):
    """
    POST /api/v1/categorize/
    Accepts a transaction + company context, returns a categorization suggestion.
    """

    def post(self, request: Request) -> Response:
        # Validate input via Pydantic schema
        try:
            payload = CategorizationRequest(**request.data)
        except ValidationError as exc:
            return Response(
                {"error": "Invalid request payload.", "detail": exc.errors()},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except TypeError as exc:
            return Response(
                {"error": "Malformed JSON.", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Delegate to service layer
        try:
            result = categorize_transaction(payload)
        except ValueError as exc:
            logger.error("Categorization failed: %s", exc)
            return Response(
                {"error": "Categorization failed.", "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(result.model_dump(), status=status.HTTP_200_OK)


class HealthCheckView(APIView):
    """GET /api/v1/health/ — liveness probe."""

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class SampleDataView(APIView):
    """
    GET /api/v1/samples/
    Returns mock sample requests useful for manual testing and evaluation.
    """

    def get(self, request: Request) -> Response:
        return Response({"samples": SAMPLE_REQUESTS}, status=status.HTTP_200_OK)
