"""
exception_handler.py — Global DRF exception handler.
Returns a consistent error envelope for all error responses.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    # Let DRF handle its own exceptions first
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "error": _summarise(exc),
            "detail": response.data,
            "code": getattr(exc, "default_code", None),
        }
        return response

    # Unhandled exceptions → 500
    logger.exception("Unhandled exception in view: %s", exc)
    return Response(
        {
            "error": "Internal server error.",
            "detail": str(exc),
            "code": "internal_error",
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _summarise(exc: Exception) -> str:
    return type(exc).__name__.replace("Exception", " error").strip()
