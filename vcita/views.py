from __future__ import annotations

import json
import logging
from typing import Any

from drf_spectacular.utils import OpenApiResponse, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services.telegram_bot_service import TelegramBotService
from intake.models import IntakeRequest, PaymentStatus, ScheduleStatus

from .models import VcitaAccount, VcitaWebhookEvent

logger = logging.getLogger(__name__)


class VcitaWebhook(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    @extend_schema(
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="vCita webhook health response")},
    )
    def get(self, request):
        return Response({"ok": True, "integration": "vcita"})

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="vCita webhook accepted")},
    )
    def post(self, request):
        raw_body = request.body.decode("utf-8", errors="ignore")
        payload, parse_error = self._parse_payload(raw_body)
        account = VcitaAccount.objects.filter(is_active=True).first()
        if account and account.webhook_secret:
            provided_secret = request.query_params.get("secret") or request.headers.get("X-Vcita-Webhook-Secret", "")
            if provided_secret != account.webhook_secret:
                return Response({"detail": "Invalid webhook secret."}, status=status.HTTP_403_FORBIDDEN)

        event = VcitaWebhookEvent.objects.create(
            account=account,
            method=request.method,
            path=request.path,
            headers=dict(request.headers),
            payload=payload,
            body=raw_body,
            ip_address=self._get_client_ip(request),
            event_type=self._extract_value(payload, "event_type", "event", "type", "action"),
            entity=self._extract_value(payload, "entity", "object", "resource", "model"),
            external_id=self._extract_external_id(payload),
            processing_error=parse_error,
        )
        logger.info("vCita webhook stored id=%s event_type=%s entity=%s", event.pk, event.event_type, event.entity)
        self._process_event(event)

        return Response(
            {
                "status": "EVENT_RECEIVED",
                "event_id": event.pk,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _parse_payload(raw_body: str) -> tuple[dict, str]:
        if not raw_body.strip():
            return {}, ""
        try:
            data = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError) as exc:
            return {}, f"Invalid JSON payload: {exc}"
        if not isinstance(data, dict):
            return {"value": data}, "Payload root was not an object."
        return data, ""

    @staticmethod
    def _extract_value(payload: dict, *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return str(value)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if value is not None:
                    return str(value)
        return ""

    @classmethod
    def _process_event(cls, event: VcitaWebhookEvent) -> None:
        event_name = f"{event.entity}/{event.event_type}".strip("/")
        normalized_event = event_name.lower()
        booking_uid = cls._find_nested_value(
            event.payload,
            {
                "booking_id",
                "booking_uid",
                "appointment_id",
                "appointment_uid",
                "meeting_id",
                "meeting_uid",
            },
        )
        if not booking_uid and event.entity.lower() in {"booking", "appointment", "meeting"}:
            booking_uid = event.external_id
        if not booking_uid:
            return

        intakes = IntakeRequest.objects.select_related("assigned_artist").filter(vcita_booking_uid=booking_uid)
        if not intakes.exists():
            return

        updated = False
        for intake in intakes:
            message = ""
            update_fields = ["updated_at"]
            if "paid" in normalized_event:
                intake.payment_status = PaymentStatus.PAID
                intake.payment_reference = event.external_id or booking_uid
                update_fields.extend(["payment_status", "payment_reference"])
                message = f"Request #{intake.pk}: vCita payment marked paid."
            elif "refunded" in normalized_event:
                intake.payment_status = PaymentStatus.REFUNDED
                intake.payment_reference = event.external_id or booking_uid
                update_fields.extend(["payment_status", "payment_reference"])
                message = f"Request #{intake.pk}: vCita payment marked refunded."
            elif "failed" in normalized_event:
                intake.payment_status = PaymentStatus.FAILED
                intake.payment_reference = event.external_id or booking_uid
                update_fields.extend(["payment_status", "payment_reference"])
                message = f"Request #{intake.pk}: vCita payment marked failed."
            elif "cancelled" in normalized_event or "canceled" in normalized_event:
                intake.schedule_status = ScheduleStatus.CANCELLED
                update_fields.append("schedule_status")
                message = f"Request #{intake.pk}: vCita booking was cancelled."
            elif "rescheduled" in normalized_event:
                intake.schedule_status = ScheduleStatus.RESCHEDULED
                update_fields.append("schedule_status")
                message = f"Request #{intake.pk}: vCita booking was rescheduled."

            if not message:
                continue

            intake.save(update_fields=update_fields)
            updated = True
            cls._notify_telegram(message)

        if updated:
            event.status = "processed"
            event.save(update_fields=["status", "updated_at"])

    @staticmethod
    def _find_nested_value(value: Any, keys: set[str]) -> str:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and item:
                    return str(item)
            for item in value.values():
                nested = VcitaWebhook._find_nested_value(item, keys)
                if nested:
                    return nested
        if isinstance(value, list):
            for item in value:
                nested = VcitaWebhook._find_nested_value(item, keys)
                if nested:
                    return nested
        return ""

    @staticmethod
    def _notify_telegram(message: str) -> None:
        try:
            TelegramBotService().send_message(text=message)
        except Exception:
            logger.exception("Failed to notify Telegram for vCita webhook event.")

    @classmethod
    def _extract_external_id(cls, payload: dict) -> str:
        for key in ("id", "uid", "external_id", "resource_id"):
            value = payload.get(key)
            if value is not None:
                return str(value)

        data: Any = payload.get("data")
        if isinstance(data, dict):
            for key in ("id", "uid", "external_id", "resource_id"):
                value = data.get(key)
                if value is not None:
                    return str(value)
        return ""

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")
