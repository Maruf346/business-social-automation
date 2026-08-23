from __future__ import annotations

import logging
import time

from celery import chain, shared_task

from core.exceptions import (
    AIServiceError,
    MediaDownloadError,
    MetaAPIError,
    OutlookAPIError,
)
from core.services.ai_service import AIService
from core.services.message_service import MessageService
from core.services.outlook_api import OutlookAPIService, OutlookAPIError
from core.models import OutlookAccount
from intake.models import IntakeRequest, IntakeSource, OutboundAction, OutboundActionStatus, OutboundActionType, RiskLevel
from intake.outbound import ClientOutboundService
from intake.services import IntakeStateService
from intake.telegram_workflow import TelegramWorkflowService
from lead.models import Lead, Conversation, Message
from core.services.media_service import MediaService, MediaDownloadError
from lead.choices import MESSAGE_STATUS, SEND_BY

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
    from core.services.meta_api import MetaAPIService

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
    intake = IntakeStateService.get_or_create_active_intake(lead=lead)
    IntakeStateService.update_channel_context(
        intake=intake,
        source=IntakeSource.WHATSAPP,
        last_incoming_message=incoming_msg,
        whatsapp_account=waba,
    )

    if intake.assigned_artist_id:
        TelegramWorkflowService().send_artist_update(
            intake=intake,
            text=current_message_body,
            media_items=[{"type": "image", "url": url, "file_name": "whatsapp-media"} for url in image_urls],
        )
        return {
            "status": "forwarded_to_assigned_artist",
            "intake_id": intake.pk,
            "artist_id": intake.assigned_artist_id,
        }

    existing_db_state = IntakeStateService.build_existing_db_state(lead=lead, intake=intake)

    # Call AI API ──────────────────────
    ai_svc = AIService()
    try:
        reply_text = ai_svc.get_reply(
            current_message=current_message_body,
            chat_history=history,
            lead=lead,
            image_urls=image_urls if image_urls else None,
            existing_db_state=existing_db_state,
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
        reply_text = {
            "draft_reply": _AI_FALLBACK_REPLY,
            "risk_level": "low",
        }
        draft_reply = _AI_FALLBACK_REPLY

    ai_analysis = IntakeStateService.record_ai_response(
        intake=intake,
        lead=lead,
        message=incoming_msg,
        response=reply_text,
        endpoint="analyze",
    )

    risk_level = ai_analysis.risk_level
    if risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.UNKNOWN):
        try:
            ClientOutboundService.send_intake_reply(
                intake=intake,
                text=(
                    "Thank you for your message. "
                    "Our team is reviewing your request. "
                    "We'll get back to you shortly."
                ),
                action_type=OutboundActionType.WAITING_MESSAGE,
            )
        except Exception:
            logger.exception("Failed to send waiting message.")
        
        # Send message in Telegram Group for Confimration====
        history = MessageService.get_chat_history(lead)
        existing_db_state = IntakeStateService.build_existing_db_state(
            lead=lead,
            intake=intake,
            latest_analysis=ai_analysis,
        )
        reply_summery = ai_svc.get_summery(
            chat_history=history,
            lead=lead,
            current_message=current_message_body,
            image_urls=image_urls if image_urls else None,
            existing_db_state=existing_db_state,
        )

        summary = reply_summery.get("summary", "")

        TelegramWorkflowService().send_review_card(intake=intake, summary=summary)
        return {
            "status": "waiting_for_human_approval",
            "intake_id": intake.pk,
            "ai_analysis_id": ai_analysis.pk,
        }
    elif risk_level in ("low",):
        # Save outgoing message ──────────────────────
        outgoing = None

        # Send via Meta API ──────────────────────
        try:
            time.sleep(2)
            outgoing = ClientOutboundService.send_intake_reply(
                intake=intake,
                text=draft_reply,
                action_type=OutboundActionType.AI_AUTO_REPLY,
                send_by=SEND_BY.AI,
            )
            # Link Meta wamid ──────────────────────
        except MetaAPIError:
            if self.request.retries >= self.max_retries:
                logger.exception(
                    "Meta API failed after %s retries for lead=%s msg=%s",
                    self.request.retries, lead_id, incoming_message_id,
                )
                return {"status": "failed", "intake_id": intake.pk}
            else:
                raise  # autoretry handles it

        logger.info("Task complete: process_message_reply | lead=%s", lead_id)
        return {
            "status": "success",
            "outgoing_message_id": outgoing.pk if outgoing else None,
            "wamid": outgoing.provider_message_id if outgoing and outgoing.provider_message_id else "",
            "image_urls": image_urls,
            "intake_id": intake.pk,
            "ai_analysis_id": ai_analysis.pk,
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
from celery.utils.log import get_task_logger
logger = get_task_logger(__name__)

# MAIN TASK: Start the Pipeline
@shared_task(name="core.tasks.process_outlook_mail_reply")
def process_outlook_mail_reply(outlook_account_id: int, message_id: str, resource: str, webhook_log_id: int):
    workflow = chain(
        step1_fetch_and_save_email.s(outlook_account_id, message_id, resource, webhook_log_id),
        step2_generate_ai_reply.s(),
        step3_send_outlook_reply.s()
    )
    workflow.apply_async()
    logger.info("Pipeline triggered for message_id=%s", message_id)

# STAGE 1: Fetch Email, Extract Data & Save Incoming
@shared_task(
    bind=True, name="core.tasks.step1_fetch_and_save_email",
    max_retries=3, autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True, retry_backoff_max=60, retry_jitter=True, acks_late=True
)
def step1_fetch_and_save_email(self, outlook_account_id: int, message_id: str, resource: str, webhook_log_id: int) -> dict:    
    logger.info("Stage 1 started: Fetch & Save | msg_id=%s attempt=%s", message_id, self.request.retries)

    if Message.objects.filter(provider_message_id=message_id).exists():
        logger.info("Message %s already processed. Skipping duplicate webhook.", message_id)
        return {"pipeline_status": "skipped", "reason": "already_processed"}

    try:
        outlook_account = OutlookAccount.objects.get(pk=outlook_account_id)
    except OutlookAccount.DoesNotExist as exc:
        logger.error("OutlookAccount id=%s not found — aborting", outlook_account_id)
        return {"pipeline_status": "aborted", "reason": str(exc)}

    outlook_svc = OutlookAPIService(outlook_account)
    try:
        user_id = OutlookAPIService.extract_user_id_from_resource(resource)
    except OutlookAPIError as exc:
        logger.error("Cannot extract user_id: %s", exc)
        return {"pipeline_status": "aborted", "reason": str(exc)}

    # Fetch full email message
    try:
        email_data = outlook_svc.fetch_message(user_id, message_id)
    except OutlookAPIError as exc:
        # ErrorItemNotFound ফিক্স (Deleted বা Missing মেইলের ক্ষেত্রে abort করা)
        if "ErrorItemNotFound" in str(exc) or getattr(exc, 'status_code', None) == 404:
            logger.warning("Message %s not found in Outlook (might be deleted/moved). Aborting pipeline.", message_id)
            return {"pipeline_status": "aborted", "reason": "ErrorItemNotFound"}
        
        # অন্য কোনো API Error হলে retry করবে
        raise self.retry(exc=exc)

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

    # Ignore self-sent emails
    if sender_email.lower() == outlook_account.business_mail.lower():
        logger.info("Ignoring self-sent email from %s", sender_email)
        return {"pipeline_status": "skipped", "reason": "self_sent"}

    # Strip HTML to plain text
    if body_type.lower() == "html":
        body_text = OutlookAPIService.strip_html_to_text(body_content)
        html_content = body_content
    else:
        body_text = body_content
        html_content = ""

    # DB Operations
    lead = MessageService.get_or_create_email_lead(email=sender_email, name=sender_name)
    conversation = MessageService.get_or_create_conversation(
        lead=lead, conversation_id=conversation_id, subject=subject
    )
    incoming = MessageService.save_email_message(
        lead=lead, conversation=conversation, subject=subject,
        body_text=body_text, html_content=html_content,
        provider_message_id=message_id, internet_message_id=internet_message_id,
        conversation_message_id=conversation_id, raw_payload=email_data,
    )
    MessageService.update_lead_last_message(lead, incoming)

    # Download attachments
    image_urls: list[str] = []
    if has_attachments:
        try:
            attachments = outlook_svc.fetch_attachments(user_id, message_id)
            for att in attachments:
                try:
                    result = MediaService.save_outlook_attachment(attachment=att, message=incoming)
                    if result and MediaService.is_image_mime(att.get("contentType", "")):
                        image_urls.append(result.public_url)
                except MediaDownloadError:
                    logger.exception("Failed to save attachment '%s' — skipping", att.get("name", "unknown"))
        except OutlookAPIError:
            logger.exception("Failed to fetch attachments for msg_id=%s — continuing without", message_id)

    return {
        "pipeline_status": "continue",
        "lead_id": lead.pk,
        "conversation_id": conversation.pk,
        "incoming_text": body_text,
        "subject": subject,
        "user_id": user_id,
        "message_id": message_id,
        "image_urls": image_urls,
        "outlook_account_id": outlook_account_id
    }

# STAGE 2: Generate AI Reply & Save Draft
@shared_task(
    bind=True,
    name="core.tasks.step2_generate_ai_reply",
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    acks_late=True,
)
def step2_generate_ai_reply(self, pipeline_data: dict) -> dict:
    if pipeline_data.get("pipeline_status") != "continue":
        logger.info("Stage 2 skipped due to pipeline status: %s", pipeline_data.get("pipeline_status"))
        return pipeline_data

    lead_id = pipeline_data["lead_id"]
    conversation_id = pipeline_data["conversation_id"]
    
    lead = Lead.objects.get(pk=lead_id)
    conversation = Conversation.objects.get(pk=conversation_id)
    history = MessageService.get_conversation_history(conversation)
    incoming_message = Message.objects.filter(
        provider_message_id=pipeline_data["message_id"],
        lead=lead,
        conversation=conversation,
    ).first()
    intake = IntakeStateService.get_or_create_active_intake(lead=lead, conversation=conversation)
    IntakeStateService.update_channel_context(
        intake=intake,
        source=IntakeSource.OUTLOOK,
        last_incoming_message=incoming_message,
        outlook_account=OutlookAccount.objects.get(pk=pipeline_data["outlook_account_id"]),
        outlook_user_id=pipeline_data["user_id"],
    )

    if intake.assigned_artist_id:
        TelegramWorkflowService().send_artist_update(
            intake=intake,
            text=pipeline_data["incoming_text"],
            media_items=[{"type": "image", "url": url, "file_name": "outlook-image"} for url in pipeline_data.get("image_urls", [])],
        )
        pipeline_data["pipeline_status"] = "forwarded_to_assigned_artist"
        pipeline_data["intake_id"] = intake.pk
        return pipeline_data

    existing_db_state = IntakeStateService.build_existing_db_state(lead=lead, intake=intake)

    logger.info("Stage 2 started: AI Generate | conv_id=%s attempt=%s", conversation_id, self.request.retries)

    try:
        ai_svc = AIService()
        reply_text = ai_svc.get_reply(
            current_message=pipeline_data["incoming_text"],
            chat_history=history,
            lead=lead,
            image_urls=pipeline_data.get("image_urls") or None,
            existing_db_state=existing_db_state,
        )
        draft_reply: str = reply_text.get("draft_reply", "")
    except Exception as exc: # Replace Exception with AIServiceError if appropriately imported
        if self.request.retries < self.max_retries:
            logger.warning("AI failed for Outlook. Retrying... (%s/%s)", self.request.retries + 1, self.max_retries)
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        
        logger.warning("AI failed after %s retries. Using fallback reply.", self.request.retries)
        draft_reply = getattr(self, '_AI_FALLBACK_REPLY', "Thank you for your message. We will get back to you shortly.")
        reply_text = {
            "draft_reply": draft_reply,
            "risk_level": "low",
        }

    ai_analysis = IntakeStateService.record_ai_response(
        intake=intake,
        lead=lead,
        message=incoming_message,
        response=reply_text,
        endpoint="analyze",
    )

    risk_level = ai_analysis.risk_level
    pipeline_data["risk_level"] = risk_level
    pipeline_data["intake_id"] = intake.pk
    pipeline_data["ai_analysis_id"] = ai_analysis.pk
    if risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.UNKNOWN):
        # Prepare the Client Summery====
        existing_db_state = IntakeStateService.build_existing_db_state(
            lead=lead,
            intake=intake,
            latest_analysis=ai_analysis,
        )
        reply_summery = ai_svc.get_summery(
            chat_history=history,
            lead=lead,
            current_message=pipeline_data["incoming_text"],
            image_urls=pipeline_data.get("image_urls") or None,
            existing_db_state=existing_db_state,
        )
        summary = reply_summery.get("summary", "")
        # draft_reply = reply_summery.get("draft_reply", "")
        # telegram_message = reply_summery.get("telegram_message", "")

        pipeline_data["summary"] = summary
        # pipeline_data["pipeline_status"] = "stop"
        return pipeline_data

    # Save outgoing draft
    reply_html = OutlookAPIService.text_to_html(draft_reply)
    outgoing = MessageService.save_outgoing_email(
        lead=lead,
        conversation=conversation,
        subject=pipeline_data["subject"],
        content=draft_reply,
        html_content=reply_html,
    )

    pipeline_data["outgoing_message_id"] = outgoing.pk
    pipeline_data["reply_html"] = reply_html
    return pipeline_data

