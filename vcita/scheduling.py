from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction

from intake.models import IntakeRequest, PaymentStatus, ScheduleStatus
from lead.models import Lead

from .api import VcitaAPIClient, VcitaAPIError
from .models import VcitaAccount, VcitaService


class VcitaSchedulingError(Exception):
    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass(frozen=True)
class VcitaScheduleResult:
    intake: IntakeRequest
    account: VcitaAccount
    service: VcitaService
    requested_date: str
    requested_time: str
    booking_uid: str
    raw_response: dict[str, Any]
    was_reschedule: bool


class VcitaSchedulingService:
    DEFAULT_DURATION_MINUTES = 60

    def __init__(self, account: VcitaAccount | None = None):
        self.account = account or VcitaAccount.objects.filter(is_active=True).first()
        if self.account:
            self.client = VcitaAPIClient(self.account)
        else:
            self.client = None

    def schedule_intake(
        self,
        intake: IntakeRequest,
        appointment_date: str | None = None,
        appointment_time: str | None = None,
        service_code: str = "",
    ) -> VcitaScheduleResult:
        account = self._require_account()
        client = self._require_client()
        appointment_date = (appointment_date or intake.appointment_date).strip()
        appointment_time = (appointment_time or intake.appointment_time).strip()
        start_local = self._parse_local_start(appointment_date, appointment_time, account.default_timezone)

        if not intake.assigned_artist_id:
            raise VcitaSchedulingError("Please assign an artist first, then schedule this request.")
        if not intake.assigned_artist.vcita_staff_uid:
            raise VcitaSchedulingError(
                f"{intake.assigned_artist.name} is missing a vCita staff ID. Add it in the Admin panel first."
            )
        if not account.business_uid:
            raise VcitaSchedulingError("vCita business UID is missing. Sync user info or add it in the Admin panel.")

        service = self._get_service(account, service_code)
        vcita_client_uid = self._get_or_create_client_uid(
            intake.lead,
            account,
            client,
            staff_uid=intake.assigned_artist.vcita_staff_uid,
        )
        was_reschedule = bool(intake.vcita_booking_uid)
        self._check_availability(
            client=client,
            service=service,
            staff_uid=intake.assigned_artist.vcita_staff_uid,
            start_local=start_local,
            exclude_booking_uid=intake.vcita_booking_uid if was_reschedule else "",
        )

        payload = self._build_booking_payload(
            intake=intake,
            account=account,
            service=service,
            client_uid=vcita_client_uid,
            staff_uid=intake.assigned_artist.vcita_staff_uid,
            start_local=start_local,
        )

        try:
            if was_reschedule:
                response = client.update_booking(intake.vcita_booking_uid, payload)
            else:
                response = client.create_booking(payload)
        except VcitaAPIError as exc:
            self._mark_schedule_failed(intake, self._format_api_error(exc))
            raise VcitaSchedulingError(
                self._format_api_error(exc),
                status_code=exc.status_code,
                response_body=exc.response_body,
            ) from exc

        booking_uid = self._extract_uid(response, keys=("booking_id", "booking_uid", "appointment_id", "uid", "id"))
        if not booking_uid and was_reschedule:
            booking_uid = intake.vcita_booking_uid
        if not booking_uid:
            self._mark_schedule_failed(intake, "vCita did not return a booking ID.")
            raise VcitaSchedulingError("vCita scheduled response did not include a booking ID.")

        with transaction.atomic():
            intake.scheduled_date = appointment_date
            intake.scheduled_time = appointment_time
            intake.scheduled_service = service
            intake.scheduled_service_code = service.code
            intake.scheduled_service_name = service.name
            intake.scheduled_service_uid = service.vcita_service_uid
            intake.vcita_booking_uid = booking_uid
            intake.schedule_status = ScheduleStatus.RESCHEDULED if was_reschedule else ScheduleStatus.SCHEDULED
            intake.schedule_error = ""
            if intake.payment_status == PaymentStatus.UNKNOWN:
                intake.payment_status = PaymentStatus.UNPAID
            intake.save(
                update_fields=[
                    "scheduled_date",
                    "scheduled_time",
                    "scheduled_service",
                    "scheduled_service_code",
                    "scheduled_service_name",
                    "scheduled_service_uid",
                    "vcita_booking_uid",
                    "schedule_status",
                    "schedule_error",
                    "payment_status",
                    "updated_at",
                ]
            )

        return VcitaScheduleResult(
            intake=intake,
            account=account,
            service=service,
            requested_date=appointment_date,
            requested_time=appointment_time,
            booking_uid=booking_uid,
            raw_response=response,
            was_reschedule=was_reschedule,
        )

    def _get_service(self, account: VcitaAccount, service_code: str) -> VcitaService:
        normalized_code = (service_code or "").strip().upper()
        if not normalized_code:
            raise VcitaSchedulingError(self.service_code_help(account))

        service = VcitaService.objects.filter(
            account=account,
            code=normalized_code,
            is_active=True,
        ).first()
        if service:
            return service

        raise VcitaSchedulingError(
            f"Unknown service code: {normalized_code}.\n{self.service_code_help(account)}"
        )

    @staticmethod
    def service_code_help(account: VcitaAccount | None = None) -> str:
        queryset = VcitaService.objects.filter(is_active=True).select_related("account").order_by("code")
        if account:
            queryset = queryset.filter(account=account)
        services = list(queryset[:20])
        if not services:
            return "Please add an active vCita service mapping in the Admin panel before scheduling."

        lines = ["Please select a service code to schedule this request:"]
        for service in services:
            lines.append(f"- {service.code}: {service.name}")
        lines.append("Use /schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM")
        lines.append("Example: /schedule 12 OCH 2026-09-04 14:30")
        return "\n".join(lines)

    def _get_or_create_client_uid(
        self,
        lead: Lead,
        account: VcitaAccount,
        client: VcitaAPIClient,
        staff_uid: str = "",
    ) -> str:
        if lead.vcita_client_uid:
            return lead.vcita_client_uid

        search_term = (lead.email or lead.phone_number or "").strip()
        if search_term:
            search_by = "email" if lead.email else "phone"
            try:
                search_response = client.search_clients(search_term, search_by=search_by)
            except VcitaAPIError:
                search_response = {}
            existing_uid = self._extract_uid(
                search_response,
                keys=("client_id", "client_uid", "contact_id", "contact_uid", "uid", "id"),
            )
            if existing_uid:
                lead.vcita_client_uid = existing_uid
                lead.save(update_fields=["vcita_client_uid", "updated_at"])
                return existing_uid

        payload = self._build_client_payload(lead, account, staff_uid=staff_uid)
        try:
            response = client.create_client(payload)
        except VcitaAPIError as exc:
            raise VcitaSchedulingError(
                self._format_api_error(exc),
                status_code=exc.status_code,
                response_body=exc.response_body,
            ) from exc

        client_uid = self._extract_uid(response, keys=("client_id", "client_uid", "contact_id", "contact_uid", "uid", "id"))
        if not client_uid:
            raise VcitaSchedulingError("vCita client creation did not return a client ID.")

        lead.vcita_client_uid = client_uid
        lead.save(update_fields=["vcita_client_uid", "updated_at"])
        return client_uid

    def _check_availability(
        self,
        client: VcitaAPIClient,
        service: VcitaService,
        staff_uid: str,
        start_local: datetime,
        exclude_booking_uid: str = "",
    ) -> None:
        start_utc = start_local.astimezone(dt_timezone.utc)
        end_utc = (start_local + timedelta(minutes=self.DEFAULT_DURATION_MINUTES)).astimezone(dt_timezone.utc)
        params: dict[str, Any] = {
            "start_time": start_utc.isoformat().replace("+00:00", "Z"),
            "end_time": end_utc.isoformat().replace("+00:00", "Z"),
            "service_uid": service.vcita_service_uid,
            "staff_uids": staff_uid,
            "slot_duration": self.DEFAULT_DURATION_MINUTES,
        }
        if exclude_booking_uid:
            params["exclude_booking_uid"] = exclude_booking_uid

        try:
            response = client.get_availability_slots(params)
        except VcitaAPIError as exc:
            raise VcitaSchedulingError(
                self._format_api_error(exc),
                status_code=exc.status_code,
                response_body=exc.response_body,
            ) from exc

        slots = self._extract_slots(response)
        if slots and not self._slot_matches(slots, start_local):
            raise VcitaSchedulingError("That vCita slot is not available. Please choose another date/time.")

    def _build_client_payload(self, lead: Lead, account: VcitaAccount, staff_uid: str = "") -> dict[str, Any]:
        display_name = (lead.name or "").strip() or lead.email or lead.phone_number or f"Lead #{lead.pk}"
        first_name, last_name = self._split_client_name(display_name, lead.pk)
        client_payload: dict[str, Any] = {
            "business_id": account.business_uid,
            "name": display_name,
            "first_name": first_name,
            "last_name": last_name,
            "source_channel": "tattoo-hysteria-backend",
            "source_name": "Tattoo Hysteria AI Intake",
        }
        if staff_uid:
            client_payload["staff_id"] = staff_uid
        if lead.email:
            client_payload["email"] = lead.email
        if lead.phone_number:
            client_payload["phone"] = lead.phone_number
        return client_payload

    @staticmethod
    def _split_client_name(display_name: str, lead_id: int) -> tuple[str, str]:
        cleaned = (display_name or "").strip()
        if not cleaned or "@" in cleaned:
            return "Tattoo", f"Lead {lead_id}"
        parts = cleaned.split(maxsplit=1)
        first_name = parts[0].strip() or "Tattoo"
        last_name = parts[1].strip() if len(parts) > 1 else f"Lead {lead_id}"
        return first_name, last_name

    def _build_booking_payload(
        self,
        intake: IntakeRequest,
        account: VcitaAccount,
        service: VcitaService,
        client_uid: str,
        staff_uid: str,
        start_local: datetime,
    ) -> dict[str, Any]:
        note_parts = [
            f"Request #{intake.pk}",
            f"Service: {service.code} - {service.name}",
            f"Idea: {intake.tattoo_idea or 'Unclear'}",
        ]
        price = intake.approved_price or intake.ai_suggested_price
        if price:
            note_parts.append(f"Price: {price}")
        if intake.latest_summary:
            note_parts.append(f"Summary: {intake.latest_summary}")

        return {
            "business_id": account.business_uid,
            "service_id": service.vcita_service_uid,
            "staff_id": staff_uid,
            "client_id": client_uid,
            "start_time": start_local.isoformat(),
            "time_zone": account.default_timezone,
            "status": "scheduled",
            "notes": "\n".join(note_parts),
        }

    def _require_account(self) -> VcitaAccount:
        if not self.account:
            raise VcitaSchedulingError("vCita account is not configured. Add an active vCita account first.")
        return self.account

    def _require_client(self) -> VcitaAPIClient:
        if not self.client:
            raise VcitaSchedulingError("vCita account is not configured. Add an active vCita account first.")
        return self.client

    @staticmethod
    def _parse_local_start(appointment_date: str, appointment_time: str, timezone_name: str) -> datetime:
        if not appointment_date or not appointment_time:
            raise VcitaSchedulingError("Schedule date/time is missing. Use /schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM.")
        try:
            parsed = datetime.strptime(f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise VcitaSchedulingError("Use this format: /schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM") from exc

        try:
            tzinfo = ZoneInfo(timezone_name or "Europe/Amsterdam")
        except ZoneInfoNotFoundError as exc:
            raise VcitaSchedulingError("Configured vCita timezone is invalid. Use Europe/Amsterdam.") from exc
        return parsed.replace(tzinfo=tzinfo)

    @staticmethod
    def _extract_uid(data: Any, keys: tuple[str, ...]) -> str:
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, (str, int)):
                    return str(value)
            for value in data.values():
                uid = VcitaSchedulingService._extract_uid(value, keys)
                if uid:
                    return uid
        if isinstance(data, list):
            for item in data:
                uid = VcitaSchedulingService._extract_uid(item, keys)
                if uid:
                    return uid
        return ""

    @staticmethod
    def _extract_slots(data: Any) -> list[dict[str, Any]]:
        slots: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for key, value in data.items():
                if key in {"slots", "availability_slots", "available_slots"} and isinstance(value, list):
                    slots.extend(item for item in value if isinstance(item, dict))
                else:
                    slots.extend(VcitaSchedulingService._extract_slots(value))
        elif isinstance(data, list):
            for item in data:
                slots.extend(VcitaSchedulingService._extract_slots(item))
        return slots

    @staticmethod
    def _slot_matches(slots: list[dict[str, Any]], start_local: datetime) -> bool:
        expected_utc = start_local.astimezone(dt_timezone.utc)
        for slot in slots:
            value = slot.get("start_time") or slot.get("start") or slot.get("starts_at")
            if not isinstance(value, str):
                continue
            normalized = value.replace("Z", "+00:00")
            try:
                slot_start = datetime.fromisoformat(normalized)
            except ValueError:
                continue
            if slot_start.astimezone(dt_timezone.utc) == expected_utc:
                return True
        return False

    @staticmethod
    def _format_api_error(exc: VcitaAPIError) -> str:
        if exc.status_code:
            return f"vCita API error {exc.status_code}: {exc.response_body or exc}"
        return f"vCita API error: {exc.response_body or exc}"

    @staticmethod
    def _mark_schedule_failed(intake: IntakeRequest, message: str) -> None:
        intake.schedule_status = ScheduleStatus.FAILED
        intake.schedule_error = message
        intake.save(update_fields=["schedule_status", "schedule_error", "updated_at"])