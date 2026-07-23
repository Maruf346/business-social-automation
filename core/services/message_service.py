from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_tz
from typing import Optional

from django.conf import settings
from django.db.models import QuerySet

from lead.choices import (
    LEAD_SOURCE,
    MESSAGE_DIRECTION,
    MESSAGE_STATUS,
    MESSAGE_TYPE,
    SEND_BY,
)
from lead.models import Lead, Message
from core.services.webhook_parser import ParsedMessage

logger = logging.getLogger(__name__)


class MessageService:
    # ------------------------------------------------------------------
    # Lead operations
    @staticmethod
    def get_or_create_lead(
        phone_number: str,
        name: str = "",
        source: str = LEAD_SOURCE.WHATSAPP,
    ) -> Lead:
        lead, created = Lead.objects.get_or_create(
            source=source,
            phone_number=phone_number,
            defaults={"name": name},
        )
        if created:
            logger.info("Created new Lead id=%s phone=%s", lead.pk, phone_number)
        else:
            # Update the name if it was previously blank
            if not lead.name and name:
                lead.name = name
                lead.save(update_fields=["name", "updated_at"])
        return lead
    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------
    # Incoming message
    @staticmethod
    def save_incoming_message(lead: Lead, parsed: ParsedMessage) -> Message:
        msg_type = parsed.message_type.upper()
        valid_types = {choice.value.upper(): choice for choice in MESSAGE_TYPE}
        resolved_type = valid_types.get(msg_type, MESSAGE_TYPE.TEXT)
        timestamp = datetime.fromtimestamp(
            int(parsed.timestamp), tz=dt_tz.utc
        )

        message = Message.objects.create(
            system_id=parsed.message_id,
            lead=lead,
            send_by=SEND_BY.CLIENT,
            direction=MESSAGE_DIRECTION.INCOMING,
            message_type=resolved_type,
            content=parsed.body,
            status=MESSAGE_STATUS.RECEIVED,
            timestamp=timestamp,
        )
        logger.info(
            "Saved incoming message id=%s wamid=%s lead=%s",
            message.pk,
            parsed.message_id,
            lead.pk,
        )
        return message
    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------
    # Outgoing message
    # ------------------------------------------------------------------
    @staticmethod
    def save_outgoing_message(
        lead: Lead,
        content: str,
        system_id: str = "",
    ) -> Message:
        message = Message.objects.create(
            system_id=system_id,
            lead=lead,
            send_by=SEND_BY.AI,
            direction=MESSAGE_DIRECTION.OUTGOING,
            message_type=MESSAGE_TYPE.TEXT,
            content=content,
            status=MESSAGE_STATUS.SENT,
        )
        logger.info(
            "Saved outgoing message id=%s lead=%s", message.pk, lead.pk
        )
        return message

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------
    @staticmethod
    def update_message_status(system_id: str, new_status: str) -> bool:
        status_map: dict[str, str] = {
            "sent": MESSAGE_STATUS.SENT,
            "delivered": MESSAGE_STATUS.DELIVERED,
            "read": MESSAGE_STATUS.READ,
            "failed": MESSAGE_STATUS.FAILED,
        }
        resolved = status_map.get(new_status)
        if resolved is None:
            logger.warning("Unknown status '%s' for wamid=%s", new_status, system_id)
            return False

        updated = Message.objects.filter(system_id=system_id).update(status=resolved)

        # If the status is READ, also flip the `read` boolean
        if resolved == MESSAGE_STATUS.READ and updated:
            Message.objects.filter(system_id=system_id).update(read=True)

        if updated:
            logger.info("Updated message wamid=%s → %s", system_id, resolved)
        else:
            logger.warning("No message found for wamid=%s", system_id)
        return bool(updated)

    # ------------------------------------------------------------------
    # Chat history for AI context
    # ------------------------------------------------------------------
    @staticmethod
    def get_chat_history(
        lead: Lead,
        limit: Optional[int] = None,
    ) -> QuerySet[Message]:
        if limit is None:
            limit = settings.AI_SERVICE.get("CHAT_HISTORY_LIMIT", 6)

        recent_ids = (
            Message.objects.filter(lead=lead)
            .order_by("-timestamp")
            .values_list("pk", flat=True)[:limit]
        )
        return Message.objects.filter(pk__in=recent_ids).order_by("timestamp")

    @staticmethod
    def update_lead_last_message(lead: Lead, message: Message) -> None:
        lead.last_message_at = message.timestamp
        lead.save(update_fields=["last_message_at", "updated_at"])


