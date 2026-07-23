from __future__ import annotations
import hashlib
import hmac
import json
import logging
from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views import View
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from core.choices import WebhookSource
from core.models import WebhookLog
from core.services.orchestrator import WebhookOrchestrator

logger = logging.getLogger(__name__)


class WhatsappWebhook(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    # ------------------------------------------------------------------
    # GET — Meta verification handshake
    def get(self, request, *args, **kwargs) -> HttpResponse:
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        expected_token = settings.WHATSAPP.get("VERIFY_TOKEN", "")

        if mode == "subscribe" and token == expected_token:
            logger.info("Webhook verification succeeded")
            return HttpResponse(challenge, content_type="text/plain", status=200)

        logger.warning("Webhook verification failed — token mismatch")
        return HttpResponse("Invalid verification token", status=403)

    # ------------------------------------------------------------------
    # POST — incoming webhook events
    def post(self, request, *args, **kwargs) -> Response:
        if not self._verify_signature(request):
            logger.warning("HMAC signature verification failed — ignoring payload")
            return Response(
                {"status": "INVALID_SIGNATURE"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Parse body
        raw_body = request.body.decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError):
            logger.error("Failed to decode webhook JSON body")
            return Response(
                {"status": "EVENT_RECEIVED"},
                status=status.HTTP_200_OK,
            )

        # Persist raw webhook log
        webhook_log = WebhookLog.objects.create(
            method=request.method,
            source=WebhookSource.META,
            path=request.path,
            headers=dict(request.headers),
            payload=payload,
            body=raw_body,
            ip_address=self._get_client_ip(request),
        )
        logger.info("Webhook logged id=%s", webhook_log.pk)
        # print("payload: ", payload)
        # Delegate all business logic to the orchestrator
        try:
            WebhookOrchestrator.process_webhook(payload, webhook_log)
            logger.info("Webhook processed successfully")
        except Exception:
            logger.exception("Orchestrator raised an unhandled exception")

        return Response(
            {
                "status": "EVENT_RECEIVED",
                "message": "Webhook processed successfully.",
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------------
    # Helpers
    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")

    @staticmethod
    def _verify_signature(request) -> bool:
        app_secret: str = settings.WHATSAPP.get("APP_SECRET", "")
        if not app_secret:
            return True

        signature_header = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
        if not signature_header.startswith("sha256="):
            return False

        expected_sig = signature_header[7:]  # strip "sha256=" prefix
        computed_sig = hmac.new(
            key=app_secret.encode("utf-8"),
            msg=request.body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed_sig, expected_sig)

class OutlookWebhook(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request, *args, **kwargs):
        token = request.GET.get("validationToken")
        if token:
            return HttpResponse(token, status=200, content_type="text/plain")
        return HttpResponse(status=400)
    
    # ------------------------------------------------------------------
    # POST — incoming webhook events
    def post(self, request, *args, **kwargs) -> Response:
        # Parse body
        raw_body = request.body.decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError):
            logger.error("Failed to decode webhook JSON body")
            return Response(
                {"status": "EVENT_RECEIVED"},
                status=status.HTTP_200_OK,
            )

        # Persist raw webhook log
        webhook_log = WebhookLog.objects.create(
            method=request.method,
            source=WebhookSource.OUTLOOK,
            path=request.path,
            headers=dict(request.headers),
            payload=payload,
            body=raw_body,
            ip_address=self._get_client_ip(request),
        )
        logger.info("Webhook logged id=%s", webhook_log.pk)

        try:
            WebhookOrchestrator.process_outlook_webhook(payload, webhook_log)
        except Exception:
            logger.exception("Orchestrator raised an unhandled exception")
        
        token = request.GET.get("validationToken")
        return Response(
            {
                "token": token
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------------
    # Helpers
    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


# @method_decorator(csrf_exempt, name="dispatch")
# class OutlookWebhook(View):

#     def get(self, request, *args, **kwargs):
#         token = request.GET.get("validationToken")
#         if token:
#             return HttpResponse(token, status=200, content_type="text/plain")
#         return HttpResponse(status=400)

#     def post(self, request, *args, **kwargs):
#         print("=====================================================")
#         logger.info("GET Params: %s", request.GET)
#         logger.info("Accept: %s", request.headers.get("Accept"))
#         logger.info("Method: %s", request.method)
#         logger.info("Request Body: %s", request.body)
#         print("=====================================================")

#         token = request.GET.get("validationToken")
#         return HttpResponse(token, status=200, content_type="text/plain")


