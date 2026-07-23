from __future__ import annotations
import logging
from celery import shared_task
from core.exceptions import AIServiceError, MetaAPIError
import time
logger = logging.getLogger(__name__)
from core.models import WhatsAppAccount
from core.services.ai_service import AIService
from core.services.message_service import MessageService
from core.services.meta_api import MetaAPIService
from lead.choices import MESSAGE_STATUS
from lead.models import Lead

# Fallback when AI is unreachable — ensures we never leave the user hanging
_AI_FALLBACK_REPLY = (
    "Thank you for reaching out! We're currently experiencing high demand "
    "and will respond as soon as possible. 🙏"
)


# =========================================================================
# Task 1 — AI processing + Meta send (the heavy path)
@shared_task(
    bind=True, name="core.tasks.process_message_reply", max_retries=3, autoretry_for=(MetaAPIError, ConnectionError, TimeoutError), retry_backoff=True, retry_backoff_max=60, retry_jitter=True, acks_late=True,
    # autoretry_for=(AIServiceError, MetaAPIError, ConnectionError, TimeoutError),
)
def process_message_reply(self, incoming_message_id: int, lead_id: int, waba_id: int, sender_phone: str, current_message_body: str,) -> dict:
    logger.info(
        "Task started: process_message_reply | lead=%s incoming_msg=%s attempt=%s",
        lead_id,
        incoming_message_id,
        self.request.retries,
    )

    # ── Re-fetch ORM objects from serialised IDs ────────────────────
    try:
        lead = Lead.objects.get(pk=lead_id)
        waba = WhatsAppAccount.objects.get(pk=waba_id)
    except (Lead.DoesNotExist, WhatsAppAccount.DoesNotExist) as exc:
        logger.error("DB lookup failed — aborting task: %s", exc)
        return {"status": "aborted", "reason": str(exc)}

    # ── 1. Fetch chat history ───────────────────────────────────────
    history = MessageService.get_chat_history(lead)

    # ── 2. Call AI API ──────────────────────────────────────────────
    try:
        ai_svc = AIService()
        reply_text = ai_svc.get_reply(
            current_message=current_message_body,
            chat_history=history,
            lead=lead,
        )
    except AIServiceError as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                "AI failed. Retrying... (%s/%s)",
                self.request.retries + 1,
                self.max_retries,
            )
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        logger.warning(
            "AI failed after %s retries. Using fallback reply.",
            self.request.retries,
        )
        reply_text = _AI_FALLBACK_REPLY

    # ── 3. Save outgoing message ────────────────────────────────────
    outgoing = MessageService.save_outgoing_message(
        lead=lead,
        content=reply_text,
    )

    # ── 4. Send via Meta API ────────────────────────────────────────
    try:
        time.sleep(2)
        meta_svc = MetaAPIService(waba)
        meta_response = meta_svc.send_text_message(
            to=sender_phone,
            body=reply_text,
        )
        # ── 5. Link Meta wamid to our outgoing message ──────────────
        wamid = MetaAPIService.extract_message_id(meta_response)
        if wamid:
            outgoing.system_id = wamid
            outgoing.save(update_fields=["system_id", "updated_at"])
            logger.info(
                "Outgoing message id=%s linked to wamid=%s", outgoing.pk, wamid
            )
    except MetaAPIError:
        if self.request.retries >= self.max_retries:
            logger.exception(
                "Meta API failed after %s retries for lead=%s msg=%s",
                self.request.retries,
                lead_id,
                outgoing.pk,
            )
            outgoing.status = MESSAGE_STATUS.FAILED
            outgoing.error_message = "Meta API send failed after retries"
            outgoing.save(update_fields=["status", "error_message", "updated_at"])
            return {"status": "failed", "outgoing_message_id": outgoing.pk}
        else:
            raise  # Let Celery's autoretry handle it

    logger.info("Task complete: process_message_reply | lead=%s", lead_id)
    return {
        "status": "success",
        "outgoing_message_id": outgoing.pk,
        "wamid": wamid,
    }
# =========================================================================


