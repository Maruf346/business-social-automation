from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:  # pragma: no cover - handled at runtime for optional deployment setup
    service_account = None
    build = None
    HttpError = Exception

from intake.models import IntakeRequest, PendingHoldStatus

from .models import *


class GoogleCalendarError(Exception):
    pass


@dataclass(frozen=True)
class GoogleCalendarSyncResult:
    checked_calendar_ids: list[str]
    synced_event_ids: list[str]
    warnings: list[str]


class GoogleCalendarService:
    DEFAULT_DURATION_MINUTES = 60

    def __init__(self):
        self._service = None

    def is_configured(self) -> bool:
        config = getattr(settings, "GOOGLE_CALENDAR", {})
        return bool(config.get("SERVICE_ACCOUNT_FILE") or config.get("SERVICE_ACCOUNT_JSON"))

    def test_calendar_access(self, calendar: GoogleCalendarConfig) -> None:
        now = datetime.now().astimezone()
        self._freebusy([calendar.calendar_id], now, now + timedelta(minutes=1))

    def preflight_confirmed_schedule(
        self,
        intake: IntakeRequest,
        start_at: datetime,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        ignore_own_pending_hold: bool = True,
        include_shared_vcita: bool = True,
    ) -> list[str]:
        calendars = self._calendars_for_confirmed_schedule(intake, include_shared_vcita=include_shared_vcita)
        if not calendars:
            return []
        if not self.is_configured():
            raise GoogleCalendarError(
                "Google Calendar is mapped in the Admin panel, but service account credentials are not configured."
            )

        end_at = start_at + timedelta(minutes=duration_minutes)
        busy_by_calendar = self._freebusy([calendar.calendar_id for calendar in calendars], start_at, end_at)
        own_pending_by_calendar = self._active_pending_events_by_calendar(intake) if ignore_own_pending_hold else {}
        busy_names = []
        for calendar in calendars:
            busy_slots = busy_by_calendar.get(calendar.calendar_id) or []
            own_pending = own_pending_by_calendar.get(calendar.pk)
            if own_pending and self._busy_slots_only_match_event(busy_slots, own_pending):
                continue
            if busy_slots:
                busy_names.append(calendar.name)
        if busy_names:
            raise GoogleCalendarError(
                "Google Calendar conflict found for: " + ", ".join(busy_names)
            )
        return [calendar.calendar_id for calendar in calendars]

    def sync_confirmed_schedule(
        self,
        intake: IntakeRequest,
        start_at: datetime,
        service_code: str,
        service_name: str,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        include_shared_vcita: bool = True,
    ) -> GoogleCalendarSyncResult:
        calendars = self._event_calendars_for_confirmed_schedule(intake, include_shared_vcita=include_shared_vcita)
        if not calendars:
            return GoogleCalendarSyncResult(checked_calendar_ids=[], synced_event_ids=[], warnings=[])
        if not self.is_configured():
            return GoogleCalendarSyncResult(
                checked_calendar_ids=[calendar.calendar_id for calendar in calendars],
                synced_event_ids=[],
                warnings=["Google Calendar event was not created because service account credentials are not configured."],
            )

        end_at = start_at + timedelta(minutes=duration_minutes)
        summary = self._build_event_summary(intake, service_code, service_name)
        description = self._build_event_description(intake, service_code, service_name)
        synced_event_ids: list[str] = []
        warnings: list[str] = []

        for calendar in calendars:
            existing = GoogleCalendarEvent.objects.filter(
                intake=intake,
                calendar=calendar,
                event_type=GoogleCalendarEventType.CONFIRMED_APPOINTMENT,
            ).exclude(status=GoogleCalendarSyncStatus.RELEASED).first()
            try:
                response = self._upsert_event(
                    calendar=calendar,
                    existing_event_id=existing.google_event_id if existing else "",
                    start_at=start_at,
                    end_at=end_at,
                    summary=summary,
                    description=description,
                )
            except GoogleCalendarError as exc:
                self._record_failed_event(
                    intake=intake,
                    calendar=calendar,
                    start_at=start_at,
                    end_at=end_at,
                    summary=summary,
                    description=description,
                    message=str(exc),
                    event_type=GoogleCalendarEventType.CONFIRMED_APPOINTMENT,
                    existing=existing,
                )
                warnings.append(f"{calendar.name}: {exc}")
                continue

            google_event_id = str(response.get("id") or (existing.google_event_id if existing else ""))
            with transaction.atomic():
                event = existing or GoogleCalendarEvent(intake=intake, calendar=calendar)
                event.event_type = GoogleCalendarEventType.CONFIRMED_APPOINTMENT
                event.google_event_id = google_event_id
                event.status = GoogleCalendarSyncStatus.SYNCED
                event.start_at = start_at
                event.end_at = end_at
                event.summary = summary
                event.description = description
                event.sync_error = ""
                event.raw_response = response
                event.save()
            if google_event_id:
                synced_event_ids.append(google_event_id)

        return GoogleCalendarSyncResult(
            checked_calendar_ids=[calendar.calendar_id for calendar in calendars],
            synced_event_ids=synced_event_ids,
            warnings=warnings,
        )
    def hold_pending_appointment(
        self,
        intake: IntakeRequest,
        start_at: datetime,
        service_code: str,
        service_name: str,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
    ) -> GoogleCalendarSyncResult:
        calendars = list(
            GoogleCalendarConfig.objects.filter(
                calendar_type=GoogleCalendarType.PENDING,
                is_active=True,
            )
        )
        if not calendars:
            raise GoogleCalendarError("Pending Appointments calendar is not configured in the Admin panel.")
        if not self.is_configured():
            raise GoogleCalendarError("Google Calendar service account credentials are not configured.")

        end_at = start_at + timedelta(minutes=duration_minutes)
        busy_by_calendar = self._freebusy([calendar.calendar_id for calendar in calendars], start_at, end_at)
        busy_names = []
        own_pending_by_calendar = self._active_pending_events_by_calendar(intake)
        for calendar in calendars:
            busy_slots = busy_by_calendar.get(calendar.calendar_id) or []
            own_pending = own_pending_by_calendar.get(calendar.pk)
            if own_pending and self._busy_slots_only_match_event(busy_slots, own_pending):
                continue
            if busy_slots:
                busy_names.append(calendar.name)
        if busy_names:
            raise GoogleCalendarError("Google Calendar conflict found for: " + ", ".join(busy_names))

        summary = self._build_pending_event_summary(intake, service_code, service_name)
        description = self._build_pending_event_description(intake, service_code, service_name)
        synced_event_ids: list[str] = []
        warnings: list[str] = []

        for calendar in calendars:
            existing = GoogleCalendarEvent.objects.filter(
                intake=intake,
                calendar=calendar,
                event_type=GoogleCalendarEventType.PENDING_HOLD,
            ).exclude(status=GoogleCalendarSyncStatus.RELEASED).first()
            try:
                response = self._upsert_event(
                    calendar=calendar,
                    existing_event_id=existing.google_event_id if existing else "",
                    start_at=start_at,
                    end_at=end_at,
                    summary=summary,
                    description=description,
                )
            except GoogleCalendarError as exc:
                self._record_failed_event(
                    intake=intake,
                    calendar=calendar,
                    start_at=start_at,
                    end_at=end_at,
                    summary=summary,
                    description=description,
                    message=str(exc),
                    event_type=GoogleCalendarEventType.PENDING_HOLD,
                    existing=existing,
                )
                warnings.append(f"{calendar.name}: {exc}")
                continue

            google_event_id = str(response.get("id") or (existing.google_event_id if existing else ""))
            with transaction.atomic():
                event = existing or GoogleCalendarEvent(intake=intake, calendar=calendar)
                event.event_type = GoogleCalendarEventType.PENDING_HOLD
                event.google_event_id = google_event_id
                event.status = GoogleCalendarSyncStatus.SYNCED
                event.start_at = start_at
                event.end_at = end_at
                event.summary = summary
                event.description = description
                event.sync_error = ""
                event.raw_response = response
                event.save()
            if google_event_id:
                synced_event_ids.append(google_event_id)

        if warnings and not synced_event_ids:
            raise GoogleCalendarError("Pending hold could not be created: " + " | ".join(warnings))

        return GoogleCalendarSyncResult(
            checked_calendar_ids=[calendar.calendar_id for calendar in calendars],
            synced_event_ids=synced_event_ids,
            warnings=warnings,
        )

    def release_pending_hold(self, intake: IntakeRequest) -> GoogleCalendarSyncResult:
        events = list(
            GoogleCalendarEvent.objects.select_related("calendar").filter(
                intake=intake,
                event_type=GoogleCalendarEventType.PENDING_HOLD,
            ).exclude(status=GoogleCalendarSyncStatus.RELEASED)
        )
        if not events:
            return GoogleCalendarSyncResult(checked_calendar_ids=[], synced_event_ids=[], warnings=[])
        if not self.is_configured():
            return GoogleCalendarSyncResult(
                checked_calendar_ids=[event.calendar.calendar_id for event in events],
                synced_event_ids=[],
                warnings=["Pending hold was not released because Google Calendar credentials are not configured."],
            )

        service = self._get_service()
        released_event_ids: list[str] = []
        warnings: list[str] = []
        for event in events:
            try:
                if event.google_event_id:
                    service.events().delete(
                        calendarId=event.calendar.calendar_id,
                        eventId=event.google_event_id,
                    ).execute()
                event.status = GoogleCalendarSyncStatus.RELEASED
                event.sync_error = ""
                event.save(update_fields=["status", "sync_error", "updated_at"])
                if event.google_event_id:
                    released_event_ids.append(event.google_event_id)
            except HttpError as exc:
                message = self._format_http_error(exc)
                event.status = GoogleCalendarSyncStatus.FAILED
                event.sync_error = message
                event.save(update_fields=["status", "sync_error", "updated_at"])
                warnings.append(f"{event.calendar.name}: {message}")
            except Exception as exc:
                message = str(exc)
                event.status = GoogleCalendarSyncStatus.FAILED
                event.sync_error = message
                event.save(update_fields=["status", "sync_error", "updated_at"])
                warnings.append(f"{event.calendar.name}: {message}")

        return GoogleCalendarSyncResult(
            checked_calendar_ids=[event.calendar.calendar_id for event in events],
            synced_event_ids=released_event_ids,
            warnings=warnings,
        )

    def _calendars_for_confirmed_schedule(
        self,
        intake: IntakeRequest,
        include_shared_vcita: bool = True,
    ) -> list[GoogleCalendarConfig]:
        calendars: list[GoogleCalendarConfig] = []
        if intake.assigned_artist_id:
            calendars.extend(
                GoogleCalendarConfig.objects.filter(
                    calendar_type=GoogleCalendarType.ARTIST,
                    artist_id=intake.assigned_artist_id,
                    is_active=True,
                )
            )
        calendars.extend(
            GoogleCalendarConfig.objects.filter(
                calendar_type=GoogleCalendarType.PENDING,
                is_active=True,
            )
        )
        if include_shared_vcita:
            calendars.extend(
                GoogleCalendarConfig.objects.filter(
                    calendar_type=GoogleCalendarType.SHARED_VCITA,
                    is_active=True,
                )
            )
        return self._unique_calendars(calendars)

    def _event_calendars_for_confirmed_schedule(
        self,
        intake: IntakeRequest,
        include_shared_vcita: bool = True,
    ) -> list[GoogleCalendarConfig]:
        calendars: list[GoogleCalendarConfig] = []
        if intake.assigned_artist_id:
            calendars.extend(
                GoogleCalendarConfig.objects.filter(
                    calendar_type=GoogleCalendarType.ARTIST,
                    artist_id=intake.assigned_artist_id,
                    is_active=True,
                )
            )
        if include_shared_vcita:
            calendars.extend(
                GoogleCalendarConfig.objects.filter(
                    calendar_type=GoogleCalendarType.SHARED_VCITA,
                    is_active=True,
                )
            )
        return self._unique_calendars(calendars)

    @staticmethod
    def _active_pending_events_by_calendar(intake: IntakeRequest) -> dict[int, GoogleCalendarEvent]:
        if intake.pending_hold_status not in {PendingHoldStatus.ACTIVE, PendingHoldStatus.FINALIZED}:
            return {}
        events = GoogleCalendarEvent.objects.filter(
            intake=intake,
            event_type=GoogleCalendarEventType.PENDING_HOLD,
            status=GoogleCalendarSyncStatus.SYNCED,
        )
        return {event.calendar_id: event for event in events}

    @staticmethod
    def _busy_slots_only_match_event(busy_slots: list[dict[str, str]], event: GoogleCalendarEvent) -> bool:
        if not busy_slots:
            return False
        event_start = event.start_at.astimezone(timezone.utc)
        event_end = event.end_at.astimezone(timezone.utc)
        for slot in busy_slots:
            try:
                slot_start = datetime.fromisoformat(str(slot.get("start", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
                slot_end = datetime.fromisoformat(str(slot.get("end", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                return False
            if slot_start != event_start or slot_end != event_end:
                return False
        return True

    @staticmethod
    def _unique_calendars(calendars: list[GoogleCalendarConfig]) -> list[GoogleCalendarConfig]:
        seen: set[int] = set()
        unique: list[GoogleCalendarConfig] = []
        for calendar in calendars:
            if calendar.pk in seen:
                continue
            seen.add(calendar.pk)
            unique.append(calendar)
        return unique

    def _freebusy(self, calendar_ids: list[str], start_at: datetime, end_at: datetime) -> dict[str, list[dict[str, str]]]:
        service = self._get_service()
        body = {
            "timeMin": start_at.isoformat(),
            "timeMax": end_at.isoformat(),
            "items": [{"id": calendar_id} for calendar_id in calendar_ids],
        }
        try:
            response = service.freebusy().query(body=body).execute()
        except HttpError as exc:
            raise GoogleCalendarError(self._format_http_error(exc)) from exc
        except Exception as exc:
            raise GoogleCalendarError(str(exc)) from exc

        calendars = response.get("calendars", {}) if isinstance(response, dict) else {}
        return {
            calendar_id: calendars.get(calendar_id, {}).get("busy", [])
            for calendar_id in calendar_ids
        }

    def _upsert_event(
        self,
        calendar: GoogleCalendarConfig,
        existing_event_id: str,
        start_at: datetime,
        end_at: datetime,
        summary: str,
        description: str,
    ) -> dict[str, Any]:
        service = self._get_service()
        body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_at.isoformat(),
                "timeZone": calendar.timezone,
            },
            "end": {
                "dateTime": end_at.isoformat(),
                "timeZone": calendar.timezone,
            },
        }
        try:
            if existing_event_id:
                return service.events().patch(
                    calendarId=calendar.calendar_id,
                    eventId=existing_event_id,
                    body=body,
                ).execute()
            return service.events().insert(calendarId=calendar.calendar_id, body=body).execute()
        except HttpError as exc:
            raise GoogleCalendarError(self._format_http_error(exc)) from exc
        except Exception as exc:
            raise GoogleCalendarError(str(exc)) from exc

    def _get_service(self):
        if self._service is not None:
            return self._service
        if service_account is None or build is None:
            raise GoogleCalendarError(
                "Google Calendar dependencies are not installed. Install google-api-python-client and google-auth."
            )

        config = getattr(settings, "GOOGLE_CALENDAR", {})
        scopes = config.get("SCOPES") or ["https://www.googleapis.com/auth/calendar"]
        service_account_file = config.get("SERVICE_ACCOUNT_FILE")
        service_account_json = config.get("SERVICE_ACCOUNT_JSON")

        try:
            if service_account_json:
                data = json.loads(service_account_json)
                credentials = service_account.Credentials.from_service_account_info(data, scopes=scopes)
            elif service_account_file:
                credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=scopes)
            else:
                raise GoogleCalendarError("Google Calendar service account credentials are not configured.")
        except GoogleCalendarError:
            raise
        except Exception as exc:
            raise GoogleCalendarError(f"Could not load Google Calendar credentials: {exc}") from exc

        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    @staticmethod
    def _build_pending_event_summary(intake: IntakeRequest, service_code: str, service_name: str) -> str:
        client = str(intake.lead)
        artist = intake.assigned_artist.name if intake.assigned_artist else "Unassigned"
        return f"PENDING Request #{intake.pk} - {service_code} - {artist} - {client}"[:255]

    @staticmethod
    def _build_pending_event_description(intake: IntakeRequest, service_code: str, service_name: str) -> str:
        lines = [
            f"Pending hold for Request #{intake.pk}",
            f"Service: {service_code} - {service_name}",
            f"Client: {intake.lead}",
            f"Artist: {intake.assigned_artist.name if intake.assigned_artist else 'Unassigned'}",
            "This slot is held while payment/final confirmation is pending.",
        ]
        if intake.latest_summary:
            lines.extend(["", "Summary:", intake.latest_summary])
        return "\n".join(lines)

    @staticmethod
    def _build_event_summary(intake: IntakeRequest, service_code: str, service_name: str) -> str:
        client = str(intake.lead)
        artist = intake.assigned_artist.name if intake.assigned_artist else "Unassigned"
        return f"Request #{intake.pk} - {service_code} - {artist} - {client}"[:255]

    @staticmethod
    def _build_event_description(intake: IntakeRequest, service_code: str, service_name: str) -> str:
        lines = [
            f"Request #{intake.pk}",
            f"Service: {service_code} - {service_name}",
            f"Client: {intake.lead}",
            f"Artist: {intake.assigned_artist.name if intake.assigned_artist else 'Unassigned'}",
            f"Idea: {intake.tattoo_idea or 'Unclear'}",
        ]
        price = intake.approved_price or intake.ai_suggested_price
        if price:
            lines.append(f"Price: {price}")
        if intake.placement:
            lines.append(f"Placement: {intake.placement}")
        if intake.size_estimate_cm:
            lines.append(f"Size: {intake.size_estimate_cm}")
        if intake.color_preference:
            lines.append(f"Color: {intake.color_preference}")
        if intake.latest_summary:
            lines.extend(["", "Summary:", intake.latest_summary])
        return "\n".join(lines)

    @staticmethod
    def _record_failed_event(
        intake: IntakeRequest,
        calendar: GoogleCalendarConfig,
        start_at: datetime,
        end_at: datetime,
        summary: str,
        description: str,
        message: str,
        event_type: str = GoogleCalendarEventType.CONFIRMED_APPOINTMENT,
        existing: GoogleCalendarEvent | None = None,
    ) -> None:
        event = existing or GoogleCalendarEvent(intake=intake, calendar=calendar)
        event.event_type = event_type
        event.status = GoogleCalendarSyncStatus.FAILED
        event.start_at = start_at
        event.end_at = end_at
        event.summary = summary
        event.description = description
        event.sync_error = message
        event.save()

    @staticmethod
    def _format_http_error(exc: HttpError) -> str:
        status = getattr(getattr(exc, "resp", None), "status", None)
        content = getattr(exc, "content", b"")
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        if status:
            return f"Google Calendar API error {status}: {content or exc}"
        return f"Google Calendar API error: {content or exc}"
