from __future__ import annotations

import logging
import time

from celery import shared_task

from core.exceptions import (
    AIServiceError,
    MediaDownloadError,
    MetaAPIError,
    OutlookAPIError,
)

logger = logging.getLogger(__name__)

_AI_FALLBACK_REPLY = (
    "Thank you for reaching out! We're currently experiencing high demand "
    "and will respond as soon as possible. 🙏"
)

# =========================================================================
# WhatsApp: AI processing + optional image download + Meta send
@shared_task(
    bind=True,
    name="core.tasks.process_message_reply",
    max_retries=3,
    autoretry_for=(MetaAPIError, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    acks_late=True,
)
def process_message_reply(self, incoming_message_id: int, lead_id: int, waba_id: int, sender_phone: str, current_message_body: str, media_id: str = "", media_mime_type: str = "",) -> dict:
    from core.models import WhatsAppAccount
    from core.services.ai_service import AIService
    from core.services.media_service import MediaService
    from core.services.message_service import MessageService
    from core.services.meta_api import MetaAPIService
    from lead.choices import MESSAGE_STATUS
    from lead.models import Lead, Message

    logger.info(
        "Task started: process_message_reply | lead=%s msg=%s attempt=%s media=%s",
        lead_id, incoming_message_id, self.request.retries, media_id or "none",
    )

    # Re-fetch ORM objects ──────────────────────
    try:
        lead = Lead.objects.get(pk=lead_id)
        waba = WhatsAppAccount.objects.get(pk=waba_id)
        incoming_msg = Message.objects.get(pk=incoming_message_id)
    except (Lead.DoesNotExist, WhatsAppAccount.DoesNotExist, Message.DoesNotExist) as exc:
        logger.error("DB lookup failed — aborting task: %s", exc)
        return {"status": "aborted", "reason": str(exc)}

    # Download media if present ──────────────────────
    image_urls: list[str] = []
    if media_id:
        try:
            access_token = MetaAPIService._resolve_access_token(waba)
            result = MediaService.download_whatsapp_media(
                media_id=media_id,
                mime_type=media_mime_type,
                access_token=access_token,
                message=incoming_msg,
            )
            image_urls.append(result.public_url)
            logger.info(
                "Downloaded WhatsApp media: media_id=%s url=%s",
                media_id, result.public_url,
            )
        except MediaDownloadError:
            logger.exception(
                "Failed to download media media_id=%s — continuing without image",
                media_id,
            )

    # Fetch chat history ──────────────────────
    history = MessageService.get_chat_history(lead)

    # Call AI API ──────────────────────
    ai_svc = AIService()
    try:
        reply_text = ai_svc.get_reply(
            current_message=current_message_body,
            chat_history=history,
            lead=lead,
            image_urls=image_urls if image_urls else None,
        )
        draft_reply: str = reply_text.get("draft_reply", "")
    except AIServiceError as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                "AI failed. Retrying... (%s/%s)",
                self.request.retries + 1, self.max_retries,
            )
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        logger.warning(
            "AI failed after %s retries. Using fallback reply.",
            self.request.retries,
        )
        reply_text = _AI_FALLBACK_REPLY

    risk_level = reply_text.get("risk_level", "low")
    if risk_level in ("high",):
        try:
            meta_svc = MetaAPIService(waba)
            meta_svc.send_text_message(
                to=sender_phone,
                body=(
                    "Thank you for your message. "
                    "Our team is reviewing your request. "
                    "We'll get back to you shortly."
                ),
            )
        except Exception:
            logger.exception("Failed to send waiting message.")
        
        # Send message in Telegram Group for Confimration====
        history = MessageService.get_chat_history(lead)
        reply_summery = ai_svc.get_summery(chat_history=history, lead=lead)

        summary = reply_summery.get("summary", "")
        draft_reply = reply_summery.get("draft_reply", "")
        telegram_message = reply_summery.get("telegram_message", "")

        from .services.telegram_bot_service import TelegramBotService
        telegram = TelegramBotService()
        telegram.send_message(
            chat_id=8145617629,
            text=summary,
        )
        return {
            "status": "waiting_for_human_approval",
        }
    elif risk_level in ("low",):
        # Save outgoing message ──────────────────────
        outgoing = MessageService.save_outgoing_message(
            lead=lead,
            content=draft_reply,
        )

        # Send via Meta API ──────────────────────
        try:
            time.sleep(2)
            meta_svc = MetaAPIService(waba)
            meta_response = meta_svc.send_text_message(
                to=sender_phone,
                body=draft_reply,
            )
            # Link Meta wamid ──────────────────────
            wamid = MetaAPIService.extract_message_id(meta_response)
            if wamid:
                outgoing.provider_message_id = wamid
                outgoing.save(update_fields=["provider_message_id", "updated_at"])
                logger.info("Outgoing message id=%s linked to wamid=%s", outgoing.pk, wamid)
        except MetaAPIError:
            if self.request.retries >= self.max_retries:
                logger.exception(
                    "Meta API failed after %s retries for lead=%s msg=%s",
                    self.request.retries, lead_id, outgoing.pk,
                )
                outgoing.status = MESSAGE_STATUS.FAILED
                outgoing.error_message = "Meta API send failed after retries"
                outgoing.save(update_fields=["status", "error_message", "updated_at"])
                return {"status": "failed", "outgoing_message_id": outgoing.pk}
            else:
                raise  # autoretry handles it

        logger.info("Task complete: process_message_reply | lead=%s", lead_id)
        return {
            "status": "success",
            "outgoing_message_id": outgoing.pk,
            "wamid": wamid if 'wamid' in dir() else "",
            "image_urls": image_urls,
        }

