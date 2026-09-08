from __future__ import annotations

import logging
from html import escape
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.exceptions import MetaAPIError, OutlookAPIError
from core.services.telegram_bot_service import TelegramBotService
from google_calendar.services import GoogleCalendarError, GoogleCalendarService
from intake.models import (
    ArtistProfile,
    ExternalArtistOffer,
    ExternalArtistOfferStatus,
    HumanDecision,
    HumanDecisionAction,
    IntakeRequest,
    IntakeStatus,
    OutboundActionType,
    PendingHoldStatus,
    ScheduleStatus,
    TelegramMessageLink,
    TelegramMessagePurpose,
)
from lead.choices import SEND_BY
from intake.outbound import ClientOutboundService
from vcita.models import VcitaScheduleProvider
from vcita.scheduling import VcitaHoldResult, VcitaScheduleResult, VcitaSchedulingError, VcitaSchedulingService

logger = logging.getLogger(__name__)


class TelegramWorkflowService:
    CALLBACK_PREFIX = "intake"

    def __init__(self):
        self.telegram = TelegramBotService()

    def send_review_card(self, intake: IntakeRequest, summary: str = "") -> dict:
        if summary:
            intake.latest_summary = summary
            intake.save(update_fields=["latest_summary", "updated_at"])
        text = self._format_review_text(intake)
        response = self.telegram.send_message(
            text=text,
            reply_markup=self._build_review_keyboard(intake),
        )
        self._store_message_link(
            intake=intake,
            purpose=TelegramMessagePurpose.GROUP_REVIEW,
            response=response,
            artist=None,
        )
        return response


    def send_pending_hold_review_card(self, intake: IntakeRequest, summary: str) -> dict:
        text = self._format_pending_hold_review_text(intake, summary)
        response = self.telegram.send_message(
            text=text,
            reply_markup=self._build_pending_hold_review_keyboard(intake),
        )
        self._store_message_link(
            intake=intake,
            purpose=TelegramMessagePurpose.GROUP_REVIEW,
            response=response,
            artist=None,
        )
        return response
    def send_artist_update(
        self,
        intake: IntakeRequest,
        text: str,
        media_items: list[dict[str, Any]] | None = None,
        purpose: str = TelegramMessagePurpose.CLIENT_UPDATE,
    ) -> dict | None:
        if not intake.assigned_artist or not intake.assigned_artist.telegram_chat_id:
            logger.warning("Cannot send artist update for intake=%s without assigned artist chat.", intake.pk)
            return None

        message = self._format_artist_update_text(intake, text, media_items or [])
        response = self.telegram.send_message(
            chat_id=intake.assigned_artist.telegram_chat_id,
            text=message,
        )
        self._store_message_link(
            intake=intake,
            purpose=purpose,
            response=response,
            artist=intake.assigned_artist,
        )
        return response

    def handle_update(self, update: dict[str, Any]) -> dict[str, Any]:
        if "callback_query" in update:
            return self._handle_callback(update["callback_query"], update)
        if "message" in update:
            return self._handle_message(update["message"], update)
        return {"ok": True, "ignored": True}

    def _handle_callback(self, callback: dict[str, Any], raw_update: dict[str, Any]) -> dict[str, Any]:
        callback_id = callback.get("id", "")
        from_user = callback.get("from", {})
        actor = self._get_artist_by_user(from_user.get("id"))

        data = callback.get("data", "")
        parsed = self._parse_callback_data(data)
        if not parsed:
            self.telegram.answer_callback_query(callback_id, "Unknown action.")
            return {"ok": False, "reason": "unknown_action"}

        action = parsed["action"]
        intake = IntakeRequest.objects.select_related("lead", "assigned_artist", "scheduled_service").get(pk=parsed["intake_id"])
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if action in ("external_accept", "external_decline"):
            return self._handle_external_artist_offer_callback(
                intake=intake,
                actor=actor,
                offer_id=int(parsed["offer_id"]),
                decision=action,
                callback_id=callback_id,
                chat_id=chat_id,
                message_id=message_id,
                original_text=message.get("text") or "",
                raw_update=raw_update,
            )

        if not actor or not actor.can_approve:
            self.telegram.answer_callback_query(callback_id, "Only Hoss/Nina can do this.")
            return {"ok": False, "reason": "unauthorized"}

        if action == "approve":
            return self._approve_ai_reply(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "reject":
            return self._reject_intake(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action in ("edit", "manual"):
            return self._mark_edit_reply(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "price":
            return self._mark_edit_price(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "hold":
            return self._hold_intake(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "keep_hold":
            return self._apply_pending_hold_decision(
                intake=intake,
                actor=actor,
                decision="keep",
                raw_update=raw_update,
                chat_id=chat_id,
                message_id=message_id,
                callback_id=callback_id,
                original_text=message.get("text") or "",
            )
        if action == "release_hold":
            return self._apply_pending_hold_decision(
                intake=intake,
                actor=actor,
                decision="release",
                raw_update=raw_update,
                chat_id=chat_id,
                message_id=message_id,
                callback_id=callback_id,
                original_text=message.get("text") or "",
            )
        if action == "schedule":
            return self._schedule_intake(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "assign":
            artist = ArtistProfile.objects.get(pk=parsed["artist_id"], is_active=True)
            return self._assign_artist(intake, actor, artist, callback_id, chat_id, message_id, raw_update)
        if action == "reassign":
            artist = ArtistProfile.objects.get(pk=parsed["artist_id"], is_active=True)
            return self._assign_artist(
                intake,
                actor,
                artist,
                callback_id,
                chat_id,
                message_id,
                raw_update,
                refresh_review_card=False,
                reassign_card=True,
            )

        self.telegram.answer_callback_query(callback_id, "Unsupported action.")
        return {"ok": False, "reason": "unsupported_action"}

    def _handle_message(self, message: dict[str, Any], raw_update: dict[str, Any]) -> dict[str, Any]:
        text = (message.get("text") or message.get("caption") or "").strip()
        from_user = message.get("from", {})
        chat = message.get("chat", {})
        artist = self._get_artist_by_user(from_user.get("id"))
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""

        if command == "/whoami":
            return self._handle_whoami(message, artist)

        if not artist:
            self.telegram.send_message(
                chat_id=chat.get("id"),
                text="Your Telegram user is not registered as an artist.",
            )
            return {"ok": False, "reason": "unknown_artist"}

        if command == "/price":
            return self._handle_price_command(message, artist, raw_update)

        if command == "/schedule":
            return self._handle_schedule_command(message, artist, raw_update)

        if command == "/reassign":
            return self._handle_reassign_command(message, artist, raw_update)

        if command == "/hold":
            return self._handle_hold_command(message, artist, raw_update)

        if command == "/keephold":
            return self._handle_keep_hold_command(message, artist, raw_update)

        if command == "/releasehold":
            return self._handle_release_hold_command(message, artist, raw_update)

        if command == "/logs":
            return self._handle_logs_command(message, artist)

        if command == "/reply":
            return self._handle_reply_command(message, artist, raw_update)

        if chat.get("type") != "private":
            return {"ok": True, "ignored": "non_private_message"}

        reply_to = message.get("reply_to_message") or {}
        if reply_to:
            link = TelegramMessageLink.objects.filter(
                telegram_chat_id=chat.get("id"),
                telegram_message_id=reply_to.get("message_id"),
                is_active=True,
            ).select_related("intake", "artist").first()
            if link:
                return self._send_artist_reply(link.intake, artist, message, raw_update)

        self.telegram.send_message(
            chat_id=chat.get("id"),
            text="Please reply directly to a request message, or use /reply REQUEST_ID your message.",
        )
        return {"ok": False, "reason": "missing_reply_target"}

    def _handle_whoami(self, message: dict[str, Any], artist: ArtistProfile | None) -> dict[str, Any]:
        from_user = message.get("from", {})
        chat = message.get("chat", {})
        if artist and chat.get("type") == "private":
            artist.telegram_chat_id = chat.get("id")
            artist.save(update_fields=["telegram_chat_id", "updated_at"])

        self.telegram.send_message(
            chat_id=chat.get("id"),
            text=(
                f"Telegram user id: <code>{from_user.get('id')}</code>\n"
                f"Telegram chat id: <code>{chat.get('id')}</code>\n"
                f"Registered artist: <b>{escape(artist.name) if artist else 'No'}</b>"
            ),
        )
        return {"ok": True, "artist_id": artist.pk if artist else None}

    def _handle_reply_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        text = (message.get("text") or "").strip()
        parts = text.split(" ", 2)
        if len(parts) < 3 or not parts[1].isdigit():
            self.telegram.send_message(
                chat_id=message.get("chat", {}).get("id"),
                text="Use /reply REQUEST_ID your message.",
            )
            return {"ok": False, "reason": "invalid_reply_command"}

        intake = IntakeRequest.objects.filter(
            pk=int(parts[1]),
            is_active=True,
        ).first()
        if not intake:
            self.telegram.send_message(
                chat_id=message.get("chat", {}).get("id"),
                text="I could not find an active request assigned to you with that ID.",
            )
            return {"ok": False, "reason": "unknown_intake"}

        message = dict(message)
        message["text"] = parts[2]
        if intake.assigned_artist_id:
            return self._send_artist_reply(intake, artist, message, raw_update)
        if artist.can_approve:
            return self._send_hoss_group_reply(intake, artist, message, raw_update)

        self.telegram.send_message(
            chat_id=message.get("chat", {}).get("id"),
            text="This request is not assigned to you.",
        )
        return {"ok": False, "reason": "wrong_artist"}

    def _handle_price_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        chat_id = message.get("chat", {}).get("id")
        if not artist.can_approve:
            self.telegram.send_message(chat_id=chat_id, text="Only Hoss can edit price.")
            return {"ok": False, "reason": "unauthorized"}

        text = (message.get("text") or "").strip()
        parts = text.split(" ", 2)
        if len(parts) < 3 or not parts[1].isdigit() or not parts[2].strip():
            self.telegram.send_message(
                chat_id=chat_id,
                text=(
                    "Use /price REQUEST_ID approved price | optional note.\n"
                    "Example: /price 1 $250-$350 | depends on final size"
                ),
            )
            return {"ok": False, "reason": "invalid_price_command"}

        intake = IntakeRequest.objects.filter(pk=int(parts[1]), is_active=True).first()
        if not intake:
            self.telegram.send_message(chat_id=chat_id, text="I could not find an active request with that ID.")
            return {"ok": False, "reason": "unknown_intake"}

        price, note = self._parse_price_text(parts[2])
        if not price:
            self.telegram.send_message(
                chat_id=chat_id,
                text="Price cannot be empty. Example: /price 1 $250-$350 | depends on final size",
            )
            return {"ok": False, "reason": "missing_price"}

        return self._update_price(intake, artist, price, note, message, raw_update)

    def _handle_schedule_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        chat_id = message.get("chat", {}).get("id")
        if not artist.can_approve:
            self.telegram.send_message(chat_id=chat_id, text="Only Hoss can schedule requests.")
            return {"ok": False, "reason": "unauthorized"}

        text = (message.get("text") or "").strip()
        parts = text.split()
        if len(parts) != 5 or not parts[1].isdigit():
            self.telegram.send_message(chat_id=chat_id, text=self._schedule_command_help())
            return {"ok": False, "reason": "invalid_schedule_command"}

        intake = IntakeRequest.objects.select_related("lead", "assigned_artist", "scheduled_service").filter(
            pk=int(parts[1]),
            is_active=True,
        ).first()
        if not intake:
            self.telegram.send_message(chat_id=chat_id, text="I could not find an active request with that ID.")
            return {"ok": False, "reason": "unknown_intake"}

        return self._schedule_intake(
            intake=intake,
            actor=artist,
            callback_id=None,
            chat_id=chat_id,
            message_id=message.get("message_id"),
            raw_update=raw_update,
            service_code=parts[2],
            appointment_date=parts[3],
            appointment_time=parts[4],
        )


    def _handle_reassign_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        chat_id = message.get("chat", {}).get("id")
        if not artist.can_approve:
            self.telegram.send_message(chat_id=chat_id, text="Only Hoss/Nina can reassign requests.")
            return {"ok": False, "reason": "unauthorized"}

        text = (message.get("text") or "").strip()
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            self.telegram.send_message(
                chat_id=chat_id,
                text="Use /reassign REQUEST_ID.\nExample: /reassign 12",
            )
            return {"ok": False, "reason": "invalid_reassign_command"}

        intake = IntakeRequest.objects.select_related("lead", "assigned_artist", "scheduled_service").filter(
            pk=int(parts[1]),
            is_active=True,
        ).first()
        if not intake:
            self.telegram.send_message(chat_id=chat_id, text="I could not find an active request with that ID.")
            return {"ok": False, "reason": "unknown_intake"}

        self.telegram.send_message(
            chat_id=chat_id,
            text=f"Select the new artist for Request #{intake.pk}.",
            reply_markup=self._build_artist_selection_keyboard(intake, action="reassign"),
        )
        return {"ok": True, "action": "reassign_options", "intake_id": intake.pk}

    def _handle_hold_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        chat_id = message.get("chat", {}).get("id")
        if not artist.can_approve:
            self.telegram.send_message(chat_id=chat_id, text="Only Hoss/Nina can hold appointment slots.")
            return {"ok": False, "reason": "unauthorized"}

        text = (message.get("text") or "").strip()
        parts = text.split()
        if len(parts) != 5 or not parts[1].isdigit():
            self.telegram.send_message(chat_id=chat_id, text=self._hold_command_help())
            return {"ok": False, "reason": "invalid_hold_command"}

        intake = IntakeRequest.objects.select_related("lead", "assigned_artist", "scheduled_service").filter(
            pk=int(parts[1]),
            is_active=True,
        ).first()
        if not intake:
            self.telegram.send_message(chat_id=chat_id, text="I could not find an active request with that ID.")
            return {"ok": False, "reason": "unknown_intake"}

        return self._hold_intake(
            intake=intake,
            actor=artist,
            callback_id=None,
            chat_id=chat_id,
            message_id=message.get("message_id"),
            raw_update=raw_update,
            service_code=parts[2],
            appointment_date=parts[3],
            appointment_time=parts[4],
        )

    def _handle_keep_hold_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        return self._handle_pending_hold_decision(
            message=message,
            artist=artist,
            raw_update=raw_update,
            decision="keep",
        )

    def _handle_release_hold_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        return self._handle_pending_hold_decision(
            message=message,
            artist=artist,
            raw_update=raw_update,
            decision="release",
        )

    def _handle_pending_hold_decision(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
        raw_update: dict[str, Any],
        decision: str,
    ) -> dict[str, Any]:
        chat_id = message.get("chat", {}).get("id")
        if not artist.can_approve:
            self.telegram.send_message(chat_id=chat_id, text="Only Hoss/Nina can keep or release pending holds.")
            return {"ok": False, "reason": "unauthorized"}

        command = "/keephold" if decision == "keep" else "/releasehold"
        parts = (message.get("text") or "").strip().split()
        if len(parts) != 2 or not parts[1].isdigit():
            self.telegram.send_message(chat_id=chat_id, text=f"Use {command} REQUEST_ID. Example: {command} 12")
            return {"ok": False, "reason": "invalid_pending_hold_decision"}

        intake = IntakeRequest.objects.select_related("lead", "assigned_artist", "scheduled_service").filter(
            pk=int(parts[1]),
            is_active=True,
        ).first()
        if not intake:
            self.telegram.send_message(chat_id=chat_id, text="I could not find an active request with that ID.")
            return {"ok": False, "reason": "unknown_intake"}

        return self._apply_pending_hold_decision(
            intake=intake,
            actor=artist,
            decision=decision,
            raw_update=raw_update,
            chat_id=chat_id,
            message_id=message.get("message_id"),
        )

    def _apply_pending_hold_decision(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        decision: str,
        raw_update: dict[str, Any],
        chat_id: int | None,
        message_id: int | None,
        callback_id: str | None = None,
        original_text: str = "",
    ) -> dict[str, Any]:
        if intake.pending_hold_status != PendingHoldStatus.ACTIVE:
            response_text = f"Request #{intake.pk}: this pending hold has already been handled."
            if callback_id:
                self.telegram.answer_callback_query(callback_id, "This pending hold has already been handled.", show_alert=True)
                self._mark_pending_hold_review_card_handled(
                    chat_id,
                    message_id,
                    original_text,
                    "Status: This pending hold was already handled.",
                )
            else:
                self.telegram.send_message(chat_id=chat_id, text=response_text)
            return {"ok": False, "reason": "pending_hold_already_handled", "intake_id": intake.pk}

        scheduler = VcitaSchedulingService()
        try:
            if decision == "keep":
                expires_at = scheduler.keep_pending_hold(intake)
                expires_label = timezone.localtime(expires_at).strftime("%Y-%m-%d %H:%M")
                note = f"Pending hold kept until {expires_label}."
                action = HumanDecisionAction.KEEP_HOLD
                response_text = f"Request #{intake.pk}: pending hold kept until {expires_label}."
                status_text = f"Status: Hold kept by {actor.name} until {expires_label}."
            else:
                released_event_ids = scheduler.release_pending_hold_manually(intake)
                note = "Pending hold released."
                if released_event_ids:
                    note += " Released Google event IDs: " + ", ".join(released_event_ids)
                action = HumanDecisionAction.RELEASE_HOLD
                response_text = f"Request #{intake.pk}: pending hold released."
                status_text = f"Status: Hold released by {actor.name}."
        except VcitaSchedulingError as exc:
            if callback_id:
                self.telegram.answer_callback_query(callback_id, str(exc)[:200], show_alert=True)
                self._clear_pending_hold_review_buttons(chat_id, message_id)
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk}: could not {decision} pending hold.\nReason: {escape(str(exc))}",
            )
            return {"ok": False, "reason": f"{decision}_hold_failed", "intake_id": intake.pk}

        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=action,
            note=note,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id or "",
            raw_update=raw_update,
        )
        if callback_id:
            self.telegram.answer_callback_query(callback_id, response_text[:200])
            self._mark_pending_hold_review_card_handled(chat_id, message_id, original_text, status_text)
        self.telegram.send_message(chat_id=chat_id, text=response_text)
        return {"ok": True, "action": decision + "_hold", "intake_id": intake.pk}
    def _handle_logs_command(
        self,
        message: dict[str, Any],
        artist: ArtistProfile,
    ) -> dict[str, Any]:
        chat_id = message.get("chat", {}).get("id")
        if not artist.can_approve:
            self.telegram.send_message(chat_id=chat_id, text="Only Hoss can view request logs.")
            return {"ok": False, "reason": "unauthorized"}

        parsed = self._parse_logs_command((message.get("text") or "").strip())
        if parsed is None:
            self.telegram.send_message(chat_id=chat_id, text=self._logs_command_help())
            return {"ok": False, "reason": "invalid_logs_command"}

        intake_id, limit = parsed
        decisions = HumanDecision.objects.select_related("intake", "actor", "assigned_artist")
        if intake_id is not None:
            decisions = decisions.filter(intake_id=intake_id)
            if not IntakeRequest.objects.filter(pk=intake_id).exists():
                self.telegram.send_message(chat_id=chat_id, text=f"I could not find Request #{intake_id}.")
                return {"ok": False, "reason": "unknown_intake"}

        decisions = decisions.order_by("-created_at")[:limit]
        text = self._format_logs_response(list(decisions), intake_id, limit)
        self.telegram.send_message(chat_id=chat_id, text=text)
        return {"ok": True, "action": "logs", "intake_id": intake_id, "limit": limit}

    @transaction.atomic
    def _approve_ai_reply(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        if not intake.latest_draft_reply.strip():
            self.telegram.answer_callback_query(callback_id, "No AI draft reply is available.")
            return {"ok": False, "reason": "missing_draft_reply"}

        if not self._send_client_reply_or_notify(
            intake=intake,
            text=intake.latest_draft_reply,
            chat_id=chat_id,
            callback_id=callback_id,
            action_type=OutboundActionType.HOSS_APPROVED_REPLY,
            actor=actor,
            send_by=SEND_BY.AGENT,
        ):
            return {"ok": False, "reason": "client_send_failed"}
        intake.status = IntakeStatus.APPROVED
        intake.save(update_fields=["status", "updated_at"])
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.APPROVE_AI_REPLY,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        self._refresh_review_card(intake, chat_id, message_id, f"Status: AI reply approved by {actor.name}.")
        self.telegram.answer_callback_query(callback_id, "AI reply sent to client.")
        self.telegram.send_message(chat_id=chat_id, text=f"Request #{intake.pk}: AI reply approved and sent.")
        return {"ok": True, "action": "approve", "intake_id": intake.pk}

    @transaction.atomic
    def _assign_artist(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        artist: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        raw_update: dict[str, Any],
        refresh_review_card: bool = True,
        reassign_card: bool = False,
    ) -> dict[str, Any]:
        scheduled_reassign = self._prepare_scheduled_reassign(intake, artist)
        if scheduled_reassign:
            ok, message = scheduled_reassign
            if not ok:
                if reassign_card:
                    self._mark_short_action_card_handled(chat_id, message_id, message)
                elif refresh_review_card:
                    self._refresh_review_card(intake, chat_id, message_id, message)
                self.telegram.answer_callback_query(callback_id, message[:200], show_alert=True)
                self.telegram.send_message(chat_id=chat_id, text=message)
                return {"ok": False, "reason": "scheduled_reassign_blocked", "intake_id": intake.pk, "artist_id": artist.pk}

        if not artist.can_approve:
            return self._offer_external_artist(
                intake,
                actor,
                artist,
                callback_id,
                chat_id,
                message_id,
                raw_update,
                refresh_review_card=refresh_review_card,
                reassign_card=reassign_card,
            )

        previous_artist = intake.assigned_artist
        intake.assigned_artist = artist
        intake.status = IntakeStatus.ASSIGNED
        intake.save(update_fields=["assigned_artist", "status", "updated_at"])
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            assigned_artist=artist,
            action=HumanDecisionAction.ASSIGN_ARTIST,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        if previous_artist and previous_artist.pk != artist.pk and previous_artist.telegram_chat_id:
            self.telegram.send_message(
                chat_id=previous_artist.telegram_chat_id,
                text=f"Request #{intake.pk} has been reassigned to {artist.name}.",
            )
        if scheduled_reassign:
            warning = self._sync_scheduled_reassign(intake, previous_artist, artist)
            if warning:
                self.telegram.send_message(
                    chat_id=chat_id,
                    text=f"Request #{intake.pk}: reassigned to {artist.name}, but calendar sync needs review. Reason: {warning}",
                )
        if artist.telegram_chat_id:
            self.send_artist_update(
                intake=intake,
                text="You have been assigned to this request.",
                purpose=TelegramMessagePurpose.ARTIST_ASSIGNMENT,
            )
            if refresh_review_card:
                self._refresh_review_card(intake, chat_id, message_id, f"Status: Assigned to {artist.name} by {actor.name}.")
            elif reassign_card:
                self._mark_short_action_card_handled(chat_id, message_id, f"Request #{intake.pk} reassigned to {artist.name}.")
            self.telegram.answer_callback_query(callback_id, f"Assigned to {artist.name}.")
            self.telegram.send_message(chat_id=chat_id, text=f"Request #{intake.pk} assigned to {escape(artist.name)}.")
        else:
            if refresh_review_card:
                self._refresh_review_card(intake, chat_id, message_id, f"Status: Assigned to {artist.name}, but /whoami is still needed.")
            elif reassign_card:
                self._mark_short_action_card_handled(chat_id, message_id, f"Request #{intake.pk} reassigned to {artist.name}, but /whoami is still needed.")
            self.telegram.answer_callback_query(callback_id, f"{artist.name} has no private chat ID yet.")
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk} assigned to {escape(artist.name)}, but they need to start the bot and run /whoami.",
            )
        return {"ok": True, "action": "assign", "intake_id": intake.pk, "artist_id": artist.pk}

    def _offer_external_artist(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        artist: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        raw_update: dict[str, Any],
        refresh_review_card: bool = True,
        reassign_card: bool = False,
    ) -> dict[str, Any]:
        if not artist.telegram_chat_id:
            self.telegram.answer_callback_query(callback_id, f"{artist.name} has no private chat ID yet.")
            self.telegram.send_message(
                chat_id=chat_id,
                text=(
                    f"Request #{intake.pk}: could not offer this request to {escape(artist.name)}.\n"
                    "Reason: the artist needs to start the bot and run /whoami first."
                ),
            )
            return {"ok": False, "reason": "missing_artist_chat", "intake_id": intake.pk, "artist_id": artist.pk}

        existing_offer = ExternalArtistOffer.objects.filter(
            intake=intake,
            artist=artist,
            status=ExternalArtistOfferStatus.OFFERED,
        ).first()
        if existing_offer:
            if refresh_review_card:
                self._refresh_review_card(intake, chat_id, message_id, f"Status: Already offered to {artist.name}. Waiting for Accept or Decline.")
            elif reassign_card:
                self._mark_short_action_card_handled(chat_id, message_id, f"Request #{intake.pk} is already offered to {artist.name}.")
            self.telegram.answer_callback_query(callback_id, f"{artist.name} already has an active offer.")
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk} is already offered to {escape(artist.name)}. Waiting for Accept or Decline.",
            )
            return {"ok": False, "reason": "offer_already_active", "intake_id": intake.pk, "artist_id": artist.pk}

        safe_brief = self._format_external_artist_offer_text(intake, artist)
        offer = ExternalArtistOffer.objects.create(
            intake=intake,
            artist=artist,
            offered_by=actor,
            safe_brief=safe_brief,
            raw_update=raw_update,
        )
        response = self.telegram.send_message(
            chat_id=artist.telegram_chat_id,
            text=safe_brief,
            reply_markup=self._build_external_artist_offer_keyboard(intake, offer),
        )
        telegram_message = response.get("result", {})
        offer.telegram_chat_id = telegram_message.get("chat", {}).get("id")
        offer.telegram_message_id = telegram_message.get("message_id")
        offer.save(update_fields=["telegram_chat_id", "telegram_message_id", "updated_at"])
        self._store_message_link(
            intake=intake,
            purpose=TelegramMessagePurpose.EXTERNAL_ARTIST_OFFER,
            response=response,
            artist=artist,
        )
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            assigned_artist=artist,
            action=HumanDecisionAction.EXTERNAL_ARTIST_OFFER,
            note=f"Offer sent to {artist.name}.",
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        if refresh_review_card:
            self._refresh_review_card(intake, chat_id, message_id, f"Status: Offered to {artist.name}. Waiting for Accept or Decline.")
        elif reassign_card:
            self._mark_short_action_card_handled(chat_id, message_id, f"Request #{intake.pk} offered to {artist.name}. Waiting for Accept or Decline.")
        self.telegram.answer_callback_query(callback_id, f"Offer sent to {artist.name}.")
        self.telegram.send_message(
            chat_id=chat_id,
            text=f"Request #{intake.pk} offered to {escape(artist.name)}. Waiting for Accept or Decline.",
        )
        return {"ok": True, "action": "external_artist_offer", "intake_id": intake.pk, "artist_id": artist.pk}

    def _prepare_scheduled_reassign(self, intake: IntakeRequest, new_artist: ArtistProfile) -> tuple[bool, str] | None:
        if not self._is_scheduled_intake(intake) or intake.assigned_artist_id == new_artist.pk:
            return None

        provider = self._scheduled_provider(intake)
        if provider == VcitaScheduleProvider.VCITA:
            if new_artist.can_approve:
                return True, f"Request #{intake.pk} reassigned to {new_artist.name}."
            return False, (
                f"Request #{intake.pk} is already scheduled in vCita. "
                "Please reschedule or cancel it before assigning an external artist."
            )

        if provider == VcitaScheduleProvider.GOOGLE_ONLY:
            if new_artist.can_approve:
                return False, (
                    f"Request #{intake.pk} is already scheduled for an external artist. "
                    "Please reschedule it with a Hoss/Nina service before assigning Hoss or Nina."
                )
            try:
                start_local = self._scheduled_start(intake)
                GoogleCalendarService().preflight_artist_schedule(
                    intake=intake,
                    artist=new_artist,
                    start_at=start_local,
                    duration_minutes=VcitaSchedulingService.DEFAULT_DURATION_MINUTES,
                )
            except (GoogleCalendarError, VcitaSchedulingError) as exc:
                return False, (
                    f"Request #{intake.pk} is already scheduled for {intake.scheduled_date} at {intake.scheduled_time}. "
                    f"{new_artist.name} is not available or cannot be checked. Reason: {exc}"
                )
            return True, f"Request #{intake.pk} reassigned to {new_artist.name}."

        return None

    @staticmethod
    def _is_scheduled_intake(intake: IntakeRequest) -> bool:
        return bool(
            intake.scheduled_date
            and intake.scheduled_time
            and intake.schedule_status in {ScheduleStatus.SCHEDULED, ScheduleStatus.RESCHEDULED}
        )

    @staticmethod
    def _scheduled_provider(intake: IntakeRequest) -> str:
        if intake.vcita_booking_uid:
            return VcitaScheduleProvider.VCITA
        if intake.scheduled_service and (
            intake.scheduled_service.schedule_provider == VcitaScheduleProvider.GOOGLE_ONLY
            or intake.scheduled_service.code.upper() in {"TA", "TC"}
        ):
            return VcitaScheduleProvider.GOOGLE_ONLY
        if intake.scheduled_service_code.upper() in {"TA", "TC"}:
            return VcitaScheduleProvider.GOOGLE_ONLY
        return VcitaScheduleProvider.VCITA

    @staticmethod
    def _scheduled_start(intake: IntakeRequest):
        scheduler = VcitaSchedulingService()
        account = scheduler.account
        timezone_name = account.default_timezone if account else "Europe/Amsterdam"
        return scheduler._parse_local_start(intake.scheduled_date, intake.scheduled_time, timezone_name)

    def _sync_scheduled_reassign(
        self,
        intake: IntakeRequest,
        previous_artist: ArtistProfile | None,
        new_artist: ArtistProfile,
    ) -> str:
        if not self._is_scheduled_intake(intake):
            return ""
        if self._scheduled_provider(intake) != VcitaScheduleProvider.GOOGLE_ONLY:
            return ""
        if new_artist.can_approve:
            return ""

        start_local = self._scheduled_start(intake)
        google_calendar = GoogleCalendarService()
        sync_result = google_calendar.sync_confirmed_schedule(
            intake=intake,
            start_at=start_local,
            service_code=intake.scheduled_service_code or "TA/TC",
            service_name=intake.scheduled_service_name or "External artist appointment",
            duration_minutes=VcitaSchedulingService.DEFAULT_DURATION_MINUTES,
            include_shared_vcita=False,
        )
        release_result = google_calendar.release_confirmed_artist_events_except(intake, keep_artist=new_artist)
        warnings = [*sync_result.warnings, *release_result.warnings]
        return " | ".join(warnings)


    @transaction.atomic
    def _handle_external_artist_offer_callback(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile | None,
        offer_id: int,
        decision: str,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        original_text: str,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        if not actor:
            self.telegram.answer_callback_query(callback_id, "Your Telegram user is not registered as an artist.", show_alert=True)
            return {"ok": False, "reason": "unknown_artist", "offer_id": offer_id}

        offer = ExternalArtistOffer.objects.select_for_update().select_related("intake", "artist").get(pk=offer_id)
        if offer.intake_id != intake.pk:
            self.telegram.answer_callback_query(callback_id, "This offer does not match the request.", show_alert=True)
            return {"ok": False, "reason": "offer_intake_mismatch", "offer_id": offer_id}
        if actor.pk != offer.artist_id:
            self.telegram.answer_callback_query(callback_id, "Only the offered artist can respond to this.", show_alert=True)
            return {"ok": False, "reason": "wrong_artist", "offer_id": offer_id}
        if offer.status != ExternalArtistOfferStatus.OFFERED:
            self.telegram.answer_callback_query(callback_id, "This offer has already been handled.", show_alert=True)
            self._mark_external_offer_card_handled(chat_id, message_id, original_text, f"Status: Already {offer.get_status_display()} by {offer.artist.name}.")
            return {"ok": False, "reason": "offer_already_handled", "offer_id": offer_id}

        if decision == "external_accept":
            return self._accept_external_artist_offer(offer, actor, callback_id, chat_id, message_id, original_text, raw_update)
        return self._decline_external_artist_offer(offer, actor, callback_id, chat_id, message_id, original_text, raw_update)

    def _accept_external_artist_offer(
        self,
        offer: ExternalArtistOffer,
        actor: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        original_text: str,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        now = timezone.now()
        intake = offer.intake
        scheduled_reassign = self._prepare_scheduled_reassign(intake, actor)
        if scheduled_reassign:
            ok, message = scheduled_reassign
            if not ok:
                self.telegram.answer_callback_query(callback_id, message[:200], show_alert=True)
                self._mark_external_offer_card_handled(chat_id, message_id, original_text, f"Status: Could not accept. {message}")
                self.telegram.send_message(chat_id=chat_id, text=f"Request #{intake.pk}: could not accept this request. {message}")
                self.telegram.send_message(text=message)
                return {"ok": False, "reason": "scheduled_reassign_blocked", "intake_id": intake.pk, "artist_id": actor.pk}
        previous_artist = intake.assigned_artist
        intake.assigned_artist = actor
        intake.status = IntakeStatus.ASSIGNED
        intake.save(update_fields=["assigned_artist", "status", "updated_at"])
        offer.status = ExternalArtistOfferStatus.ACCEPTED
        offer.responded_at = now
        offer.client_contact_released_at = now
        offer.raw_update = raw_update
        offer.save(update_fields=["status", "responded_at", "client_contact_released_at", "raw_update", "updated_at"])
        ExternalArtistOffer.objects.filter(
            intake=intake,
            status=ExternalArtistOfferStatus.OFFERED,
        ).exclude(pk=offer.pk).update(status=ExternalArtistOfferStatus.CANCELLED, updated_at=now)
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            assigned_artist=actor,
            action=HumanDecisionAction.EXTERNAL_ARTIST_ACCEPT,
            note=f"{actor.name} accepted the artist offer.",
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        if scheduled_reassign:
            warning = self._sync_scheduled_reassign(intake, previous_artist, actor)
            if warning:
                self.telegram.send_message(text=f"Request #{intake.pk}: {actor.name} accepted, but calendar sync needs review. Reason: {warning}")

        self.telegram.answer_callback_query(callback_id, "Accepted.")
        self._mark_external_offer_card_handled(chat_id, message_id, original_text, f"Status: Accepted by {actor.name}.")
        if previous_artist and previous_artist.pk != actor.pk and previous_artist.telegram_chat_id:
            self.telegram.send_message(
                chat_id=previous_artist.telegram_chat_id,
                text=f"Request #{intake.pk} has been reassigned to {actor.name}.",
            )
        self.telegram.send_message(chat_id=chat_id, text=self._format_external_artist_contact_text(intake, actor))
        self.telegram.send_message(
            text=f"Request #{intake.pk}: {escape(actor.name)} accepted. Client name/email released to the artist.",
        )
        client_message = (
            f"Good news, {actor.name} has accepted your tattoo request. "
            "They will contact you by email with the next steps."
        )
        self._send_client_reply_or_notify(
            intake=intake,
            text=client_message,
            chat_id=None,
            action_type=OutboundActionType.EXTERNAL_ARTIST_ACCEPTED,
            actor=actor,
            send_by=SEND_BY.AGENT,
        )
        return {"ok": True, "action": "external_artist_accept", "intake_id": intake.pk, "artist_id": actor.pk}

    def _decline_external_artist_offer(
        self,
        offer: ExternalArtistOffer,
        actor: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        original_text: str,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        now = timezone.now()
        intake = offer.intake
        offer.status = ExternalArtistOfferStatus.DECLINED
        offer.responded_at = now
        offer.raw_update = raw_update
        offer.save(update_fields=["status", "responded_at", "raw_update", "updated_at"])
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            assigned_artist=actor,
            action=HumanDecisionAction.EXTERNAL_ARTIST_DECLINE,
            note=f"{actor.name} declined the artist offer.",
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        self.telegram.answer_callback_query(callback_id, "Declined.")
        self._mark_external_offer_card_handled(chat_id, message_id, original_text, f"Status: Declined by {actor.name}.")
        self.telegram.send_message(chat_id=chat_id, text=f"Request #{intake.pk}: you declined this request.")
        self.telegram.send_message(
            text=f"Request #{intake.pk}: {escape(actor.name)} declined. Please assign another artist or handle it manually.",
        )
        return {"ok": True, "action": "external_artist_decline", "intake_id": intake.pk, "artist_id": actor.pk}

    @transaction.atomic
    def _reject_intake(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        intake.status = IntakeStatus.REJECTED
        intake.save(update_fields=["status", "updated_at"])
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.REJECT,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        self._refresh_review_card(intake, chat_id, message_id, f"Status: AI reply rejected by {actor.name}.")
        self.telegram.answer_callback_query(callback_id, "Marked rejected.")
        self.telegram.send_message(chat_id=chat_id, text=f"Request #{intake.pk} marked rejected.")
        return {"ok": True, "action": "reject", "intake_id": intake.pk}

    @transaction.atomic
    def _mark_edit_reply(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        intake.status = IntakeStatus.WAITING_FOR_HUMAN
        intake.save(update_fields=["status", "updated_at"])
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.EDIT_REPLY,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        self._refresh_review_card(
            intake,
            chat_id,
            message_id,
            f"Status: Edit reply selected by {actor.name}. Use /reply {intake.pk} your message.",
        )
        self.telegram.answer_callback_query(callback_id, "Edit mode selected.")
        self.telegram.send_message(
            chat_id=chat_id,
            text=f"Request #{intake.pk}: send an edited reply with /reply {intake.pk} your message.",
        )
        return {"ok": True, "action": "edit", "intake_id": intake.pk}

    @transaction.atomic
    def _mark_edit_price(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.EDIT_PRICE,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id,
            raw_update=raw_update,
        )
        self.telegram.answer_callback_query(callback_id, "Price edit selected.")
        self.telegram.send_message(
            chat_id=chat_id,
            text=(
                f"Request #{intake.pk}: send the approved price with:\n"
                f"<code>/price {intake.pk} $250 | optional note</code>\n\n"
                "Examples:\n"
                f"<code>/price {intake.pk} $250</code>\n"
                f"<code>/price {intake.pk} $250-$350 | depends on final size</code>"
            ),
        )
        return {"ok": True, "action": "edit_price", "intake_id": intake.pk}

    @transaction.atomic
    def _update_price(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        price: str,
        note: str,
        message: dict[str, Any],
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        intake.approved_price = price
        intake.price_note = note
        intake.price_approved_by = actor
        intake.price_approved_at = timezone.now()
        intake.save(
            update_fields=[
                "approved_price",
                "price_note",
                "price_approved_by",
                "price_approved_at",
                "updated_at",
            ]
        )
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.EDIT_PRICE,
            note=f"Price: {price}\nNote: {note}" if note else f"Price: {price}",
            telegram_chat_id=message.get("chat", {}).get("id"),
            telegram_message_id=message.get("message_id"),
            raw_update=raw_update,
        )

        confirmation = f"Request #{intake.pk} price updated.\nPrice: {escape(price)}"
        if note:
            confirmation = f"{confirmation}\nNote: {escape(note)}"
        self.telegram.send_message(chat_id=message.get("chat", {}).get("id"), text=confirmation)
        return {"ok": True, "action": "price_updated", "intake_id": intake.pk}

    def _schedule_intake(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        callback_id: str | None,
        chat_id: int | None,
        message_id: int | None,
        raw_update: dict[str, Any],
        service_code: str = "",
        appointment_date: str | None = None,
        appointment_time: str | None = None,
    ) -> dict[str, Any]:
        if not service_code:
            message = VcitaSchedulingService.service_code_help()
            if callback_id:
                self.telegram.answer_callback_query(callback_id, "Please select a service code first.", show_alert=True)
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk}: {escape(message)}",
            )
            return {"ok": False, "reason": "missing_service_code", "intake_id": intake.pk}
        if not intake.assigned_artist_id:
            message = "Please assign an artist first, then schedule this request."
            if callback_id:
                self.telegram.answer_callback_query(callback_id, message, show_alert=True)
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk}: {message}",
            )
            return {"ok": False, "reason": "missing_artist_assignment", "intake_id": intake.pk}

        try:
            result = VcitaSchedulingService().schedule_intake(
                intake=intake,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                service_code=service_code,
            )
        except VcitaSchedulingError as exc:
            if callback_id:
                self.telegram.answer_callback_query(callback_id, str(exc)[:200], show_alert=True)
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk}: could not schedule.\nReason: {escape(str(exc))}",
            )
            return {"ok": False, "reason": "schedule_failed", "intake_id": intake.pk}

        schedule_note = f"Scheduled {result.service.code} for {result.requested_date} {result.requested_time}. "
        if result.booking_uid:
            schedule_note += f"vCita booking: {result.booking_uid}"
        else:
            schedule_note += "Google Calendar only"
        schedule_note += self._format_google_warning_note(result.google_sync_warnings)

        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.SCHEDULE,
            note=schedule_note,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_callback_id=callback_id or "",
            raw_update=raw_update,
        )
        if callback_id:
            self.telegram.answer_callback_query(callback_id, "Request scheduled.")
        self.telegram.send_message(chat_id=chat_id, text=self._format_schedule_group_confirmation(result))

        client_notice = self._format_client_schedule_notice(result)
        client_sent = self._send_client_reply_or_notify(
            intake=result.intake,
            text=client_notice,
            chat_id=chat_id,
            action_type=OutboundActionType.SCHEDULE_NOTIFICATION,
            actor=actor,
            send_by=SEND_BY.AGENT,
        )
        if result.intake.assigned_artist and result.intake.assigned_artist.telegram_chat_id:
            self.send_artist_update(
                intake=result.intake,
                text=(
                    f"This request has been {'rescheduled' if result.was_reschedule else 'scheduled'} "
                    f"for {result.service.code} on {result.requested_date} at {result.requested_time}."
                ),
            )
        return {
            "ok": True,
            "action": "schedule",
            "intake_id": intake.pk,
            "booking_uid": result.booking_uid,
            "client_notified": client_sent,
        }

    @transaction.atomic
    def _send_hoss_group_reply(
        self,
        intake: IntakeRequest,
        actor: ArtistProfile,
        message: dict[str, Any],
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        text = (message.get("text") or "").strip()
        if not self._send_client_reply_or_notify(
            intake=intake,
            text=text,
            chat_id=message.get("chat", {}).get("id"),
            action_type=OutboundActionType.HOSS_EDITED_REPLY,
            actor=actor,
            send_by=SEND_BY.AGENT,
        ):
            return {"ok": False, "reason": "client_send_failed"}
        intake.status = IntakeStatus.APPROVED
        intake.save(update_fields=["status", "updated_at"])
        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.EDIT_REPLY,
            note=text,
            telegram_chat_id=message.get("chat", {}).get("id"),
            telegram_message_id=message.get("message_id"),
            raw_update=raw_update,
        )
        self.telegram.send_message(
            chat_id=message.get("chat", {}).get("id"),
            text=f"Edited reply sent to client for Request #{intake.pk}.",
        )
        return {"ok": True, "action": "edit_reply_sent", "intake_id": intake.pk}

    @transaction.atomic
    def _send_artist_reply(
        self,
        intake: IntakeRequest,
        artist: ArtistProfile,
        message: dict[str, Any],
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        if intake.assigned_artist_id != artist.pk:
            self.telegram.send_message(
                chat_id=message.get("chat", {}).get("id"),
                text="This request is not assigned to you.",
            )
            return {"ok": False, "reason": "wrong_artist"}

        text = (message.get("text") or message.get("caption") or "").strip()
        media_items = self._extract_media_items(message)
        if not self._send_client_reply_or_notify(
            intake=intake,
            text=text,
            chat_id=message.get("chat", {}).get("id"),
            media_items=media_items,
            action_type=OutboundActionType.ARTIST_REPLY,
            actor=artist,
            send_by=SEND_BY.AGENT,
        ):
            return {"ok": False, "reason": "client_send_failed"}
        HumanDecision.objects.create(
            intake=intake,
            actor=artist,
            action=HumanDecisionAction.ARTIST_REPLY,
            note=text,
            telegram_chat_id=message.get("chat", {}).get("id"),
            telegram_message_id=message.get("message_id"),
            raw_update=raw_update,
        )
        self.telegram.send_message(
            chat_id=message.get("chat", {}).get("id"),
            text=f"Sent to client for Request #{intake.pk}.",
        )
        return {"ok": True, "action": "artist_reply", "intake_id": intake.pk}

    def _send_client_reply_or_notify(
        self,
        intake: IntakeRequest,
        text: str,
        chat_id: int | None,
        callback_id: str | None = None,
        media_items: list[dict[str, Any]] | None = None,
        action_type: str = OutboundActionType.AI_AUTO_REPLY,
        actor: ArtistProfile | None = None,
        send_by: str | None = None,
    ) -> bool:
        try:
            ClientOutboundService.send_intake_reply(
                intake,
                text,
                media_items=media_items,
                action_type=action_type,
                actor=actor,
                send_by=send_by,
            )
        except (ValueError, MetaAPIError, OutlookAPIError) as exc:
            logger.warning("Could not send client reply for intake=%s: %s", intake.pk, exc)
            if callback_id:
                self.telegram.answer_callback_query(callback_id, "Could not send reply to client.")
            self.telegram.send_message(
                chat_id=chat_id,
                text=(
                    f"Request #{intake.pk}: could not send reply to client.\n"
                    f"Reason: {escape(str(exc))}"
                ),
            )
            return False
        return True

    def _extract_media_items(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        media_items: list[dict[str, Any]] = []
        caption = message.get("caption", "")

        if message.get("photo"):
            photo = message["photo"][-1]
            downloaded = self.telegram.download_file(photo["file_id"], original_name="photo.jpg")
            media_items.append({
                "type": "image",
                "url": downloaded["url"],
                "file_name": downloaded["file_name"],
                "caption": caption,
            })

        if message.get("document"):
            document = message["document"]
            downloaded = self.telegram.download_file(
                document["file_id"],
                original_name=document.get("file_name", "document"),
            )
            media_items.append({
                "type": "document",
                "url": downloaded["url"],
                "file_name": downloaded["file_name"],
                "caption": caption,
            })

        return media_items



    def _build_external_artist_offer_keyboard(self, intake: IntakeRequest, offer: ExternalArtistOffer) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "Accept",
                        "callback_data": f"{self.CALLBACK_PREFIX}:external_accept:{intake.pk}:{offer.pk}",
                    },
                    {
                        "text": "Decline",
                        "callback_data": f"{self.CALLBACK_PREFIX}:external_decline:{intake.pk}:{offer.pk}",
                    },
                ]
            ]
        }

    def _format_external_artist_offer_text(self, intake: IntakeRequest, artist: ArtistProfile) -> str:
        detail_lines = [
            f"Idea: {escape(intake.tattoo_idea or 'Unclear')}",
            f"Price: {escape(intake.approved_price or intake.ai_suggested_price or 'Not approved')}",
        ]
        if intake.placement:
            detail_lines.append(f"Placement: {escape(intake.placement)}")
        if intake.size_estimate_cm:
            detail_lines.append(f"Size: {escape(intake.size_estimate_cm)}")
        if intake.color_preference:
            detail_lines.append(f"Color: {escape(intake.color_preference)}")
        if intake.style_tags:
            detail_lines.append(f"Style: {escape(', '.join(intake.style_tags))}")
        if intake.appointment_date and intake.appointment_time:
            detail_lines.append(f"Preferred schedule: {escape(intake.appointment_date)} at {escape(intake.appointment_time)}")
        if intake.pending_hold_date and intake.pending_hold_time:
            detail_lines.append(f"Pending hold: {escape(intake.pending_hold_date)} at {escape(intake.pending_hold_time)}")
        media_lines = self._external_offer_media_lines(intake)
        if media_lines:
            detail_lines.extend(media_lines)
        summary_section = ""
        if intake.latest_summary:
            summary_section = f"\n\n<b>Summary</b>\n{escape(intake.latest_summary)}"
        return (
            f"<b>Artist offer for Request #{intake.pk}</b>\n"
            f"Artist: {escape(artist.name)}\n"
            "Client contact is hidden until you accept.\n\n"
            f"{chr(10).join(detail_lines)}"
            f"{summary_section}\n\n"
            "Please choose one option."
        )

    def _format_external_artist_contact_text(self, intake: IntakeRequest, artist: ArtistProfile) -> str:
        lead = intake.lead
        name = lead.name or "Not provided"
        email = lead.email or "Not provided"
        return (
            f"<b>Request #{intake.pk}: client contact released</b>\n"
            f"Client name: {escape(name)}\n"
            f"Client email: {escape(email)}\n"
            "Client phone is hidden.\n\n"
            "You are now assigned to this request. Reply to future bot updates for this request, or use:\n"
            f"<code>/reply {intake.pk} your message</code>"
        )

    def _external_offer_media_lines(self, intake: IntakeRequest) -> list[str]:
        if not intake.last_incoming_message_id:
            return []
        lines = []
        for media in intake.last_incoming_message.media_files.all()[:5]:
            url = media.download_url
            if not url and media.file:
                try:
                    url = media.file.url
                except Exception:
                    url = ""
            if url:
                label = media.file_name or media.media_type or "file"
                lines.append(f"Reference: {escape(label)} - {escape(url)}")
        return lines

    def _mark_external_offer_card_handled(
        self,
        chat_id: int | None,
        message_id: int | None,
        original_text: str,
        status_text: str,
    ) -> None:
        if not chat_id or not message_id:
            return
        text = escape(original_text.strip()) if original_text.strip() else "Artist offer handled."
        if "Status:" not in original_text:
            text = f"{text}\n\n<b>{escape(status_text)}</b>"
        try:
            self.telegram.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=None)
        except Exception:
            logger.exception("Could not edit external artist offer card after decision.")
            try:
                self.telegram.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            except Exception:
                logger.exception("Could not clear external artist offer buttons.")
    def _build_pending_hold_review_keyboard(self, intake: IntakeRequest) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "Keep Hold",
                        "callback_data": f"{self.CALLBACK_PREFIX}:keep_hold:{intake.pk}",
                    },
                    {
                        "text": "Release Hold",
                        "callback_data": f"{self.CALLBACK_PREFIX}:release_hold:{intake.pk}",
                    },
                ]
            ]
        }

    def _format_pending_hold_review_text(self, intake: IntakeRequest, summary: str) -> str:
        expires_at = (
            timezone.localtime(intake.pending_hold_expires_at).strftime("%Y-%m-%d %H:%M")
            if intake.pending_hold_expires_at
            else "Unknown"
        )
        return (
            f"<b>Pending hold needs review: Request #{intake.pk}</b>\n"
            f"Expired/review due: {escape(expires_at)}\n"
            f"Held time: {escape(intake.pending_hold_date)} at {escape(intake.pending_hold_time)}\n"
            f"Service: {escape(intake.pending_hold_service_code)} - {escape(intake.pending_hold_service_name)}\n"
            f"Artist: {escape(intake.assigned_artist.name if intake.assigned_artist else 'Unassigned')}\n\n"
            f"<b>Summary</b>\n{escape(summary)}\n\n"
            "Please choose what to do."
        )

    def _mark_pending_hold_review_card_handled(
        self,
        chat_id: int | None,
        message_id: int | None,
        original_text: str,
        status_text: str,
    ) -> None:
        if not chat_id or not message_id:
            return
        text = escape(original_text.strip()) if original_text.strip() else "Pending hold review handled."
        if "Status:" not in original_text:
            text = f"{text}\n\n<b>{escape(status_text)}</b>"
        try:
            self.telegram.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=None)
        except Exception:
            logger.exception("Could not edit pending hold review card after decision.")
            self._clear_pending_hold_review_buttons(chat_id, message_id)

    def _clear_pending_hold_review_buttons(self, chat_id: int | None, message_id: int | None) -> None:
        if not chat_id or not message_id:
            return
        try:
            self.telegram.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except Exception:
            logger.exception("Could not clear pending hold review buttons.")


    def _mark_short_action_card_handled(
        self,
        chat_id: int | None,
        message_id: int | None,
        text: str,
    ) -> None:
        if not chat_id or not message_id:
            return
        try:
            self.telegram.edit_message_text(chat_id=chat_id, message_id=message_id, text=escape(text), reply_markup=None)
            self.telegram.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except Exception:
            logger.exception("Could not mark short Telegram action card handled.")


    def _review_keyboard_or_none(self, intake: IntakeRequest) -> dict[str, Any] | None:
        keyboard = self._build_review_keyboard(intake)["inline_keyboard"]
        if not keyboard:
            return None
        return {"inline_keyboard": keyboard}

    def _refresh_review_card(
        self,
        intake: IntakeRequest,
        chat_id: int | None,
        message_id: int | None,
        status_text: str,
    ) -> None:
        if not chat_id or not message_id:
            return
        text = self._format_review_text(intake, status_text=status_text)
        reply_markup = self._review_keyboard_or_none(intake)
        try:
            self.telegram.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            if reply_markup is None:
                self.telegram.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except Exception:
            logger.exception("Could not refresh Telegram review card after action.")
            try:
                self.telegram.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)
            except Exception:
                logger.exception("Could not refresh Telegram review card buttons after action.")

    @staticmethod
    def _ai_reply_decision_handled(intake: IntakeRequest) -> bool:
        return HumanDecision.objects.filter(
            intake=intake,
            action__in=[
                HumanDecisionAction.APPROVE_AI_REPLY,
                HumanDecisionAction.EDIT_REPLY,
                HumanDecisionAction.REJECT,
            ],
        ).exists()

    @staticmethod
    def _assignment_locked(intake: IntakeRequest) -> bool:
        if intake.assigned_artist_id:
            return True
        return ExternalArtistOffer.objects.filter(
            intake=intake,
            status=ExternalArtistOfferStatus.OFFERED,
        ).exists()

    def _build_artist_selection_keyboard(self, intake: IntakeRequest, action: str = "assign") -> dict[str, Any]:
        keyboard: list[list[dict[str, str]]] = []
        artists = ArtistProfile.objects.filter(is_active=True).order_by("sort_order", "name")
        row = []
        for artist in artists:
            row.append({
                "text": artist.name,
                "callback_data": f"{self.CALLBACK_PREFIX}:{action}:{intake.pk}:{artist.pk}",
            })
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        return {"inline_keyboard": keyboard}

    def _build_review_keyboard(self, intake: IntakeRequest) -> dict[str, Any]:
        keyboard: list[list[dict[str, str]]] = []

        if not self._ai_reply_decision_handled(intake):
            keyboard.extend([
                [
                    {"text": "Approve AI Reply", "callback_data": f"{self.CALLBACK_PREFIX}:approve:{intake.pk}"},
                    {"text": "Edit Reply", "callback_data": f"{self.CALLBACK_PREFIX}:edit:{intake.pk}"},
                ],
                [
                    {"text": "Reject", "callback_data": f"{self.CALLBACK_PREFIX}:reject:{intake.pk}"},
                ],
            ])

        keyboard.append([
            {"text": "Edit Price", "callback_data": f"{self.CALLBACK_PREFIX}:price:{intake.pk}"},
        ])

        if not self._assignment_locked(intake):
            artists_keyboard = self._build_artist_selection_keyboard(intake, action="assign")["inline_keyboard"]
            for row in artists_keyboard:
                keyboard.append([
                    {
                        "text": f"Assign {button['text']}",
                        "callback_data": button["callback_data"],
                    }
                    for button in row
                ])

        return {"inline_keyboard": keyboard}


    def _format_review_text(self, intake: IntakeRequest, status_text: str = "") -> str:
        price_lines = [
            f"Price: {escape(intake.approved_price or 'Not approved')}",
        ]
        if intake.ai_suggested_price:
            price_lines.append(f"AI suggested price: {escape(intake.ai_suggested_price)}")
        if intake.price_note:
            price_lines.append(f"Price note: {escape(intake.price_note)}")
        if intake.appointment_date and intake.appointment_time:
            price_lines.append(f"Suggested schedule: {escape(intake.appointment_date)} at {escape(intake.appointment_time)}")
        if intake.pending_hold_status and intake.pending_hold_status != "none":
            pending = f"Pending hold: {intake.get_pending_hold_status_display()}"
            if intake.pending_hold_date and intake.pending_hold_time:
                pending += f" - {intake.pending_hold_date} at {intake.pending_hold_time}"
            if intake.pending_hold_service_code:
                pending += f" - {intake.pending_hold_service_code} {intake.pending_hold_service_name}"
            price_lines.append(escape(pending))
        if intake.scheduled_date and intake.scheduled_time:
            price_lines.append(
                f"Scheduled: {escape(intake.scheduled_date)} at {escape(intake.scheduled_time)}"
            )
            if intake.scheduled_service_code:
                price_lines.append(
                    f"Service: {escape(intake.scheduled_service_code)} - {escape(intake.scheduled_service_name)}"
                )
        if intake.payment_status:
            price_lines.append(f"Payment status: {escape(intake.get_payment_status_display())}")

        summary_section = ""
        if intake.latest_summary:
            summary_section = f"\n<b>Summary</b>\n{escape(intake.latest_summary)}\n"

        status_section = ""
        if status_text:
            status_section = f"\n<b>{escape(status_text)}</b>\n"

        return (
            f"<b>High-risk request #{intake.pk}</b>\n"
            f"Client: {escape(str(intake.lead))}\n"
            f"Source: {escape(intake.source)}\n"
            f"Idea: {escape(intake.tattoo_idea or 'Unclear')}\n"
            f"Artist suggestion: {escape(intake.suggested_artist or 'Unclear')}\n"
            f"Missing: {escape(', '.join(intake.missing_information) or 'None')}\n\n"
            f"{chr(10).join(price_lines)}\n"
            f"{summary_section}"
            f"{status_section}\n"
            f"<b>Draft reply</b>\n<pre>{escape(intake.latest_draft_reply or '')}</pre>"
        )


    def _format_artist_update_text(
        self,
        intake: IntakeRequest,
        text: str,
        media_items: list[dict[str, Any]],
    ) -> str:
        media_note = ""
        if media_items:
            media_note = "\nMedia: " + ", ".join(escape(item.get("url", "")) for item in media_items if item.get("url"))

        detail_lines = [
            f"Idea: {escape(intake.tattoo_idea or 'Unclear')}",
            f"Approved Price: {escape(intake.approved_price or 'Not approved')}",
        ]
        if intake.ai_suggested_price:
            detail_lines.append(f"AI suggested price: {escape(intake.ai_suggested_price or 'None')}")
        if intake.price_note:
            detail_lines.append(f"Price note: {escape(intake.price_note or 'None')}")
        if intake.placement:
            detail_lines.append(f"Placement: {escape(intake.placement or 'None')}")
        if intake.size_estimate_cm:
            detail_lines.append(f"Size: {escape(intake.size_estimate_cm or 'None')}")
        if intake.color_preference:
            detail_lines.append(f"Color: {escape(intake.color_preference or 'None')}")
        if intake.scheduled_date and intake.scheduled_time:
            detail_lines.append(f"Scheduled: {escape(intake.scheduled_date)} at {escape(intake.scheduled_time)}")
            if intake.scheduled_service_code:
                detail_lines.append(
                    f"Service: {escape(intake.scheduled_service_code)} - {escape(intake.scheduled_service_name)}"
                )
        elif intake.pending_hold_date and intake.pending_hold_time:
            detail_lines.append(f"Pending hold: {escape(intake.pending_hold_date)} at {escape(intake.pending_hold_time)}")
            if intake.pending_hold_service_code:
                detail_lines.append(f"Service: {escape(intake.pending_hold_service_code)} - {escape(intake.pending_hold_service_name)}")
        elif intake.appointment_date and intake.appointment_time:
            detail_lines.append(f"Suggested schedule: {escape(intake.appointment_date)} at {escape(intake.appointment_time)}")

        summary_section = ""
        if intake.latest_summary:
            summary_section = f"\n\n<b>Summary</b>\n{escape(intake.latest_summary)}"

        return (
            f"<b>Request #{intake.pk}</b>\n"
            f"Client: {escape(str(intake.lead))}\n"
            f"Source: {escape(intake.source)}\n"
            f"{chr(10).join(detail_lines)}"
            f"{summary_section}\n\n"
            f"{escape(text or '')}"
            f"{media_note}\n\n"
            "Reply to this message to answer the client, or use:\n"
            f"<code>/reply {intake.pk} your message</code>"
        )

    def _store_message_link(
        self,
        intake: IntakeRequest,
        purpose: str,
        response: dict[str, Any],
        artist: ArtistProfile | None,
    ) -> TelegramMessageLink | None:
        message = response.get("result", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        if not chat_id or not message_id:
            return None

        return TelegramMessageLink.objects.create(
            intake=intake,
            lead=intake.lead,
            artist=artist,
            purpose=purpose,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            raw_message=message,
        )

    @staticmethod
    def _parse_price_text(text: str) -> tuple[str, str]:
        price, separator, note = text.partition("|")
        return price.strip(), note.strip() if separator else ""

    @staticmethod
    def _schedule_command_help() -> str:
        return (
            "Use /schedule REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM.\n"
            "Example: /schedule 1 OCH 2026-09-04 14:30\n\n"
            f"{VcitaSchedulingService.service_code_help()}"
        )

    @staticmethod
    def _hold_command_help() -> str:
        return (
            "Use /hold REQUEST_ID SERVICE_CODE YYYY-MM-DD HH:MM.\n"
            "Example: /hold 1 OCH 2026-09-04 14:30\n\n"
            f"{VcitaSchedulingService.service_code_help()}"
        )

    @staticmethod
    def _logs_command_help() -> str:
        return (
            "Use /logs, /logs REQUEST_ID, /logs --20, or /logs REQUEST_ID --20.\n"
            "Maximum is 30."
        )

    @staticmethod
    def _parse_logs_command(text: str) -> tuple[int | None, int] | None:
        parts = text.split()
        if not parts or parts[0].split("@", 1)[0].lower() != "/logs":
            return None

        intake_id: int | None = None
        limit = 10
        for part in parts[1:]:
            if part.startswith("--"):
                raw_limit = part[2:]
                if not raw_limit.isdigit():
                    return None
                limit = int(raw_limit)
                if limit < 1 or limit > 30:
                    return None
                continue
            if part.isdigit() and intake_id is None:
                intake_id = int(part)
                continue
            return None
        return intake_id, limit

    @staticmethod
    def _format_logs_response(decisions: list[HumanDecision], intake_id: int | None, limit: int) -> str:
        if intake_id is not None:
            title = f"Latest {limit} logs for Request #{intake_id}"
        else:
            title = f"Latest {limit} request logs"

        if not decisions:
            return f"{title}\n\nNo logs found."

        lines = [f"<b>{escape(title)}</b>"]
        for decision in decisions:
            timestamp = timezone.localtime(decision.created_at).strftime("%Y-%m-%d %H:%M")
            actor = decision.actor.name if decision.actor else "Unknown"
            action = decision.get_action_display()
            request_label = f"Request #{decision.intake_id}"
            detail = TelegramWorkflowService._human_decision_detail(decision)
            line = f"{escape(timestamp)} - {escape(request_label)} - {escape(actor)}: {escape(action)}"
            if detail:
                line = f"{line} - {escape(detail)}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _human_decision_detail(decision: HumanDecision) -> str:
        if decision.action == HumanDecisionAction.ASSIGN_ARTIST and decision.assigned_artist:
            return f"assigned {decision.assigned_artist.name}"
        if decision.action == HumanDecisionAction.EDIT_PRICE:
            return decision.note.replace("\n", " | ")
        if decision.action in (
            HumanDecisionAction.HOLD_APPOINTMENT,
            HumanDecisionAction.KEEP_HOLD,
            HumanDecisionAction.RELEASE_HOLD,
            HumanDecisionAction.PENDING_HOLD_REVIEW,
            HumanDecisionAction.SCHEDULE,
        ):
            return decision.note
        if decision.action in (HumanDecisionAction.EDIT_REPLY, HumanDecisionAction.ARTIST_REPLY):
            note = decision.note.strip().replace("\n", " ")
            return note[:120] + ("..." if len(note) > 120 else "")
        return decision.note.strip().replace("\n", " ")[:120]

    @staticmethod
    def _format_google_warning_note(warnings: list[str]) -> str:
        if not warnings:
            return ""
        return "\nGoogle Calendar warning: " + " | ".join(warnings)

    @staticmethod
    def _format_google_warning_text(warnings: list[str]) -> str:
        if not warnings:
            return ""
        return "\n\nGoogle Calendar warning:\n" + escape("\n".join(warnings))

    @staticmethod
    def _format_hold_group_confirmation(result: VcitaHoldResult) -> str:
        return (
            f"Request #{result.intake.pk} pending hold created.\n"
            f"When: {escape(result.requested_date)} at {escape(result.requested_time)}\n"
            f"Service: {escape(result.service.code)} - {escape(result.service.name)}\n"
            f"Artist: {escape(result.intake.assigned_artist.name if result.intake.assigned_artist else 'Unassigned')}\n"
            f"Expires: {escape(timezone.localtime(result.expires_at).strftime('%Y-%m-%d %H:%M'))}\n"
            "Waiting for vCita payment/final confirmation." + TelegramWorkflowService._format_google_warning_text(result.google_sync_warnings)
        )

    @staticmethod
    def _format_schedule_group_confirmation(result: VcitaScheduleResult) -> str:
        action = "rescheduled" if result.was_reschedule else "scheduled"
        lines = [
            f"Request #{result.intake.pk} {action}.",
            f"When: {escape(result.requested_date)} at {escape(result.requested_time)}",
            f"Service: {escape(result.service.code)} - {escape(result.service.name)}",
            f"Artist: {escape(result.intake.assigned_artist.name if result.intake.assigned_artist else 'Unassigned')}",
        ]
        if result.schedule_provider == VcitaScheduleProvider.GOOGLE_ONLY:
            lines.append("Provider: Google Calendar only")
            if result.google_synced_event_ids:
                lines.append("Google event ID: <code>" + escape(result.google_synced_event_ids[0]) + "</code>")
        else:
            lines.append(f"vCita booking ID: <code>{escape(result.booking_uid)}</code>")
        return "\n".join(lines) + TelegramWorkflowService._format_google_warning_text(result.google_sync_warnings)

    @staticmethod
    def _format_client_schedule_notice(result: VcitaScheduleResult) -> str:
        action = "rescheduled" if result.was_reschedule else "scheduled"
        return (
            f"Your {result.service.name} appointment has been {action} for "
            f"{result.requested_date} at {result.requested_time}. "
            "Please let us know if you need to change anything."
        )

    @staticmethod
    def _get_artist_by_user(telegram_user_id: Any) -> ArtistProfile | None:
        if telegram_user_id is None:
            return None
        return ArtistProfile.objects.filter(
            telegram_user_id=telegram_user_id,
            is_active=True,
        ).first()

    @classmethod
    def _parse_callback_data(cls, data: str) -> dict[str, int | str] | None:
        parts = data.split(":")
        if len(parts) < 3 or parts[0] != cls.CALLBACK_PREFIX:
            return None
        action = parts[1]
        if not parts[2].isdigit():
            return None
        parsed: dict[str, int | str] = {
            "action": action,
            "intake_id": int(parts[2]),
        }
        if action in ("assign", "reassign"):
            if len(parts) != 4 or not parts[3].isdigit():
                return None
            parsed["artist_id"] = int(parts[3])
        if action in ("external_accept", "external_decline"):
            if len(parts) != 4 or not parts[3].isdigit():
                return None
            parsed["offer_id"] = int(parts[3])
        return parsed
