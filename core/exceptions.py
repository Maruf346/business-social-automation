from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


# Base
class ServiceError(Exception):
    pass

# Webhook parsing
class WebhookParsingError(ServiceError):
    pass

# WhatsApp account lookup
class WhatsAppAccountNotFoundError(ServiceError):
    pass

class OutlookAccountNotFoundError(ServiceError):
    pass


# Meta Graph API
class MetaAPIError(ServiceError):
    def __init__(self, message: str, status_code: int | None = None, response_body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}

# AI service
class AIServiceError(ServiceError):
    def __init__(self, message: str, status_code: int | None = None, response_body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}

# Outlook / Microsoft Graph API
class OutlookAPIError(ServiceError):
    """Raised when a Microsoft Graph API call fails."""

    def __init__(self, message: str, status_code: int | None = None, response_body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}

# Media download / storage
class MediaDownloadError(ServiceError):
    pass

# ----------------------------------------------
# DRF custom exception handler
def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        custom_data = {
            "error": True,
            "status_code": response.status_code,
            "detail": response.data,
        }
        response.data = custom_data

    return response
