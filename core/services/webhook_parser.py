from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.exceptions import WebhookParsingError

logger = logging.getLogger(__name__)


class WebhookEventType(str, Enum):
    MESSAGE = "message"
    STATUS = "status"

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ParsedMessage:
    sender_phone: str
    sender_user_id: str
    sender_name: str
    message_id: str  # wamid
    timestamp: str  # Unix timestamp string
    message_type: str  # text, image, audio, …
    body: str  # text body (empty string for non-text)
    raw: dict = field(repr=False, default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedStatus:
    message_id: str  # wamid the status refers to
    status: str  # sent | delivered | read | failed
    timestamp: str
    recipient_id: str
    raw: dict = field(repr=False, default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedWebhookEvent:
    event_type: WebhookEventType
    phone_number_id: str
    waba_id: str
    display_phone_number: str
    message: Optional[ParsedMessage] = None
    status: Optional[ParsedStatus] = None

@dataclass(frozen=True, slots=True)
class OutlookWebhookParsedEvent:
    event_type: WebhookEventType
    notification: str
    subscription_id: str
    message_id: str
    resource: str
    tenant_id: str
    client_state: str

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class WebhookParser:
    @staticmethod
    def parse(payload: dict) -> ParsedWebhookEvent:
        try:
            entry = payload["entry"][0]
            waba_id: str = entry["id"]
            change_value: dict = entry["changes"][0]["value"]
            metadata: dict = change_value["metadata"]
            phone_number_id: str = metadata["phone_number_id"]
            display_phone_number: str = metadata.get("display_phone_number", "")
        except (KeyError, IndexError, TypeError) as exc:
            raise WebhookParsingError(
                f"Payload missing required top-level fields: {exc}"
            ) from exc

        # ── Incoming message ────────────────────────────────────────────
        if "messages" in change_value:
            return WebhookParser._parse_message_event(
                change_value, phone_number_id, waba_id, display_phone_number
            )

        # ── Status update ───────────────────────────────────────────────
        if "statuses" in change_value:
            return WebhookParser._parse_status_event(
                change_value, phone_number_id, waba_id, display_phone_number
            )

        raise WebhookParsingError(
            "Payload contains neither 'messages' nor 'statuses'."
        )

    def outlook_parse(payload: dict):
        try:
            notification = payload["value"][0]
            subscription_id = notification["subscriptionId"]
            message_id = notification["resourceData"]["id"]
            resource = notification["resource"]
            tenant_id = notification["tenantId"]
            client_state = notification["clientState"]
        except (KeyError, IndexError, TypeError) as exc:
            raise WebhookParsingError(
                f"Payload missing required top-level fields: {exc}"
            ) from exc
        
        return OutlookWebhookParsedEvent(
            event_type=WebhookEventType.MESSAGE,
            notification=notification,
            subscription_id=subscription_id,
            message_id=message_id,
            resource=resource,
            tenant_id=tenant_id,
            client_state=client_state
        )
    
    # ── Private helpers ─────────────────────────────────────────────────

    @staticmethod
    def _parse_message_event(value: dict, phone_number_id: str, waba_id: str, display_phone_number: str,) -> ParsedWebhookEvent:
        try:
            contact = value["contacts"][0]
            msg = value["messages"][0]

            body = ""
            msg_type = msg.get("type", "text")
            if msg_type == "text":
                body = msg.get("text", {}).get("body", "")

            parsed_msg = ParsedMessage(
                sender_phone=msg["from"],
                sender_user_id=contact.get("user_id", ""),
                sender_name=contact.get("profile", {}).get("name", ""),
                message_id=msg["id"],
                timestamp=msg["timestamp"],
                message_type=msg_type,
                body=body,
                raw=msg,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise WebhookParsingError(
                f"Failed to parse incoming message: {exc}"
            ) from exc

        return ParsedWebhookEvent(
            event_type=WebhookEventType.MESSAGE,
            phone_number_id=phone_number_id,
            waba_id=waba_id,
            display_phone_number=display_phone_number,
            message=parsed_msg,
        )

    @staticmethod
    def _parse_status_event(value: dict, phone_number_id: str, waba_id: str, display_phone_number: str,) -> ParsedWebhookEvent:
        try:
            st = value["statuses"][0]
            parsed_status = ParsedStatus(
                message_id=st["id"],
                status=st["status"],
                timestamp=st["timestamp"],
                recipient_id=st.get("recipient_id", ""),
                raw=st,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise WebhookParsingError(
                f"Failed to parse status update: {exc}"
            ) from exc

        return ParsedWebhookEvent(
            event_type=WebhookEventType.STATUS,
            phone_number_id=phone_number_id,
            waba_id=waba_id,
            display_phone_number=display_phone_number,
            status=parsed_status,
        )

