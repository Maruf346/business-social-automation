from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import QuerySet
from django.utils import timezone

from core.exceptions import AIServiceError
from core.services.ai_service import AIService
from core.services.telegram_bot_service import TelegramBotService
from intake.models import HumanDecision, HumanDecisionAction, IntakeRequest, PendingHoldStatus
from intake.services import IntakeStateService
from lead.models import Message


class Command(BaseCommand):
    help = "Notify Telegram about active pending appointment holds that need one-week review."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximum number of pending holds to notify in one run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print matching request IDs without sending Telegram messages.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        limit = max(1, min(options["limit"], 100))
        dry_run = options["dry_run"]
        queryset = (
            IntakeRequest.objects.select_related("lead", "conversation", "assigned_artist")
            .filter(
                pending_hold_status=PendingHoldStatus.ACTIVE,
                pending_hold_expires_at__lte=now,
                pending_hold_review_notified_at__isnull=True,
                is_active=True,
            )
            .order_by("pending_hold_expires_at")[:limit]
        )
        intakes = list(queryset)
        if dry_run:
            self.stdout.write("Pending hold review candidates: " + ", ".join(str(intake.pk) for intake in intakes))
            return

        telegram = TelegramBotService()
        sent = 0
        for intake in intakes:
            summary = self._get_ai_or_fallback_summary(intake)
            message = self._format_message(intake, summary)
            telegram.send_message(text=message)
            intake.pending_hold_review_notified_at = now
            intake.save(update_fields=["pending_hold_review_notified_at", "updated_at"])
            HumanDecision.objects.create(
                intake=intake,
                actor=None,
                action=HumanDecisionAction.PENDING_HOLD_REVIEW,
                note="One-week pending hold review notification sent.",
            )
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} pending hold review notification(s)."))

    @staticmethod
    def _get_ai_or_fallback_summary(intake: IntakeRequest) -> str:
        chat_history = Command._chat_history(intake)
        existing_db_state = IntakeStateService.build_existing_db_state(intake.lead, intake)
        current_message = (
            "Create a concise staff summary for a pending appointment hold that has reached one week. "
            "Do not decide whether to keep or remove it. Ask Hoss/Nina to choose."
        )
        try:
            response = AIService().get_summery(
                chat_history=chat_history,
                lead=intake.lead,
                current_message=current_message,
                image_urls=[],
                existing_db_state=existing_db_state,
            )
        except (AIServiceError, Exception):
            return Command._fallback_summary(intake)

        summary = response.get("summary") or response.get("telegram_message") or response.get("draft_reply") or ""
        return str(summary).strip() or Command._fallback_summary(intake)

    @staticmethod
    def _chat_history(intake: IntakeRequest) -> QuerySet[Message]:
        queryset = Message.objects.filter(lead=intake.lead)
        if intake.conversation_id:
            queryset = queryset.filter(conversation=intake.conversation)
        return queryset.order_by("-timestamp")[:10]

    @staticmethod
    def _fallback_summary(intake: IntakeRequest) -> str:
        parts = [
            f"Request #{intake.pk}",
            f"Client: {intake.lead}",
            f"Artist: {intake.assigned_artist.name if intake.assigned_artist else 'Unassigned'}",
            f"Service: {intake.pending_hold_service_code} - {intake.pending_hold_service_name}",
            f"Held time: {intake.pending_hold_date} at {intake.pending_hold_time}",
        ]
        if intake.tattoo_idea:
            parts.append(f"Idea: {intake.tattoo_idea}")
        if intake.latest_summary:
            parts.extend(["", intake.latest_summary])
        return "\n".join(parts)

    @staticmethod
    def _format_message(intake: IntakeRequest, summary: str) -> str:
        expires_at = timezone.localtime(intake.pending_hold_expires_at).strftime("%Y-%m-%d %H:%M") if intake.pending_hold_expires_at else "Unknown"
        return (
            f"<b>Pending hold needs review: Request #{intake.pk}</b>\n"
            f"Expired/review due: {expires_at}\n"
            f"Held time: {intake.pending_hold_date} at {intake.pending_hold_time}\n"
            f"Service: {intake.pending_hold_service_code} - {intake.pending_hold_service_name}\n"
            f"Artist: {intake.assigned_artist.name if intake.assigned_artist else 'Unassigned'}\n\n"
            f"<b>Summary</b>\n{summary}\n\n"
            "Please decide manually. Use:\n"
            f"/keephold {intake.pk}\n"
            f"/releasehold {intake.pk}"
        )