# WhatsApp: Status update
@shared_task(
    bind=True,
    name="core.tasks.process_status_update",
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
    acks_late=True,
)
def process_status_update(self, provider_message_id: str, new_status: str) -> dict:
    from core.services.message_service import MessageService

    logger.info(
        "Task started: process_status_update | wamid=%s status=%s attempt=%s",
        provider_message_id, new_status, self.request.retries,
    )

    updated = MessageService.update_message_status(
        provider_message_id=provider_message_id,
        new_status=new_status,
    )

    result_status = "updated" if updated else "not_found"
    logger.info(
        "Task complete: process_status_update | wamid=%s result=%s",
        provider_message_id, result_status,
    )
    return {"status": result_status, "wamid": provider_message_id}

# =========================================================================


# =========================================================================
# Outlook: Fetch email, AI reply, send threaded response
@shared_task(
    bind=True,
    name="core.tasks.process_outlook_mail_reply",
    max_retries=3,
    autoretry_for=(OutlookAPIError, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    acks_late=True,
)
def process_outlook_mail_reply(self, outlook_account_id: int, message_id: str, resource: str, webhook_log_id: int,) -> dict:
    from core.models import OutlookAccount
    from core.services.ai_service import AIService
    from core.services.media_service import MediaService
    from core.services.message_service import MessageService
    from core.services.outlook_api import OutlookAPIService
    from lead.choices import MESSAGE_STATUS

    logger.info(
        "Task started: process_outlook_mail_reply | msg_id=%s attempt=%s",
        message_id, self.request.retries,
    )

    # Re-fetch Outlook account ───────────────────────
    try:
        outlook_account = OutlookAccount.objects.get(pk=outlook_account_id)
    except OutlookAccount.DoesNotExist as exc:
        logger.error("OutlookAccount id=%s not found — aborting", outlook_account_id)
        return {"status": "aborted", "reason": str(exc)}

    # Extract user_id from resource ───────────────────────
    outlook_svc = OutlookAPIService(outlook_account)
    try:
        user_id = OutlookAPIService.extract_user_id_from_resource(resource)
    except OutlookAPIError as exc:
        logger.error("Cannot extract user_id: %s", exc)
        return {"status": "aborted", "reason": str(exc)}

    # Fetch full email message ───────────────────────
    email_data = outlook_svc.fetch_message(user_id, message_id)

    sender_info = email_data.get("from", {}).get("emailAddress", {})
    sender_email = sender_info.get("address", "")
    sender_name = sender_info.get("name", "")
    subject = email_data.get("subject", "")
    body_obj = email_data.get("body", {})
    body_content = body_obj.get("content", "")
    body_type = body_obj.get("contentType", "text")
    conversation_id = email_data.get("conversationId", "")
    internet_message_id = email_data.get("internetMessageId", "")
    has_attachments = email_data.get("hasAttachments", False)

    # Ignore emails sent by our own business mailbox (avoid reply loops)
    if sender_email.lower() == outlook_account.business_mail.lower():
        logger.info("Ignoring self-sent email from %s", sender_email)
        return {"status": "skipped", "reason": "self_sent"}

    # Strip HTML to plain text for AI
    if body_type.lower() == "html":
        body_text = OutlookAPIService.strip_html_to_text(body_content)
        html_content = body_content
    else:
        body_text = body_content
        html_content = ""

    # Get/create Lead by email ───────────────────────
    lead = MessageService.get_or_create_email_lead(
        email=sender_email,
        name=sender_name,
    )

    # Get/create Conversation ───────────────────────
    conversation = MessageService.get_or_create_conversation(
        lead=lead,
        conversation_id=conversation_id,
        subject=subject,
    )

    # Save incoming email ───────────────────────
    incoming = MessageService.save_email_message(
        lead=lead,
        conversation=conversation,
        subject=subject,
        body_text=body_text,
        html_content=html_content,
        provider_message_id=message_id,
        internet_message_id=internet_message_id,
        conversation_message_id=conversation_id,
        raw_payload=email_data,
    )
    MessageService.update_lead_last_message(lead, incoming)

    # Download attachments (images only → AI) ───────────────────────
    image_urls: list[str] = []
    if has_attachments:
        try:
            attachments = outlook_svc.fetch_attachments(user_id, message_id)
            for att in attachments:
                try:
                    result = MediaService.save_outlook_attachment(
                        attachment=att,
                        message=incoming,
                    )
                    if result and MediaService.is_image_mime(att.get("contentType", "")):
                        image_urls.append(result.public_url)
                except MediaDownloadError:
                    logger.exception(
                        "Failed to save attachment '%s' — skipping",
                        att.get("name", "unknown"),
                    )
        except OutlookAPIError:
            logger.exception(
                "Failed to fetch attachments for msg_id=%s — continuing without",
                message_id,
            )

    # Fetch conversation history (threaded) ───────────────────────
    history = MessageService.get_conversation_history(conversation)

    # Call AI API ───────────────────────
    try:
        ai_svc = AIService()
        reply_text = ai_svc.get_reply(
            current_message=body_text,
            chat_history=history,
            lead=lead,
            image_urls=image_urls if image_urls else None,
        )
        draft_reply: str = reply_text.get("draft_reply", "")
    except AIServiceError as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                "AI failed for Outlook. Retrying... (%s/%s)",
                self.request.retries + 1, self.max_retries,
            )
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        logger.warning(
            "AI failed after %s retries. Using fallback reply.",
            self.request.retries,
        )
        draft_reply = _AI_FALLBACK_REPLY

    # Save outgoing email reply ───────────────────────
    reply_html = OutlookAPIService.text_to_html(draft_reply)
    outgoing = MessageService.save_outgoing_email(
        lead=lead,
        conversation=conversation,
        subject=subject,
        content=draft_reply,
        html_content=reply_html,
    )

    # Send reply in the same thread ───────────────────────
    try:
        outlook_svc.send_reply(
            user_id=user_id,
            message_id=message_id,
            body_html=reply_html,
        )
        logger.info(
            "Outlook reply sent for email id=%s lead=%s conv=%s",
            message_id, lead.pk, conversation.pk,
        )
    except OutlookAPIError:
        if self.request.retries >= self.max_retries:
            logger.exception(
                "Graph API reply failed after %s retries for msg_id=%s",
                self.request.retries, message_id,
            )
            outgoing.status = MESSAGE_STATUS.FAILED
            outgoing.error_message = "Graph API reply send failed after retries"
            outgoing.save(update_fields=["status", "error_message", "updated_at"])
            return {"status": "failed", "outgoing_message_id": outgoing.pk}
        else:
            raise  # autoretry handles it

    # Update conversation last_message_at
    from django.utils import timezone as tz
    conversation.last_message_at = tz.now()
    conversation.save(update_fields=["last_message_at", "updated_at"])

    logger.info("Task complete: process_outlook_mail_reply | msg_id=%s", message_id)
    return {
        "status": "success",
        "outgoing_message_id": outgoing.pk,
        "lead_id": lead.pk,
        "image_urls": image_urls,
    }

# =========================================================================

