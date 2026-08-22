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
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema
from django.views import View
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from core.choices import WebhookSource
from core.models import WebhookLog
from core.services.orchestrator import WebhookOrchestrator
from intake.telegram_workflow import TelegramWorkflowService

logger = logging.getLogger(__name__)


class WhatsappWebhook(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    # ------------------------------------------------------------------
    # GET — Meta verification handshake
    @extend_schema(
        parameters=[
            OpenApiParameter("hub.mode", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("hub.verify_token", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("hub.challenge", OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
        responses={
            200: OpenApiResponse(response=OpenApiTypes.STR, description="Meta verification challenge"),
            403: OpenApiResponse(response=OpenApiTypes.STR, description="Invalid verification token"),
        },
    )
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
    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={
            200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Webhook accepted"),
            403: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Invalid signature"),
        },
    )
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

    @extend_schema(
        parameters=[
            OpenApiParameter("validationToken", OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
        responses={
            200: OpenApiResponse(response=OpenApiTypes.STR, description="Outlook validation token"),
            400: OpenApiResponse(description="Missing validation token"),
        },
    )
    def get(self, request, *args, **kwargs):
        token = request.GET.get("validationToken")
        if token:
            return HttpResponse(token, status=200, content_type="text/plain")
        return HttpResponse(status=400)
    
    # ------------------------------------------------------------------
    # POST — incoming webhook events
    @extend_schema(
        request=OpenApiTypes.OBJECT,
        parameters=[
            OpenApiParameter("validationToken", OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
        responses={
            200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Webhook accepted"),
        },
    )
    def post(self, request, *args, **kwargs) -> Response:
        token = request.GET.get("validationToken")
        if token:
            return HttpResponse(token, status=200, content_type="text/plain")

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
            logger.info("Outlook webhook processed successfully")
        except Exception:
            logger.exception("Outlook orchestrator raised an unhandled exception")

        return Response(
            {
                "status": "EVENT_RECEIVED",
                "message": "Outlook webhook processed successfully.",
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

class TelegramWebhook(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Webhook accepted")},
    )
    def post(self, request):
        logger.info("Telegram webhook received: %s", request.data)
        result = TelegramWorkflowService().handle_update(request.data)
        return Response(result)
    
    @extend_schema(
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="Webhook health response")},
    )
    def get(self, request):
        logger.info("Telegram webhook health check")
        return Response({"ok": True})

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


