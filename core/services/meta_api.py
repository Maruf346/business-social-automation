from __future__ import annotations
import logging
import requests
from django.conf import settings
from core.exceptions import MetaAPIError
from core.models import WhatsAppAccount

logger = logging.getLogger(__name__)


class MetaAPIService:
    def __init__(self, whatsapp_account: WhatsAppAccount) -> None:
        self._account = whatsapp_account
        self._phone_number_id: str = whatsapp_account.phone_number_id
        self._access_token: str = self._resolve_access_token(whatsapp_account)
        self._api_version: str = settings.WHATSAPP.get("API_VERSION", "v25.0")
        self._base_url = f"https://graph.facebook.com/{self._api_version}/{self._phone_number_id}/messages"
        self._session = self._build_session()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def send_text_message(self, to: str, body: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        return self._post(payload)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _post(self, payload: dict) -> dict:
        try:
            response = self._session.post(
                self._base_url,
                json=payload,
                timeout=15,
            )
            data: dict = response.json()
        except requests.exceptions.Timeout as exc:
            logger.error("Meta API timed out for phone_id=%s", self._phone_number_id)
            raise MetaAPIError(
                "Meta API request timed out", status_code=408
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Meta API connection error: %s", exc)
            raise MetaAPIError(
                f"Meta API connection failed: {exc}"
            ) from exc
        except (ValueError, TypeError) as exc:
            logger.error("Meta API returned non-JSON: %s", exc)
            raise MetaAPIError("Meta API returned invalid JSON") from exc

        # Handle Meta-level error envelopes
        if "error" in data:
            error_info = data["error"]
            msg = error_info.get("message", "Unknown Meta API error")
            code = error_info.get("code", response.status_code)
            logger.error(
                "Meta API error code=%s msg=%s phone_id=%s",
                code,
                msg,
                self._phone_number_id,
            )
            raise MetaAPIError(msg, status_code=code, response_body=data)

        if not response.ok:
            logger.error(
                "Meta API HTTP %s: %s", response.status_code, data
            )
            raise MetaAPIError(
                f"Meta API returned HTTP {response.status_code}",
                status_code=response.status_code,
                response_body=data,
            )

        logger.info("Meta API message sent successfully via phone_id=%s", self._phone_number_id)
        return data

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        })
        return session

    @staticmethod
    def _resolve_access_token(account: WhatsAppAccount) -> str:
        token_data = account.token_data
        if isinstance(token_data, dict):
            token = token_data.get("access_token", "")
        elif isinstance(token_data, str):
            token = token_data
        else:
            token = ""

        if not token:
            logger.error(
                "No access token found for WhatsAppAccount id=%s phone_id=%s",
                account.pk,
                account.phone_number_id,
            )
            raise MetaAPIError(
                f"Missing access token for WhatsAppAccount {account.pk}"
            )
        return token

    # ------------------------------------------------------------------
    # Helpers for extracting Meta response data
    # ------------------------------------------------------------------
    @staticmethod
    def extract_message_id(meta_response: dict) -> str:
        try:
            return meta_response["messages"][0]["id"]
        except (KeyError, IndexError, TypeError):
            logger.warning("Could not extract message id from Meta response: %s", meta_response)
            return ""
