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

    def userinfo(self) -> dict:
        return self.get("/oauth/userinfo")

    def list_staff(self, business_uid: str, status: str = "active") -> dict:
        return self.get(f"/platform/v1/businesses/{business_uid}/staffs", params={"status": status})

    def list_services(self, business_uid: str) -> dict:
        return self.get("/platform/v1/services", params={"business_id": business_uid})

    def search_clients(self, query: str, search_by: str = "") -> dict:
        params = {"search_term": query}
        if search_by:
            params["search_by"] = search_by
        return self.get("/platform/v1/clients", params=params)

    def create_client(self, payload: dict[str, Any]) -> dict:
        return self.post("/platform/v1/clients", json=payload)

    def get_availability_slots(self, params: dict[str, Any]) -> dict:
        return self.get("/v3/scheduling/availability_slots", params=params)

    def create_booking(self, payload: dict[str, Any]) -> dict:
        return self.post("/business/scheduling/v1/bookings", json=payload)

    def update_booking(self, booking_uid: str, payload: dict[str, Any]) -> dict:
        return self.put(f"/business/scheduling/v1/bookings/{booking_uid}", json=payload)

    def subscribe_webhook(self, event: str, target_url: str) -> dict:
        return self.post("/platform/v1/webhook/subscribe", json={"event": event, "target_url": target_url})

    def unsubscribe_webhook(self, target_url: str, event: str = "") -> dict:
        payload = {"target_url": target_url}
        if event:
            payload["event"] = event
        return self.post("/platform/v1/webhook/unsubscribe", json=payload)

    def get(self, path: str, params: dict | None = None) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, **kwargs) -> dict:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> dict:
        return self.request("PUT", path, **kwargs)

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
