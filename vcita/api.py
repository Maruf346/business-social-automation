from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import requests

from .models import VcitaAccount

logger = logging.getLogger(__name__)


class VcitaAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class VcitaAPIClient:
    def __init__(self, account: VcitaAccount, timeout: int = 30):
        self.account = account
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {account.api_token}",
            }
        )

    def list_webhooks(self, params: dict | None = None) -> dict:
        return self.get("/platform/v1/webhooks", params=params)

    def get(self, path: str, params: dict | None = None) -> dict:
        return self.request("GET", path, params=params)

    def request(self, method: str, path: str, **kwargs) -> dict:
        url = urljoin(self.account.api_base_url.rstrip("/") + "/", path.lstrip("/"))
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.exceptions.Timeout as exc:
            raise VcitaAPIError(f"vCita API timed out: {url}", status_code=408) from exc
        except requests.exceptions.ConnectionError as exc:
            raise VcitaAPIError(f"vCita API connection failed: {exc}") from exc

        return self._handle_response(response)

    @staticmethod
    def _handle_response(response: requests.Response) -> dict:
        try:
            data = response.json()
        except ValueError as exc:
            if response.ok:
                return {}
            raise VcitaAPIError(
                "vCita API returned a non-JSON error response.",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        if not response.ok:
            raise VcitaAPIError(
                "vCita API request failed.",
                status_code=response.status_code,
                response_body=data,
            )

        return data