# =========================================================================
# Task 2 — Status update (lightweight but keeps the webhook instant)
@shared_task(
    bind=True, name="core.tasks.process_status_update", max_retries=2, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=30, retry_jitter=True, acks_late=True,
)
def process_status_update(self, message_system_id: str, new_status: str,) -> dict:
    from core.services.message_service import MessageService

    logger.info(
        "Task started: process_status_update | wamid=%s status=%s attempt=%s",
        message_system_id,
        new_status,
        self.request.retries,
    )

    updated = MessageService.update_message_status(
        system_id=message_system_id,
        new_status=new_status,
    )

    result_status = "updated" if updated else "not_found"
    logger.info(
        "Task complete: process_status_update | wamid=%s result=%s",
        message_system_id,
        result_status,
    )
    return {"status": result_status, "wamid": message_system_id}
# =========================================================================


# =========================================================================
# Task 3 — Outlood Message Hanlde and AI Reply
@shared_task(
    bind=True, name="core.tasks.process_outlook_mail_reply", max_retries=3, autoretry_for=(MetaAPIError, ConnectionError, TimeoutError), retry_backoff=True, retry_backoff_max=60, retry_jitter=True, acks_late=True,
    # autoretry_for=(AIServiceError, MetaAPIError, ConnectionError, TimeoutError),
)
def process_outlook_mail_reply(self, event, outlood, webhook_log) -> dict:
    logger.info(
        "Task started: process_message_reply | lead=%s incoming_msg=%s attempt=%s",
        event.message_id,
        self.request.retries,
    )

    # ── Re-fetch ORM objects from serialised IDs ────────────────────
    try:
        lead = Lead.objects.get(pk=lead_id)
        waba = WhatsAppAccount.objects.get(pk=waba_id)
    except (Lead.DoesNotExist, WhatsAppAccount.DoesNotExist) as exc:
        logger.error("DB lookup failed — aborting task: %s", exc)
        return {"status": "aborted", "reason": str(exc)}

    # ── 1. Fetch chat history ───────────────────────────────────────
    history = MessageService.get_chat_history(lead)

    # ── 2. Call AI API ──────────────────────────────────────────────
    try:
        ai_svc = AIService()
        reply_text = ai_svc.get_reply(
            current_message=current_message_body,
            chat_history=history,
            lead=lead,
        )
    except AIServiceError as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                "AI failed. Retrying... (%s/%s)",
                self.request.retries + 1,
                self.max_retries,
            )
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        logger.warning(
            "AI failed after %s retries. Using fallback reply.",
            self.request.retries,
        )
        reply_text = _AI_FALLBACK_REPLY

    # ── 3. Save outgoing message ────────────────────────────────────
    outgoing = MessageService.save_outgoing_message(
        lead=lead,
        content=reply_text,
    )

    # ── 4. Send via Meta API ────────────────────────────────────────
    try:
        time.sleep(2)
        meta_svc = MetaAPIService(waba)
        meta_response = meta_svc.send_text_message(
            to=sender_phone,
            body=reply_text,
        )
        # ── 5. Link Meta wamid to our outgoing message ──────────────
        wamid = MetaAPIService.extract_message_id(meta_response)
        if wamid:
            outgoing.system_id = wamid
            outgoing.save(update_fields=["system_id", "updated_at"])
            logger.info(
                "Outgoing message id=%s linked to wamid=%s", outgoing.pk, wamid
            )
    except MetaAPIError:
        if self.request.retries >= self.max_retries:
            logger.exception(
                "Meta API failed after %s retries for lead=%s msg=%s",
                self.request.retries,
                lead_id,
                outgoing.pk,
            )
            outgoing.status = MESSAGE_STATUS.FAILED
            outgoing.error_message = "Meta API send failed after retries"
            outgoing.save(update_fields=["status", "error_message", "updated_at"])
            return {"status": "failed", "outgoing_message_id": outgoing.pk}
        else:
            raise  # Let Celery's autoretry handle it

    logger.info("Task complete: process_message_reply | lead=%s", lead_id)
    return {
        "status": "success",
        "outgoing_message_id": outgoing.pk,
        "wamid": wamid,
    }
# =========================================================================
