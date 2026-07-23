from __future__ import annotations
import logging
from django.db import transaction
from core.exceptions import (
    AIServiceError,
    MetaAPIError,
    WebhookParsingError,
    WhatsAppAccountNotFoundError,
    OutlookAccountNotFoundError
)
from core.models import WhatsAppAccount, WebhookLog, OutlookAccount
from core.services.ai_service import AIService
from core.services.message_service import MessageService
from core.services.meta_api import MetaAPIService
from core.services.webhook_parser import ParsedWebhookEvent, WebhookEventType, WebhookParser, OutlookWebhookParsedEvent

logger = logging.getLogger(__name__)
import time

# Fallback when AI is unreachable — ensures we never leave the user hanging
_AI_FALLBACK_REPLY = (
    "Thank you for reaching out! We're currently experiencing high demand "
    "and will respond as soon as possible. 🙏"
)


class WebhookOrchestrator:
    @staticmethod
    def process_webhook(payload: dict, webhook_log: WebhookLog) -> None:
        # 1. Parse ─────────────────────────────────────────────────────
        try:
            event: ParsedWebhookEvent = WebhookParser.parse(payload)
        except WebhookParsingError:
            logger.exception("Failed to parse webhook payload")
            return

        # 2. Resolve WhatsApp account ──────────────────────────────────
        try:
            waba = WebhookOrchestrator._resolve_account(
                event.phone_number_id, event.waba_id
            )
        except WhatsAppAccountNotFoundError:
            logger.warning(
                "No WhatsAppAccount for phone_id=%s waba_id=%s — skipping",
                event.phone_number_id,
                event.waba_id,
            )
            return

        # 3. Route ─────────────────────────────────────────────────────
        if event.event_type == WebhookEventType.MESSAGE and event.message:
            WebhookOrchestrator._handle_message(event, waba, webhook_log)
        elif event.event_type == WebhookEventType.STATUS and event.status:
            WebhookOrchestrator._handle_status(event, webhook_log)
        else:
            logger.info("Ignoring webhook event_type=%s", event.event_type)

    @staticmethod
    def process_outlook_webhook(payload: dict, webhook_log: WebhookLog) -> None:
        # 1. Parse ─────────────────────────────────────────────────────
        try:
            event: OutlookWebhookParsedEvent = WebhookParser.outlook_parse(payload)
        except WebhookParsingError:
            logger.exception("Failed to parse webhook payload")
            return
        
        # 2. Resolve WhatsApp account ──────────────────────────────────
        try:
            outlood = WebhookOrchestrator._resolve_outlood_account()
        except OutlookAccountNotFoundError:
            logger.warning(
                "No Outlook Account for phone_id=%s waba_id=%s — skipping",
                event.phone_number_id,
                event.waba_id,
            )
            return

        WebhookOrchestrator._outlood_mail_handle(event, outlood, webhook_log)


    # ------------------------------------------------------------------
    # Message flow
    @staticmethod
    def _outlood_mail_handle(event: OutlookWebhookParsedEvent, outlood: OutlookAccount, webhook_log: WebhookLog,) -> None:
        message_id = event.message_id
        assert message_id is not None
        try:
            print("ok")
            # ── Synchronous: quick DB writes ────────────────────────────
            # lead = MessageService.get_or_create_lead(
            #     phone_number=parsed_msg.sender_phone,
            #     name=parsed_msg.sender_name,
            # )
            # incoming = MessageService.save_incoming_message(lead, parsed_msg)
            # MessageService.update_lead_last_message(lead, incoming)

            # # ── Async: dispatch heavy I/O to Celery ─────────────────────
            # from core.tasks import process_outlook_mail_reply
            # ss = process_outlook_mail_reply.delay(
            #     event=event,
            #     outlood=outlood,
            #     webhook_log=webhook_log
            # )
            # logger.info(
            #     "Dispatched outlook reply task",
            #     # "Starting process outlook reply task for lead=%s incoming_msg=%s",
            #     # lead.pk,
            #     # incoming.pk,
            # )
        except Exception:
            logger.exception(
                "Unhandled error in message handler for wamid",
                # "Unhandled error in message handler for wamid=%s",
                # parsed_msg.message_id,
            )
    
    @staticmethod
    def _handle_message(event: ParsedWebhookEvent, waba: WhatsAppAccount, webhook_log: WebhookLog,) -> None:
        parsed_msg = event.message
        assert parsed_msg is not None

        try:
            # ── Synchronous: quick DB writes ────────────────────────────
            with transaction.atomic():
                lead = MessageService.get_or_create_lead(
                    phone_number=parsed_msg.sender_phone,
                    name=parsed_msg.sender_name,
                )
                incoming = MessageService.save_incoming_message(lead, parsed_msg)
                MessageService.update_lead_last_message(lead, incoming)

            # ── Async: dispatch heavy I/O to Celery ─────────────────────
            from core.tasks import process_message_reply
            ss = process_message_reply.delay(
                incoming_message_id=incoming.pk,
                lead_id=lead.pk,
                waba_id=waba.pk,
                sender_phone=parsed_msg.sender_phone,
                current_message_body=parsed_msg.body,
            )
            print("ss: ", ss)
            logger.info(
                "Dispatched process_message_reply task for lead=%s incoming_msg=%s",
                lead.pk,
                incoming.pk,
            )
        except Exception:
            logger.exception(
                "Unhandled error in message handler for wamid=%s",
                parsed_msg.message_id,
            )

    # ------------------------------------------------------------------
    # Status flow  (Celery dispatch)
    @staticmethod
    def _handle_status(event: ParsedWebhookEvent, webhook_log: WebhookLog,) -> None:
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

    # ------------------------------------------------------------------
    # Helpers
    @staticmethod
    def _resolve_account(phone_number_id: str, waba_id: str) -> WhatsAppAccount:
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

    def _resolve_outlood_account() -> OutlookAccount:
        account = OutlookAccount.objects.first()
        if account is None:
            raise WhatsAppAccountNotFoundError(
                f"No active Outlook Account Found."
            )
        return account


