from __future__ import annotations

import json
import logging
from typing import Any

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services.telegram_bot_service import TelegramBotService
from intake.models import IntakeRequest, PaymentStatus, PendingHoldStatus, ScheduleStatus
from vcita.api import VcitaAPIClient, VcitaAPIError
from vcita.scheduling import VcitaSchedulingError, VcitaSchedulingService

from .models import (
    VcitaAccount,
    VcitaFinancialRecord,
    VcitaFinancialRecordStatus,
    VcitaFinancialRecordType,
    VcitaWebhookEvent,
    VcitaWebhookStatus,
)

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
        normalized_event = cls._normalized_event(event)
        try:
            intakes, reference_uid, financial_record = cls._resolve_intakes(event, normalized_event)
        except VcitaAPIError as exc:
            cls._mark_event_failed(event, f"Could not resolve vCita webhook through API lookup: {cls._format_api_error(exc)}")
            cls._notify_telegram(
                "vCita webhook could not be matched because a vCita API lookup failed. "
                f"Event #{event.pk}: {cls._format_api_error(exc)}"
            )
            return

        if not intakes:
            cls._mark_event_unmatched(
                event,
                "Could not match vCita webhook to an intake. Stored payload for review.",
            )
            cls._notify_telegram(
                "vCita webhook could not be matched to any request. "
                f"Event #{event.pk}; reference: {reference_uid or event.external_id or 'none'}. Please review in the Admin panel."
            )
            return

        if len(intakes) > 1:
            ids = ", ".join(str(item.pk) for item in intakes)
            cls._mark_event_unmatched(event, f"Webhook matched multiple requests: {ids}")
            cls._notify_telegram(
                f"vCita webhook matched multiple requests ({ids}). Event #{event.pk} needs Admin panel review."
            )
            return

        intake = intakes[0]
        message = cls._apply_event_to_intake(intake, normalized_event, reference_uid, event)
        if not message:
            event.status = VcitaWebhookStatus.PROCESSED
            event.save(update_fields=["status", "updated_at"])
            return

        if financial_record:
            financial_record.intake = intake
            financial_record.lead = intake.lead
            financial_record.last_webhook_event = event
            financial_record.save(update_fields=["intake", "lead", "last_webhook_event", "updated_at"])

        event.status = VcitaWebhookStatus.PROCESSED
        event.processing_error = ""
        event.save(update_fields=["status", "processing_error", "updated_at"])
        cls._notify_telegram(message)

        if cls._is_paid_event(normalized_event):
            cls._try_finalize_pending_hold(intake, event)

    @classmethod
    def _resolve_intakes(
        cls,
        event: VcitaWebhookEvent,
        normalized_event: str,
    ) -> tuple[list[IntakeRequest], str, VcitaFinancialRecord | None]:
        booking_uid = cls._extract_booking_uid(event)
        if booking_uid:
            return list(
                IntakeRequest.objects.select_related("assigned_artist", "lead", "pending_hold_service").filter(
                    vcita_booking_uid=booking_uid
                )
            ), booking_uid, None

        matter_uid = cls._find_nested_value(event.payload, {"matter_uid", "matter_id", "engagement_uid", "engagement_id"})
        financial_type, financial_uid = cls._extract_financial_reference(event, normalized_event)
        financial_record = None

        if financial_type and financial_uid:
            financial_record = VcitaFinancialRecord.objects.filter(
                account=event.account,
                record_type=financial_type,
                vcita_uid=financial_uid,
            ).select_related("intake", "lead").first()
            if financial_record and financial_record.intake_id:
                return [financial_record.intake], financial_uid, financial_record

            payload = event.payload
            if not matter_uid and event.account:
                payload = cls._fetch_financial_payload(event.account, financial_type, financial_uid)
                matter_uid = cls._find_nested_value(payload, {"matter_uid", "matter_id", "engagement_uid", "engagement_id"})

            financial_record = cls._upsert_financial_record(
                event=event,
                record_type=financial_type,
                vcita_uid=financial_uid,
                matter_uid=matter_uid,
                normalized_event=normalized_event,
                payload=payload,
            )

        if matter_uid:
            intakes = list(
                IntakeRequest.objects.select_related("assigned_artist", "lead", "pending_hold_service").filter(
                    vcita_matter_uid=matter_uid
                )
            )
            return intakes, financial_uid or matter_uid, financial_record

        return [], financial_uid or event.external_id, financial_record

    @classmethod
    def _apply_event_to_intake(
        cls,
        intake: IntakeRequest,
        normalized_event: str,
        reference_uid: str,
        event: VcitaWebhookEvent,
    ) -> str:
        message = ""
        update_fields = ["updated_at"]
        reference = reference_uid or event.external_id or ""

        if cls._is_paid_event(normalized_event):
            if intake.payment_status != PaymentStatus.PAID:
                intake.payment_status = PaymentStatus.PAID
                update_fields.append("payment_status")
            intake.payment_reference = reference
            update_fields.append("payment_reference")
            message = f"Request #{intake.pk}: vCita payment marked paid."
        elif "refunded" in normalized_event:
            intake.payment_status = PaymentStatus.REFUNDED
            intake.payment_reference = reference
            update_fields.extend(["payment_status", "payment_reference"])
            message = f"Request #{intake.pk}: vCita payment marked refunded."
        elif "cancelled" in normalized_event or "canceled" in normalized_event:
            if "payment" in normalized_event:
                intake.payment_status = PaymentStatus.CANCELLED
                intake.payment_reference = reference
                update_fields.extend(["payment_status", "payment_reference"])
                message = f"Request #{intake.pk}: vCita payment marked cancelled."
            else:
                intake.schedule_status = ScheduleStatus.CANCELLED
                update_fields.append("schedule_status")
                message = f"Request #{intake.pk}: vCita booking was cancelled."
        elif "failed" in normalized_event:
            intake.payment_status = PaymentStatus.FAILED
            intake.payment_reference = reference
            update_fields.extend(["payment_status", "payment_reference"])
            message = f"Request #{intake.pk}: vCita payment marked failed."
        elif "rescheduled" in normalized_event:
            intake.schedule_status = ScheduleStatus.RESCHEDULED
            update_fields.append("schedule_status")
            message = f"Request #{intake.pk}: vCita booking was rescheduled."
        elif "invoice/issued" in normalized_event:
            if intake.payment_status == PaymentStatus.UNKNOWN:
                intake.payment_status = PaymentStatus.PENDING
                update_fields.append("payment_status")
            intake.payment_reference = reference
            update_fields.append("payment_reference")
            message = f"Request #{intake.pk}: vCita invoice was issued."
        elif "invoice/updated" in normalized_event or "deposit/created" in normalized_event or "payment/updated" in normalized_event:
            if intake.payment_status == PaymentStatus.UNKNOWN:
                intake.payment_status = PaymentStatus.PENDING
                update_fields.append("payment_status")
            if reference:
                intake.payment_reference = reference
                update_fields.append("payment_reference")
            message = f"Request #{intake.pk}: vCita payment record was updated."

        if not message:
            return ""

        intake.save(update_fields=list(dict.fromkeys(update_fields)))
        return message

    @classmethod
    def _try_finalize_pending_hold(cls, intake: IntakeRequest, event: VcitaWebhookEvent) -> None:
        if intake.pending_hold_status != PendingHoldStatus.ACTIVE:
            return
        if intake.schedule_status in {ScheduleStatus.SCHEDULED, ScheduleStatus.RESCHEDULED} and intake.vcita_booking_uid:
            cls._notify_telegram(
                f"Request #{intake.pk}: payment is paid, but final appointment already exists. No duplicate booking was created."
            )
            return
        service_code = intake.pending_hold_service_code
        if not service_code:
            cls._notify_telegram(
                f"Request #{intake.pk}: payment is paid, but no pending service code is stored. Please schedule manually."
            )
            return
        try:
            result = VcitaSchedulingService(account=event.account).schedule_intake(
                intake=intake,
                appointment_date=intake.pending_hold_date,
                appointment_time=intake.pending_hold_time,
                service_code=service_code,
            )
        except VcitaSchedulingError as exc:
            cls._notify_telegram(
                f"Request #{intake.pk}: payment is paid, but final vCita appointment could not be created. "
                f"Pending hold remains active. Reason: {exc}"
            )
            return

        cls._notify_telegram(
            f"Request #{intake.pk}: payment is paid and final appointment was created. "
            f"When: {result.requested_date} at {result.requested_time}. "
            f"vCita booking ID: {result.booking_uid}"
        )

    @classmethod
    def _extract_booking_uid(cls, event: VcitaWebhookEvent) -> str:
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
        return booking_uid

    @classmethod
    def _extract_financial_reference(cls, event: VcitaWebhookEvent, normalized_event: str) -> tuple[str, str]:
        reference_map = (
            (VcitaFinancialRecordType.PAYMENT, {"payment_uid", "payment_id"}),
            (VcitaFinancialRecordType.INVOICE, {"invoice_uid", "invoice_id"}),
            (VcitaFinancialRecordType.DEPOSIT, {"deposit_uid", "deposit_id"}),
        )
        for record_type, keys in reference_map:
            uid = cls._find_nested_value(event.payload, keys)
            if uid:
                return record_type, uid

        entity = event.entity.lower()
        if entity in {"payment", "invoice", "deposit"} and event.external_id:
            return entity, event.external_id
        if normalized_event.startswith("payment/") and event.external_id:
            return VcitaFinancialRecordType.PAYMENT, event.external_id
        if normalized_event.startswith("invoice/") and event.external_id:
            return VcitaFinancialRecordType.INVOICE, event.external_id
        if normalized_event.startswith("deposit/") and event.external_id:
            return VcitaFinancialRecordType.DEPOSIT, event.external_id
        return "", ""

    @staticmethod
    def _fetch_financial_payload(account: VcitaAccount, record_type: str, vcita_uid: str) -> dict[str, Any]:
        client = VcitaAPIClient(account)
        if record_type == VcitaFinancialRecordType.PAYMENT:
            return client.get_payment(vcita_uid)
        if record_type == VcitaFinancialRecordType.INVOICE:
            return client.get_invoice(vcita_uid)
        if record_type == VcitaFinancialRecordType.DEPOSIT:
            return client.get_deposit(vcita_uid)
        return {}

    @classmethod
    def _upsert_financial_record(
        cls,
        event: VcitaWebhookEvent,
        record_type: str,
        vcita_uid: str,
        matter_uid: str,
        normalized_event: str,
        payload: dict[str, Any],
    ) -> VcitaFinancialRecord:
        intake = None
        lead = None
        if matter_uid:
            intake = IntakeRequest.objects.filter(vcita_matter_uid=matter_uid).select_related("lead").first()
            if intake:
                lead = intake.lead

        record, _ = VcitaFinancialRecord.objects.update_or_create(
            account=event.account,
            record_type=record_type,
            vcita_uid=vcita_uid,
            defaults={
                "intake": intake,
                "lead": lead,
                "last_webhook_event": event,
                "matter_uid": matter_uid,
                "status": cls._financial_status_from_event(normalized_event, payload),
                "amount": cls._extract_amount(payload),
                "currency": cls._find_nested_value(payload, {"currency"}),
                "raw_payload": payload if isinstance(payload, dict) else {},
            },
        )
        return record

    @staticmethod
    def _financial_status_from_event(normalized_event: str, payload: dict[str, Any]) -> str:
        if "paid" in normalized_event:
            return VcitaFinancialRecordStatus.PAID
        if "recorded" in normalized_event:
            return VcitaFinancialRecordStatus.RECORDED
        if "refunded" in normalized_event:
            return VcitaFinancialRecordStatus.REFUNDED
        if "cancelled" in normalized_event or "canceled" in normalized_event:
            return VcitaFinancialRecordStatus.CANCELLED
        if "issued" in normalized_event:
            return VcitaFinancialRecordStatus.ISSUED
        if "updated" in normalized_event:
            return VcitaFinancialRecordStatus.UPDATED
        state = VcitaWebhook._find_nested_value(payload, {"state", "status", "payment_state"}).lower()
        if state in {choice.value for choice in VcitaFinancialRecordStatus}:
            return state
        return VcitaFinancialRecordStatus.UNKNOWN

    @staticmethod
    def _extract_amount(payload: dict[str, Any]) -> str:
        amount = VcitaWebhook._find_nested_value(payload, {"amount", "total", "payment_balance"})
        if isinstance(amount, str):
            return amount
        return str(amount) if amount else ""

    @staticmethod
    def _is_paid_event(normalized_event: str) -> bool:
        return "payment/paid" in normalized_event or "payment/recorded" in normalized_event or normalized_event.endswith("/paid")

    @staticmethod
    def _normalized_event(event: VcitaWebhookEvent) -> str:
        return f"{event.entity}/{event.event_type}".strip("/").lower()

    @staticmethod
    def _mark_event_failed(event: VcitaWebhookEvent, message: str) -> None:
        event.status = VcitaWebhookStatus.FAILED
        event.processing_error = message
        event.save(update_fields=["status", "processing_error", "updated_at"])

    @staticmethod
    def _mark_event_unmatched(event: VcitaWebhookEvent, message: str) -> None:
        event.status = VcitaWebhookStatus.UNMATCHED
        event.processing_error = message
        event.save(update_fields=["status", "processing_error", "updated_at"])

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

    @staticmethod
    def _format_api_error(exc: VcitaAPIError) -> str:
        if exc.status_code:
            return f"vCita API error {exc.status_code}: {exc.response_body or exc}"
        return f"vCita API error: {exc.response_body or exc}"

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
