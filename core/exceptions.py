"""
Custom exceptions for the core app service layer.

Each service module raises its own typed exception so the orchestrator
and view layer can handle failures granularly.
"""

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """Base exception for all service-layer errors."""
    pass


# ---------------------------------------------------------------------------
# Webhook parsing
# ---------------------------------------------------------------------------


class WebhookParsingError(ServiceError):
    """Raised when the incoming webhook payload cannot be parsed."""
    pass


# ---------------------------------------------------------------------------
# WhatsApp account lookup
# ---------------------------------------------------------------------------
class WhatsAppAccountNotFoundError(ServiceError):
    """Raised when no active WhatsAppAccount matches the webhook metadata."""
    pass

class OutlookAccountNotFoundError(ServiceError):
    """Raised when no active Outlook Account matches the webhook metadata."""
    pass


# ---------------------------------------------------------------------------
# Meta Graph API
# ---------------------------------------------------------------------------


class MetaAPIError(ServiceError):
    """Raised when the Meta WhatsApp Cloud API returns a non-success response."""

    def __init__(self, message: str, status_code: int | None = None, response_body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


# ---------------------------------------------------------------------------
# AI service
# ---------------------------------------------------------------------------


class AIServiceError(ServiceError):
    """Raised when the external AI API call fails or returns an unusable response."""

    def __init__(self, message: str, status_code: int | None = None, response_body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


# ---------------------------------------------------------------------------
# DRF custom exception handler (referenced by settings.REST_FRAMEWORK)
# ---------------------------------------------------------------------------


def custom_exception_handler(exc, context):
    """
    Extend the default DRF exception handler to ensure every error response
    follows a consistent JSON envelope: ``{"error": ..., "detail": ...}``.
    """
    response = exception_handler(exc, context)

    if response is not None:
        custom_data = {
            "error": True,
            "status_code": response.status_code,
            "detail": response.data,
        }
        response.data = custom_data

    return response
