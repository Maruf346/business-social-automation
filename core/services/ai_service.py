from __future__ import annotations

import logging
from typing import Optional

import requests
from django.conf import settings
from django.db.models import QuerySet

from core.exceptions import AIServiceError
from lead.choices import MESSAGE_DIRECTION
from lead.models import Lead, Message

logger = logging.getLogger(__name__)

# Fallback when the AI service is unreachable / returns garbage
_FALLBACK_REPLY = (
    "Thank you for your message! Our team is currently reviewing your "
    "request and will get back to you shortly. 🙏"
)


class AIService:
    def __init__(self) -> None:
        ai_cfg: dict = getattr(settings, "AI_SERVICE", {})
        self._url: str = ai_cfg.get("API_URL", "http://10.10.28.89:8001/api/v1/inquiries/analyze")
        self._timeout: int = ai_cfg.get("TIMEOUT", 30)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_reply(self, current_message: str, chat_history: QuerySet[Message], lead: Lead, image_urls: Optional[list[str]] = None,) -> str:
        if not self._url:
            logger.error("AI_SERVICE.API_URL is not configured; using fallback reply.")
            return _FALLBACK_REPLY

        payload = self._build_payload(current_message, chat_history, lead, image_urls)
        logger.info("AI Request Payload: %s", payload)
        
        try:
            response = requests.post(
                self._url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data: dict = response.json()
            # data: dict = {
            #     "draft_reply": "ok"
            # }
        except requests.exceptions.Timeout:
            logger.error("AI API timed out after %ss for lead=%s", self._timeout, lead.pk)
            raise AIServiceError(
                f"AI API timed out after {self._timeout}s",
                status_code=408,
            )
        except requests.exceptions.ConnectionError as exc:
            logger.error("AI API connection error: %s", exc)
            raise AIServiceError(f"AI API connection failed: {exc}") from exc
        except requests.exceptions.HTTPError as exc:
            logger.error(
                "AI API returned HTTP %s: %s",
                exc.response.status_code if exc.response else "N/A",
                exc,
            )
            raise AIServiceError(
                f"AI API HTTP error: {exc}",
                status_code=exc.response.status_code if exc.response else None,
                response_body=exc.response.json() if exc.response else None,
            ) from exc
        except (ValueError, TypeError) as exc:
            logger.error("AI API returned non-JSON response: %s", exc)
            raise AIServiceError("AI API returned invalid JSON") from exc

        draft_reply: str = data.get("draft_reply", "")
        if not draft_reply:
            logger.warning("AI response missing 'draft_reply'; full body: %s", data)
            raise AIServiceError(
                "AI response did not contain a 'draft_reply' field.",
                response_body=data,
            )

        logger.info("Received AI draft_reply for lead=%s (len=%d)", lead.pk, len(draft_reply))
        return draft_reply

    # ------------------------------------------------------------------
    # Payload builder
    # ------------------------------------------------------------------
    @staticmethod
    def _build_payload(current_message: str,chat_history: QuerySet[Message],lead: Lead,image_urls: Optional[list[str]] = None,) -> dict:
        history: list[dict[str, str]] = []
        for msg in chat_history:
            role = (
                "user"
                if msg.direction == MESSAGE_DIRECTION.INCOMING
                else "assistant"
            )
            history.append({"role": role, "content": msg.content or ""})

        # Minimal lead profile as db state context
        existing_db_state: dict = {
            "lead_id": lead.pk,
            "lead_name": lead.name or "",
            "lead_phone": lead.phone_number,
        }

        return {
            "current_message": current_message,
            "new_image_urls": image_urls or [],
            "existing_db_state": existing_db_state,
            "recent_chat_history": history,
        }