# STAGE 3: Send Outlook Reply
@shared_task(
    bind=True,
    name="core.tasks.step3_send_outlook_reply",
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    acks_late=True,
)
def step3_send_outlook_reply(self, pipeline_data: dict) -> dict:
    from django.utils import timezone as tz
    if pipeline_data.get("pipeline_status") != "continue":
        logger.info("Stage 3 skipped due to pipeline status: %s", pipeline_data.get("pipeline_status"))
        return pipeline_data

    outlook_account = OutlookAccount.objects.get(pk=pipeline_data["outlook_account_id"])
    outlook_svc = OutlookAPIService(outlook_account)
    user_id = pipeline_data["user_id"]
    message_id = pipeline_data["message_id"]

    logger.info("Stage 3 started: Send Reply | msg_id=%s attempt=%s", message_id, self.request.retries)

    risk_level = pipeline_data.get("risk_level", "low")
    if risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.UNKNOWN):
        summary = pipeline_data.get("summary")
        try:
            ClientOutboundService.send_intake_reply(
                intake=IntakeRequest.objects.get(pk=pipeline_data["intake_id"]),
                text=(
                    "Thank you for your message. "
                    "Our team is reviewing your request. "
                    "We'll get back to you shortly."
                ),
                action_type=OutboundActionType.WAITING_MESSAGE,
            )
            logger.info("Outlook reply sent for email id=%s", message_id)
        except Exception:
            logger.exception("Failed to send waiting message.")

        TelegramWorkflowService().send_review_card(
            intake=IntakeRequest.objects.get(pk=pipeline_data["intake_id"]),
            summary=summary,
        )
        logger.info("Waiting for human approval.")
        return {
            "status": "success",
            "message": "waiting_for_human_approval",
            "lead_id": pipeline_data["lead_id"],
            "image_urls": pipeline_data.get("image_urls", []),
            "intake_id": pipeline_data.get("intake_id"),
            "ai_analysis_id": pipeline_data.get("ai_analysis_id"),
        }
    elif risk_level == "low":
        # Load Outgoing instance to update status on failure
        outgoing_id = pipeline_data["outgoing_message_id"]
        outgoing = Message.objects.get(pk=outgoing_id) 
        intake = IntakeRequest.objects.get(pk=pipeline_data["intake_id"])
        outbound_action = OutboundAction.objects.create(
            intake=intake,
            lead=intake.lead,
            conversation=intake.conversation,
            message=outgoing,
            source=IntakeSource.OUTLOOK,
            action_type=OutboundActionType.AI_AUTO_REPLY,
            text=outgoing.content or "",
        )

        try:
            outlook_svc.send_reply(
                user_id=user_id,
                message_id=message_id,
                body_html=pipeline_data["reply_html"],
            )
            logger.info("Outlook reply sent for email id=%s", message_id)
        except OutlookAPIError as exc:
            outbound_action.status = OutboundActionStatus.FAILED
            outbound_action.error_message = str(exc)
            outbound_action.save(update_fields=["status", "error_message", "updated_at"])
            if self.request.retries >= self.max_retries:
                logger.exception("Graph API reply failed after %s retries for msg_id=%s", self.request.retries, message_id)
                outgoing.status = MESSAGE_STATUS.FAILED
                outgoing.error_message = "Graph API reply send failed after retries"
                outgoing.save(update_fields=["status", "error_message", "updated_at"])
                return {"status": "failed", "outgoing_message_id": outgoing.pk}
            else:
                raise self.retry(exc=exc) # Handled by autoretry

        outbound_action.status = OutboundActionStatus.SENT
        outbound_action.sent_at = tz.now()
        outbound_action.save(update_fields=["status", "sent_at", "updated_at"])

        # Update conversation
        conversation = Conversation.objects.get(pk=pipeline_data["conversation_id"])
        conversation.last_message_at = tz.now()
        conversation.save(update_fields=["last_message_at", "updated_at"])

        logger.info("Pipeline complete successfully | msg_id=%s", message_id)
        return {
            "status": "success",
            "outgoing_message_id": outgoing.pk,
            "lead_id": pipeline_data["lead_id"],
            "image_urls": pipeline_data.get("image_urls", []),
            "intake_id": pipeline_data.get("intake_id"),
            "ai_analysis_id": pipeline_data.get("ai_analysis_id"),
        }

# =========================================================================

