from __future__ import annotations

from html import escape
from typing import Any

from django.utils import timezone

from core.exceptions import MetaAPIError, OutlookAPIError
from core.services.message_service import MessageService
from core.services.meta_api import MetaAPIService
from core.services.outlook_api import OutlookAPIService
from intake.models import ArtistProfile, IntakeRequest, IntakeSource, OutboundAction, OutboundActionStatus, OutboundActionType
from lead.choices import MESSAGE_STATUS, SEND_BY
from lead.models import Message


class ClientOutboundService:
    @classmethod
    def send_intake_reply(
        cls,
        intake: IntakeRequest,
        text: str,
        media_items: list[dict[str, Any]] | None = None,
        send_by: str | None = None,
        action_type: str = OutboundActionType.AI_AUTO_REPLY,
        actor: ArtistProfile | None = None,
    ) -> Message | None:
        media_items = media_items or []
        action = OutboundAction.objects.create(
            intake=intake,
            lead=intake.lead,
            conversation=intake.conversation,
            actor=actor,
            source=intake.source,
            action_type=action_type,
            text=text or "",
            media_items=media_items,
        )
        try:
            resolved_send_by = send_by or SEND_BY.AI
            if intake.source == IntakeSource.WHATSAPP:
                message = cls._send_whatsapp_reply(intake, text, media_items, resolved_send_by)
            elif intake.source == IntakeSource.OUTLOOK:
                message = cls._send_outlook_reply(intake, text, media_items, resolved_send_by)
            else:
                raise ValueError(f"Unsupported intake source: {intake.source}")
        except Exception as exc:
            action.status = OutboundActionStatus.FAILED
            action.error_message = str(exc)
            action.save(update_fields=["status", "error_message", "updated_at"])
            raise

        action.status = OutboundActionStatus.SENT
        action.message = message
        action.sent_at = timezone.now()
        if message and message.provider_message_id:
            action.provider_message_id = message.provider_message_id
        action.save(update_fields=["status", "message", "sent_at", "provider_message_id", "updated_at"])
        return message

    @classmethod
    def _send_whatsapp_reply(
        cls,
        intake: IntakeRequest,
        text: str,
        media_items: list[dict[str, Any]],
        send_by: str,
    ) -> Message:
        if not intake.whatsapp_account:
            raise MetaAPIError(f"Intake {intake.pk} has no WhatsApp account.")
        if not intake.lead.phone_number:
            raise MetaAPIError(f"Intake {intake.pk} lead has no phone number.")

        outgoing = MessageService.save_outgoing_message(lead=intake.lead, content=text, send_by=send_by)
        meta_svc = MetaAPIService(intake.whatsapp_account)

        if text:
            meta_response = meta_svc.send_text_message(to=intake.lead.phone_number, body=text)
            wamid = MetaAPIService.extract_message_id(meta_response)
            if wamid:
                outgoing.provider_message_id = wamid
                outgoing.save(update_fields=["provider_message_id", "updated_at"])

        for media in media_items:
            media_type = media.get("type", "")
            media_url = media.get("url", "")
            caption = media.get("caption", "")
            file_name = media.get("file_name", "")
            if not media_url:
                continue
            if media_type == "image":
                meta_svc.send_image_message(to=intake.lead.phone_number, image_url=media_url, caption=caption)
            else:
                meta_svc.send_document_message(
                    to=intake.lead.phone_number,
                    document_url=media_url,
                    filename=file_name or "attachment",
                    caption=caption,
                )

        return outgoing

    @classmethod
    def _send_outlook_reply(
        cls,
        intake: IntakeRequest,
        text: str,
        media_items: list[dict[str, Any]],
        send_by: str,
    ) -> Message:
        if not intake.outlook_account:
            raise OutlookAPIError(f"Intake {intake.pk} has no Outlook account.")
        if not intake.outlook_user_id:
            raise OutlookAPIError(f"Intake {intake.pk} has no Outlook user id.")
        if not intake.last_incoming_message or not intake.last_incoming_message.provider_message_id:
            raise OutlookAPIError(f"Intake {intake.pk} has no source Outlook message.")

        html = OutlookAPIService.text_to_html(text or "")
        if media_items:
            links = []
            for media in media_items:
                url = media.get("url", "")
                if not url:
                    continue
                label = escape(media.get("file_name") or url)
                links.append(f'<li><a href="{escape(url)}">{label}</a></li>')
            if links:
                html = f"{html}<p>Attachments:</p><ul>{''.join(links)}</ul>"

        outgoing = MessageService.save_outgoing_email(
            lead=intake.lead,
            conversation=intake.conversation,
            subject=intake.last_incoming_message.subject or "",
            content=text,
            html_content=html,
            send_by=send_by,
        )

        try:
            OutlookAPIService(intake.outlook_account).send_reply(
                user_id=intake.outlook_user_id,
                message_id=intake.last_incoming_message.provider_message_id,
                body_html=html,
            )
        except OutlookAPIError:
            outgoing.status = MESSAGE_STATUS.FAILED
            outgoing.error_message = "Graph API reply send failed"
            outgoing.save(update_fields=["status", "error_message", "updated_at"])
            raise

        return outgoing
