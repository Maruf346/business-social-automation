from __future__ import annotations

from typing import Any

from django.db import transaction

from intake.models import AIAnalysis, ConfidenceLevel, IntakeRequest, IntakeSource, IntakeStatus, RiskLevel
from lead.models import Conversation, Lead, MediaFile, Message


class IntakeStateService:
    AI_RESPONSE_FIELDS = (
        "client_name",
        "tattoo_idea",
        "style_tags",
        "placement",
        "size_estimate_cm",
        "color_preference",
        "date",
        "time",
        "preferred_artist",
        "appointment_type",
        "tattoo_project_type",
        "suggested_artist",
        "confidence_level",
        "ai_reasoning",
        "missing_information",
        "risk_level",
        "summary",
        "suggested_price",
        "pricing_reasoning",
        "draft_reply",
        "auto_reply_allowed",
        "telegram_review_required",
    )

    @classmethod
    def get_or_create_active_intake(
        cls,
        lead: Lead,
        conversation: Conversation | None = None,
    ) -> IntakeRequest:
        filters: dict[str, Any] = {
            "lead": lead,
            "is_active": True,
        }
        if conversation is not None:
            filters["conversation"] = conversation

        intake = IntakeRequest.objects.filter(**filters).order_by("-updated_at").first()
        if intake:
            return intake

        return IntakeRequest.objects.create(
            lead=lead,
            conversation=conversation,
        )

    @classmethod
    def build_existing_db_state(
        cls,
        lead: Lead,
        intake: IntakeRequest,
        latest_analysis: AIAnalysis | None = None,
        current_message: Message | None = None,
    ) -> dict[str, Any]:
        if latest_analysis is None:
            latest_analysis = intake.ai_analyses.order_by("-created_at").first()
        previous_image_urls = cls._previous_image_urls(lead, intake, current_message=current_message)

        return {
            "lead": {
                "id": lead.pk,
                "name": lead.name or "",
                "phone_number": lead.phone_number or "",
                "email": lead.email or "",
                "source": cls._choice_value(lead.source),
            },
            "intake": {
                "id": intake.pk,
                "status": cls._choice_value(intake.status),
                "is_active": intake.is_active,
                "source": cls._choice_value(intake.source),
                "assigned_artist": intake.assigned_artist.name if intake.assigned_artist else "",
                "client_name": intake.client_name,
                "tattoo_idea": intake.tattoo_idea,
                "style_tags": intake.style_tags,
                "placement": intake.placement,
                "size_estimate_cm": intake.size_estimate_cm,
                "color_preference": intake.color_preference,
                "preferred_artist": intake.preferred_artist,
                "appointment_type": intake.appointment_type,
                "tattoo_project_type": intake.tattoo_project_type,
                "suggested_artist": intake.suggested_artist,
                "confidence_level": cls._choice_value(intake.confidence_level),
                "ai_reasoning": intake.ai_reasoning,
                "missing_information": intake.missing_information,
                "risk_level": cls._choice_value(intake.risk_level),
                "auto_reply_allowed": intake.auto_reply_allowed,
                "telegram_review_required": intake.telegram_review_required,
                "latest_summary": intake.latest_summary,
                "ai_suggested_price": intake.ai_suggested_price,
                "approved_price": intake.approved_price,
                "price_note": intake.price_note,
                "price_approved_by": intake.price_approved_by.name if intake.price_approved_by else "",
                "price_approved_at": intake.price_approved_at.isoformat() if intake.price_approved_at else "",
                "latest_draft_reply": intake.latest_draft_reply,
                "appointment_date": intake.appointment_date,
                "appointment_time": intake.appointment_time,
                "scheduled_date": intake.scheduled_date,
                "scheduled_time": intake.scheduled_time,
                "scheduled_service_code": intake.scheduled_service_code,
                "scheduled_service_name": intake.scheduled_service_name,
                "scheduled_service_uid": intake.scheduled_service_uid,
                "pending_hold_status": cls._choice_value(intake.pending_hold_status),
                "pending_hold_date": intake.pending_hold_date,
                "pending_hold_time": intake.pending_hold_time,
                "pending_hold_service_code": intake.pending_hold_service_code,
                "pending_hold_service_name": intake.pending_hold_service_name,
                "pending_hold_service_uid": intake.pending_hold_service_uid,
                "pending_hold_expires_at": intake.pending_hold_expires_at.isoformat() if intake.pending_hold_expires_at else "",
                "pending_hold_review_notified_at": intake.pending_hold_review_notified_at.isoformat() if intake.pending_hold_review_notified_at else "",
                "pending_hold_error": intake.pending_hold_error,
                "schedule_status": cls._choice_value(intake.schedule_status),
                "vcita_matter_uid": intake.vcita_matter_uid,
                "vcita_booking_uid": intake.vcita_booking_uid,
                "payment_status": cls._choice_value(intake.payment_status),
                "previous_image_urls": previous_image_urls,
            },
            "latest_ai_analysis": cls._analysis_state(latest_analysis),
        }

    @classmethod
    def update_channel_context(
        cls,
        intake: IntakeRequest,
        source: str,
        last_incoming_message: Message | None = None,
        whatsapp_account=None,
        outlook_account=None,
        outlook_user_id: str = "",
    ) -> IntakeRequest:
        update_fields = ["source", "updated_at"]
        intake.source = cls._normalize_choice(
            source,
            allowed={choice.value for choice in IntakeSource},
            default=IntakeSource.OTHER,
        )

        if last_incoming_message is not None:
            intake.last_incoming_message = last_incoming_message
            update_fields.append("last_incoming_message")

        if whatsapp_account is not None:
            intake.whatsapp_account = whatsapp_account
            update_fields.append("whatsapp_account")

        if outlook_account is not None:
            intake.outlook_account = outlook_account
            update_fields.append("outlook_account")

        if outlook_user_id:
            intake.outlook_user_id = outlook_user_id
            update_fields.append("outlook_user_id")

        intake.save(update_fields=update_fields)
        return intake

    @classmethod
    @transaction.atomic
    def record_ai_response(
        cls,
        intake: IntakeRequest,
        lead: Lead,
        message: Message | None,
        response: dict[str, Any],
        endpoint: str = "analyze",
        request_payload: dict[str, Any] | None = None,
    ) -> AIAnalysis:
        normalized = cls.normalize_ai_response(response)

        analysis = AIAnalysis.objects.create(
            intake=intake,
            lead=lead,
            message=message,
            endpoint=endpoint,
            client_name=normalized["client_name"],
            tattoo_idea=normalized["tattoo_idea"],
            style_tags=normalized["style_tags"],
            placement=normalized["placement"],
            size_estimate_cm=normalized["size_estimate_cm"],
            color_preference=normalized["color_preference"],
            preferred_artist=normalized["preferred_artist"],
            appointment_type=normalized["appointment_type"],
            tattoo_project_type=normalized["tattoo_project_type"],
            suggested_artist=normalized["suggested_artist"],
            confidence_level=normalized["confidence_level"],
            ai_reasoning=normalized["ai_reasoning"],
            missing_information=normalized["missing_information"],
            risk_level=normalized["risk_level"],
            summary=normalized["summary"],
            suggested_price=normalized["suggested_price"],
            pricing_reasoning=normalized["pricing_reasoning"],
            draft_reply=normalized["draft_reply"],
            appointment_date=normalized["date"],
            appointment_time=normalized["time"],
            auto_reply_allowed=normalized["auto_reply_allowed"],
            telegram_review_required=normalized["telegram_review_required"],
            raw_response=response if isinstance(response, dict) else {},
            request_payload=request_payload or {},
        )

        review_required = (
            normalized["telegram_review_required"]
            or not normalized["auto_reply_allowed"]
            or normalized["risk_level"] in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.UNKNOWN)
        )
        status = IntakeStatus.WAITING_FOR_HUMAN if review_required else IntakeStatus.COLLECTING_INFO

        intake.client_name = normalized["client_name"]
        intake.tattoo_idea = normalized["tattoo_idea"]
        intake.style_tags = normalized["style_tags"]
        intake.placement = normalized["placement"]
        intake.size_estimate_cm = normalized["size_estimate_cm"]
        intake.color_preference = normalized["color_preference"]
        intake.preferred_artist = normalized["preferred_artist"]
        intake.appointment_type = normalized["appointment_type"]
        intake.tattoo_project_type = normalized["tattoo_project_type"]
        intake.suggested_artist = normalized["suggested_artist"]
        intake.confidence_level = normalized["confidence_level"]
        intake.ai_reasoning = normalized["ai_reasoning"]
        intake.missing_information = normalized["missing_information"]
        intake.risk_level = normalized["risk_level"]
        intake.auto_reply_allowed = normalized["auto_reply_allowed"]
        intake.telegram_review_required = normalized["telegram_review_required"]
        intake.latest_summary = normalized["summary"]
        intake.ai_suggested_price = normalized["suggested_price"]
        intake.latest_draft_reply = normalized["draft_reply"]
        intake.appointment_date = normalized["date"]
        intake.appointment_time = normalized["time"]
        intake.latest_raw_ai_response = response if isinstance(response, dict) else {}
        intake.status = status

        if normalized["client_name"] and not (lead.name or "").strip():
            lead.name = normalized["client_name"]
            lead.save(update_fields=["name", "updated_at"])

        intake.save(
            update_fields=[
                "client_name",
                "tattoo_idea",
                "style_tags",
                "placement",
                "size_estimate_cm",
                "color_preference",
                "preferred_artist",
                "appointment_type",
                "tattoo_project_type",
                "suggested_artist",
                "confidence_level",
                "ai_reasoning",
                "missing_information",
                "risk_level",
                "auto_reply_allowed",
                "telegram_review_required",
                "latest_summary",
                "ai_suggested_price",
                "latest_draft_reply",
                "appointment_date",
                "appointment_time",
                "latest_raw_ai_response",
                "status",
                "updated_at",
            ]
        )

        return analysis

    @classmethod
    def normalize_ai_response(cls, response: dict[str, Any]) -> dict[str, Any]:
        data = response if isinstance(response, dict) else {}
        risk_level = cls._normalize_choice(
            data.get("risk_level"),
            allowed={choice.value for choice in RiskLevel},
            default=RiskLevel.UNKNOWN,
        )
        confidence_level = cls._normalize_choice(
            data.get("confidence_level"),
            allowed={choice.value for choice in ConfidenceLevel},
            default=ConfidenceLevel.UNKNOWN,
        )

        return {
            "client_name": cls._as_string(data.get("client_name")),
            "tattoo_idea": cls._as_string(data.get("tattoo_idea")),
            "style_tags": cls._as_list(data.get("style_tags")),
            "placement": cls._as_string(data.get("placement")),
            "size_estimate_cm": cls._as_string(data.get("size_estimate_cm")),
            "color_preference": cls._as_string(data.get("color_preference")),
            "preferred_artist": cls._as_string(data.get("preferred_artist")),
            "appointment_type": cls._normalize_appointment_type(data.get("appointment_type")),
            "tattoo_project_type": cls._as_string(data.get("tattoo_project_type")),
            "suggested_artist": cls._as_string(data.get("suggested_artist")),
            "confidence_level": confidence_level,
            "ai_reasoning": cls._as_string(data.get("ai_reasoning")),
            "missing_information": cls._as_list(data.get("missing_information")),
            "risk_level": risk_level,
            "summary": cls._as_string(data.get("summary")),
            "suggested_price": cls._as_string(
                data.get("suggested_price")
                or data.get("ai_suggested_price")
                or data.get("price")
                or data.get("price_estimate")
                or data.get("price_range")
            ),
            "pricing_reasoning": cls._as_string(data.get("pricing_reasoning") or data.get("price_reasoning")),
            "draft_reply": cls._as_string(data.get("draft_reply")),
            "date": cls._as_date_string(data.get("date") or data.get("appointment_date")),
            "time": cls._as_time_string(data.get("time") or data.get("appointment_time")),
            "auto_reply_allowed": cls._as_bool(data.get("auto_reply_allowed"), default=True),
            "telegram_review_required": cls._as_bool(data.get("telegram_review_required"), default=False),
        }

    @staticmethod
    def _previous_image_urls(
        lead: Lead,
        intake: IntakeRequest,
        current_message: Message | None = None,
        limit: int = 20,
    ) -> list[str]:
        messages = Message.objects.filter(lead=lead, direction="Incoming")
        if intake.conversation_id:
            messages = messages.filter(conversation_id=intake.conversation_id)
        if current_message is not None:
            messages = messages.exclude(pk=current_message.pk)

        media_files = (
            MediaFile.objects.filter(message__in=messages, media_type="image")
            .select_related("message")
            .order_by("-message__timestamp", "-created_at")[:limit]
        )
        urls: list[str] = []
        for media in media_files:
            url = media.download_url or (media.file.url if media.file else "")
            if url and url not in urls:
                urls.append(url)
        return list(reversed(urls))

    @staticmethod
    def _analysis_state(analysis: AIAnalysis | None) -> dict[str, Any]:
        if analysis is None:
            return {}

        return {
            "id": analysis.pk,
            "endpoint": analysis.endpoint,
            "client_name": analysis.client_name,
            "preferred_artist": analysis.preferred_artist,
            "appointment_type": analysis.appointment_type,
            "tattoo_project_type": analysis.tattoo_project_type,
            "auto_reply_allowed": analysis.auto_reply_allowed,
            "telegram_review_required": analysis.telegram_review_required,
            "ai_reasoning": analysis.ai_reasoning,
            "summary": analysis.summary,
            "suggested_price": analysis.suggested_price,
            "pricing_reasoning": analysis.pricing_reasoning,
            "draft_reply": analysis.draft_reply,
            "date": analysis.appointment_date,
            "time": analysis.appointment_time,
            "risk_level": IntakeStateService._choice_value(analysis.risk_level),
            "created_at": analysis.created_at.isoformat(),
        }

    @staticmethod
    def _as_string(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _as_date_string(value: Any) -> str:
        value = IntakeStateService._as_string(value).strip()
        if len(value) == 10 and value[4] == "-" and value[7] == "-":
            return value
        return ""

    @staticmethod
    def _as_time_string(value: Any) -> str:
        value = IntakeStateService._as_string(value).strip()
        if len(value) == 5 and value[2] == ":":
            return value
        return ""

    @staticmethod
    def _normalize_appointment_type(value: Any) -> str:
        normalized = IntakeStateService._as_string(value).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"online", "studio_visit"}:
            return normalized
        return ""

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return bool(value)

    @staticmethod
    def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
        if not isinstance(value, str):
            return default
        normalized = value.strip().lower()
        if normalized in allowed:
            return normalized
        return default

    @staticmethod
    def _choice_value(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value
