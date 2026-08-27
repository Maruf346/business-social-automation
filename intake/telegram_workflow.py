from __future__ import annotations

import logging
from html import escape
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.exceptions import MetaAPIError, OutlookAPIError
from core.services.telegram_bot_service import TelegramBotService
from intake.models import (
    ArtistProfile,
    HumanDecision,
    HumanDecisionAction,
    IntakeRequest,
    IntakeStatus,
    OutboundActionType,
    TelegramMessageLink,
    TelegramMessagePurpose,
)
from lead.choices import SEND_BY
from intake.outbound import ClientOutboundService
from vcita.scheduling import VcitaScheduleResult, VcitaSchedulingError, VcitaSchedulingService

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
        if not actor or not actor.can_approve:
            self.telegram.answer_callback_query(callback_id, "Only Hoss can do this.")
            return {"ok": False, "reason": "unauthorized"}

        data = callback.get("data", "")
        parsed = self._parse_callback_data(data)
        if not parsed:
            self.telegram.answer_callback_query(callback_id, "Unknown action.")
            return {"ok": False, "reason": "unknown_action"}

        action = parsed["action"]
        intake = IntakeRequest.objects.select_related("lead", "assigned_artist").get(pk=parsed["intake_id"])
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if action == "approve":
            return self._approve_ai_reply(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "reject":
            return self._reject_intake(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action in ("edit", "manual"):
            return self._mark_edit_reply(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "price":
            return self._mark_edit_price(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "schedule":
            return self._schedule_intake(intake, actor, callback_id, chat_id, message_id, raw_update)
        if action == "assign":
            artist = ArtistProfile.objects.get(pk=parsed["artist_id"], is_active=True)
            return self._assign_artist(intake, actor, artist, callback_id, chat_id, message_id, raw_update)

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
        parts = text.split(" ", 3)
        if len(parts) < 4 or not parts[1].isdigit():
            self.telegram.send_message(chat_id=chat_id, text=self._schedule_command_help())
            return {"ok": False, "reason": "invalid_schedule_command"}

        intake = IntakeRequest.objects.select_related("lead", "assigned_artist").filter(
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
            appointment_date=parts[2],
            appointment_time=parts[3],
        )

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
    ) -> dict[str, Any]:
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
        if artist.telegram_chat_id:
            self.send_artist_update(
                intake=intake,
                text="You have been assigned to this request.",
                purpose=TelegramMessagePurpose.ARTIST_ASSIGNMENT,
            )
            self.telegram.answer_callback_query(callback_id, f"Assigned to {artist.name}.")
            self.telegram.send_message(chat_id=chat_id, text=f"Request #{intake.pk} assigned to {escape(artist.name)}.")
        else:
            self.telegram.answer_callback_query(callback_id, f"{artist.name} has no private chat ID yet.")
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk} assigned to {escape(artist.name)}, but they need to start the bot and run /whoami.",
            )
        return {"ok": True, "action": "assign", "intake_id": intake.pk, "artist_id": artist.pk}

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
        appointment_date: str | None = None,
        appointment_time: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = VcitaSchedulingService().schedule_intake(
                intake=intake,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
            )
        except VcitaSchedulingError as exc:
            if callback_id:
                self.telegram.answer_callback_query(callback_id, "Could not schedule request.")
            self.telegram.send_message(
                chat_id=chat_id,
                text=f"Request #{intake.pk}: could not schedule in vCita.\nReason: {escape(str(exc))}",
            )
            return {"ok": False, "reason": "schedule_failed", "intake_id": intake.pk}

        HumanDecision.objects.create(
            intake=intake,
            actor=actor,
            action=HumanDecisionAction.SCHEDULE,
            note=(
                f"Scheduled for {result.requested_date} {result.requested_time}. "
                f"vCita booking: {result.booking_uid}"
            ),
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
                    f"for {result.requested_date} at {result.requested_time}."
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

    def _build_review_keyboard(self, intake: IntakeRequest) -> dict[str, Any]:
        keyboard = [
            [
                {"text": "Approve AI Reply", "callback_data": f"{self.CALLBACK_PREFIX}:approve:{intake.pk}"},
                {"text": "Edit Reply", "callback_data": f"{self.CALLBACK_PREFIX}:edit:{intake.pk}"},
            ],
            [
                {"text": "Edit Price", "callback_data": f"{self.CALLBACK_PREFIX}:price:{intake.pk}"},
            ],
            [
                {"text": "Reject", "callback_data": f"{self.CALLBACK_PREFIX}:reject:{intake.pk}"},
            ],
        ]

        artists = ArtistProfile.objects.filter(is_active=True).order_by("sort_order", "name")
        row = []
        for artist in artists:
            row.append({
                "text": f"Assign {artist.name}",
                "callback_data": f"{self.CALLBACK_PREFIX}:assign:{intake.pk}:{artist.pk}",
            })
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        if intake.appointment_date and intake.appointment_time:
            keyboard.append(
                [
                    {
                        "text": "Schedule",
                        "callback_data": f"{self.CALLBACK_PREFIX}:schedule:{intake.pk}",
                    }
                ]
            )

        return {"inline_keyboard": keyboard}

    def _format_review_text(self, intake: IntakeRequest) -> str:
        price_lines = [
            f"Price: {escape(intake.approved_price or 'Not approved')}",
        ]
        if intake.ai_suggested_price:
            price_lines.append(f"AI suggested price: {escape(intake.ai_suggested_price)}")
        if intake.price_note:
            price_lines.append(f"Price note: {escape(intake.price_note)}")
        if intake.appointment_date and intake.appointment_time:
            price_lines.append(f"Suggested schedule: {escape(intake.appointment_date)} at {escape(intake.appointment_time)}")
        if intake.scheduled_date and intake.scheduled_time:
            price_lines.append(
                f"Scheduled: {escape(intake.scheduled_date)} at {escape(intake.scheduled_time)}"
            )
        if intake.payment_status:
            price_lines.append(f"Payment status: {escape(intake.get_payment_status_display())}")

        summary_section = ""
        if intake.latest_summary:
            summary_section = f"\n<b>Summary</b>\n{escape(intake.latest_summary)}\n"

        return (
            f"<b>High-risk request #{intake.pk}</b>\n"
            f"Client: {escape(str(intake.lead))}\n"
            f"Source: {escape(intake.source)}\n"
            f"Idea: {escape(intake.tattoo_idea or 'Unclear')}\n"
            f"Artist suggestion: {escape(intake.suggested_artist or 'Unclear')}\n"
            f"Missing: {escape(', '.join(intake.missing_information) or 'None')}\n\n"
            f"{chr(10).join(price_lines)}\n"
            f"{summary_section}\n"
            f"<b>Draft reply</b>\n{escape(intake.latest_draft_reply or '')}"
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
            "Use /schedule REQUEST_ID YYYY-MM-DD HH:MM.\n"
            "Example: /schedule 1 2026-09-04 14:30"
        )

    @staticmethod
    def _format_schedule_group_confirmation(result: VcitaScheduleResult) -> str:
        action = "rescheduled" if result.was_reschedule else "scheduled"
        return (
            f"Request #{result.intake.pk} {action} in vCita.\n"
            f"When: {escape(result.requested_date)} at {escape(result.requested_time)}\n"
            f"Artist: {escape(result.intake.assigned_artist.name if result.intake.assigned_artist else 'Unassigned')}\n"
            f"vCita booking ID: <code>{escape(result.booking_uid)}</code>"
        )

    @staticmethod
    def _format_client_schedule_notice(result: VcitaScheduleResult) -> str:
        action = "rescheduled" if result.was_reschedule else "scheduled"
        return (
            f"Your tattoo appointment has been {action} for "
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
        if action == "assign":
            if len(parts) != 4 or not parts[3].isdigit():
                return None
            parsed["artist_id"] = int(parts[3])
        return parsed
