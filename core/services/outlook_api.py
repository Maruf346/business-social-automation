from __future__ import annotations

import logging
import re
from html import unescape
from typing import Optional

import requests
from django.conf import settings

from core.exceptions import OutlookAPIError
from core.models import OutlookAccount
from core.outlook.graph_subscription import GraphSubscriptionService

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_RESOURCE_USER_RE = re.compile(r"Users/([^/]+)/", re.IGNORECASE)


class OutlookAPIService:
    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, outlook_account: OutlookAccount) -> None:
        self._account = outlook_account
        self._access_token: str = GraphSubscriptionService.get_access_token(outlook_account)
        self._session = self._build_session()

    # Public API
    def fetch_message(self, user_id: str, message_id: str) -> dict:
        url = f"{self.BASE_URL}/users/{user_id}/messages/{message_id}"
        params = {
            "$select": (
                "id,subject,body,from,toRecipients,receivedDateTime,"
                "conversationId,internetMessageId,hasAttachments"
            )
        }
        data = self._get(url, params=params)
        logger.info(
            "Fetched email id=%s subject='%s' from=%s",
            message_id,
            data.get("subject", ""),
            data.get("from", {}).get("emailAddress", {}).get("address", ""),
        )
        return data

    def fetch_attachments(self, user_id: str, message_id: str) -> list[dict]:
        url = f"{self.BASE_URL}/users/{user_id}/messages/{message_id}/attachments"
        data = self._get(url)
        attachments: list[dict] = data.get("value", [])
        logger.info(
            "Fetched %d attachments for email id=%s",
            len(attachments), message_id,
        )
        return attachments

    def send_reply(self, user_id: str, message_id: str, body_html: str) -> dict:
        url = f"{self.BASE_URL}/users/{user_id}/messages/{message_id}/reply"
        payload = {
            "message": {
                "body": {
                    "contentType": "HTML",
                    "content": body_html,
                }
            }
        }
        result = self._post(url, payload)
        logger.info("Reply sent for email id=%s in user=%s", message_id, user_id)
        return result

    # extract user_id from resource string
    @staticmethod
    def extract_user_id_from_resource(resource: str) -> str:
        match = _RESOURCE_USER_RE.search(resource)
        if not match:
            raise OutlookAPIError(
                f"Cannot extract user_id from resource: '{resource}'"
            )
        return match.group(1)

    # strip HTML to plain text
    @staticmethod
    def strip_html_to_text(html: str) -> str:
        # Replace common block elements with newlines
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        # Strip remaining tags
        text = _HTML_TAG_RE.sub("", text)
        # Unescape HTML entities
        text = unescape(text)
        # Clean up excessive whitespace
        lines = [line.strip() for line in text.splitlines()]
        text = "\n".join(line for line in lines if line)
        return text.strip()

    # wrap plain text in HTML for email reply
    @staticmethod
    def text_to_html(text: str) -> str:
        paragraphs = text.split("\n\n")
        html_parts = []
        for para in paragraphs:
            para_html = para.replace("\n", "<br>")
            html_parts.append(f"<p>{para_html}</p>")
        return "\n".join(html_parts)

    # HTTP internals
    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        try:
            response = self._session.get(url, params=params, timeout=30)
        except requests.exceptions.Timeout as exc:
            logger.error("Graph API GET timed out: %s", url)
            raise OutlookAPIError("Graph API GET timed out", status_code=408) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Graph API connection error: %s", exc)
            raise OutlookAPIError(f"Graph API connection failed: {exc}") from exc

        return self._handle_response(response)

    def _post(self, url: str, payload: dict) -> dict:
        try:
            response = self._session.post(url, json=payload, timeout=30)
        except requests.exceptions.Timeout as exc:
            logger.error("Graph API POST timed out: %s", url)
            raise OutlookAPIError("Graph API POST timed out", status_code=408) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Graph API connection error: %s", exc)
            raise OutlookAPIError(f"Graph API connection failed: {exc}") from exc

        return self._handle_response(response)

    def _handle_response(self, response: requests.Response) -> dict:
        if response.status_code == 202:
            return {}
        
        try:
            data: dict = response.json()
        except (ValueError, TypeError):
            if response.ok:
                return {}
            logger.error("Graph API returned non-JSON: status=%s", response.status_code)
            raise OutlookAPIError(
                "Graph API returned non-JSON response",
                status_code=response.status_code,
            )

        # Handle Graph API error envelope
        if "error" in data:
            error_info = data["error"]
            msg = error_info.get("message", "Unknown Graph API error")
            code = error_info.get("code", str(response.status_code))
            logger.error(
                "Graph API error code=%s msg=%s",
                code, msg,
            )
            raise OutlookAPIError(msg, status_code=response.status_code, response_body=data)

        if not response.ok:
            logger.error("Graph API HTTP %s: %s", response.status_code, data)
            raise OutlookAPIError(
                f"Graph API returned HTTP {response.status_code}",
                status_code=response.status_code,
                response_body=data,
            )

        return data

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        })
        return session


