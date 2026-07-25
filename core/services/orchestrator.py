from __future__ import annotations

import logging

from django.db import transaction

from core.exceptions import (
    WebhookParsingError,
    WhatsAppAccountNotFoundError,
    OutlookAccountNotFoundError,
)
from core.models import WhatsAppAccount, WebhookLog, OutlookAccount
from core.services.message_service import MessageService
from core.services.webhook_parser import (
    ParsedWebhookEvent,
    WebhookEventType,
    WebhookParser,
    OutlookWebhookParsedEvent,
)

logger = logging.getLogger(__name__)


class WebhookOrchestrator:
    # ==================================================================
    # WhatsApp Pipeline
    @staticmethod
    def process_webhook(payload: dict, webhook_log: WebhookLog) -> None:
        # Parse ─────────────────────────────
        try:
            event: ParsedWebhookEvent = WebhookParser.parse(payload)
        except WebhookParsingError:
            logger.exception("Failed to parse webhook payload")
            return

        # Resolve WhatsApp account ────────────
        try:
            waba = WebhookOrchestrator._resolve_whatsapp_account(
                event.phone_number_id, event.waba_id
            )
        except WhatsAppAccountNotFoundError:
            logger.warning(
                "No WhatsAppAccount for phone_id=%s waba_id=%s — skipping",
                event.phone_number_id,
                event.waba_id,
            )
            return

        # Route ────────────────────────────────
        if event.event_type == WebhookEventType.MESSAGE and event.message:
            WebhookOrchestrator._handle_whatsapp_message(event, waba, webhook_log)
        elif event.event_type == WebhookEventType.STATUS and event.status:
            WebhookOrchestrator._handle_whatsapp_status(event, webhook_log)
        else:
            logger.info("Ignoring webhook event_type=%s", event.event_type)

    @staticmethod
    def _handle_whatsapp_message(event: ParsedWebhookEvent, waba: WhatsAppAccount, webhook_log: WebhookLog,) -> None:
        parsed_msg = event.message
        assert parsed_msg is not None

        try:
            # quick DB writes ───────
            with transaction.atomic():
                lead = MessageService.get_or_create_lead(
                    phone_number=parsed_msg.sender_phone,
                    name=parsed_msg.sender_name,
                )
                incoming = MessageService.save_incoming_message(lead, parsed_msg)
                MessageService.update_lead_last_message(lead, incoming)

            # dispatch heavy I/O to Celery ────────
            from core.tasks import process_message_reply

            process_message_reply.delay(
                incoming_message_id=incoming.pk,
                lead_id=lead.pk,
                waba_id=waba.pk,
                sender_phone=parsed_msg.sender_phone,
                current_message_body=parsed_msg.body,
                media_id=parsed_msg.media_id,
                media_mime_type=parsed_msg.media_mime_type,
            )
            logger.info(
                "Dispatched process_message_reply task for lead=%s incoming_msg=%s media_id=%s",
                lead.pk,
                incoming.pk,
                parsed_msg.media_id or "none",
            )
        except Exception:
            logger.exception(
                "Unhandled error in message handler for wamid=%s",
                parsed_msg.message_id,
            )

    @staticmethod
    def _handle_whatsapp_status(event: ParsedWebhookEvent, webhook_log: WebhookLog,) -> None:
        parsed_status = event.status
        assert parsed_status is not None

        try:
            from core.tasks import process_status_update
            process_status_update.delay(
                provider_message_id=parsed_status.message_id,
                new_status=parsed_status.status,
            )
            logger.info(
                "Dispatched process_status_update task for wamid=%s status=%s",
                parsed_status.message_id,
                parsed_status.status,
            )
        except Exception:
            logger.exception(
                "Error dispatching status update for wamid=%s",
                parsed_status.message_id,
            )

    # ==================================================================
    # Outlook Pipeline
    @staticmethod
    def process_outlook_webhook(payload: dict, webhook_log: WebhookLog) -> None:
        # Parse ──────────────────────────────
        try:
            event: OutlookWebhookParsedEvent = WebhookParser.outlook_parse(payload)
        except WebhookParsingError:
            logger.exception("Failed to parse Outlook webhook payload")
            return

        # Resolve Outlook account ─────────────
        try:
            outlook_account = WebhookOrchestrator._resolve_outlook_account()
        except OutlookAccountNotFoundError:
            logger.warning("No active OutlookAccount found — skipping")
            return

        # Dispatch to Celery ───────────────────
        WebhookOrchestrator._handle_outlook_mail(event, outlook_account, webhook_log)

    @staticmethod
    def _handle_outlook_mail(event: OutlookWebhookParsedEvent, outlook_account: OutlookAccount, webhook_log: WebhookLog,) -> None:
        try:
            from core.tasks import process_outlook_mail_reply
            process_outlook_mail_reply.delay(
                outlook_account_id=outlook_account.pk,
                message_id=event.message_id,
                resource=event.resource,
                webhook_log_id=webhook_log.pk,
            )
            logger.info(
                "Dispatched process_outlook_mail_reply task: msg_id=%s resource=%s",
                event.message_id,
                event.resource,
            )
        except Exception:
            logger.exception(
                "Error dispatching Outlook mail handler for message_id=%s",
                event.message_id,
            )

    # Account resolution helpers
    @staticmethod
    def _resolve_whatsapp_account(phone_number_id: str, waba_id: str) -> WhatsAppAccount:
        account = WhatsAppAccount.objects.filter(
            phone_number_id=phone_number_id,
            waba_id=waba_id,
            is_active=True,
        ).first()
        if account is None:
            raise WhatsAppAccountNotFoundError(
                f"No active WhatsAppAccount: phone_id={phone_number_id}, waba_id={waba_id}"
            )
        return account

    @staticmethod
    def _resolve_outlook_account() -> OutlookAccount:
        account = OutlookAccount.objects.filter(is_active=True).first()
        if account is None:
            raise OutlookAccountNotFoundError("No active OutlookAccount found.")
        return account


