from __future__ import annotations

import json
import logging
from typing import Any

from drf_spectacular.utils import OpenApiResponse, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import VcitaAccount, VcitaWebhookEvent

logger = logging.getLogger(__name__)


class VcitaWebhook(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    @extend_schema(
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="vCita webhook health response")},
    )
    def get(self, request):
        return Response({"ok": True, "integration": "vcita"})

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT, description="vCita webhook accepted")},
    )
    def post(self, request):
        raw_body = request.body.decode("utf-8", errors="ignore")
        payload, parse_error = self._parse_payload(raw_body)
        account = VcitaAccount.objects.filter(is_active=True).first()

        event = VcitaWebhookEvent.objects.create(
            account=account,
            method=request.method,
            path=request.path,
            headers=dict(request.headers),
            payload=payload,
            body=raw_body,
            ip_address=self._get_client_ip(request),
            event_type=self._extract_value(payload, "event_type", "event", "type", "action"),
            entity=self._extract_value(payload, "entity", "object", "resource", "model"),
            external_id=self._extract_external_id(payload),
            processing_error=parse_error,
        )
        logger.info("vCita webhook stored id=%s event_type=%s entity=%s", event.pk, event.event_type, event.entity)

        return Response(
            {
                "status": "EVENT_RECEIVED",
                "event_id": event.pk,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _parse_payload(raw_body: str) -> tuple[dict, str]:
        if not raw_body.strip():
            return {}, ""
        try:
            data = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError) as exc:
            return {}, f"Invalid JSON payload: {exc}"
        if not isinstance(data, dict):
            return {"value": data}, "Payload root was not an object."
        return data, ""

    @staticmethod
    def _extract_value(payload: dict, *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return str(value)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if value is not None:
                    return str(value)
        return ""

    @classmethod
    def _extract_external_id(cls, payload: dict) -> str:
        for key in ("id", "uid", "external_id", "resource_id"):
            value = payload.get(key)
            if value is not None:
                return str(value)

        data: Any = payload.get("data")
        if isinstance(data, dict):
            for key in ("id", "uid", "external_id", "resource_id"):
                value = data.get(key)
                if value is not None:
                    return str(value)
        return ""

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")
