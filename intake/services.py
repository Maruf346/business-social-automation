from __future__ import annotations

from typing import Any

from django.db import transaction

from intake.models import AIAnalysis, ConfidenceLevel, IntakeRequest, IntakeSource, IntakeStatus, RiskLevel
from lead.models import Conversation, Lead, Message


class IntakeStateService:
    AI_RESPONSE_FIELDS = (
        "tattoo_idea",
        "style_tags",
        "placement",
        "size_estimate_cm",
        "color_preference",
        "suggested_artist",
        "confidence_level",
        "ai_reasoning",
        "missing_information",
        "risk_level",
        "summary",
        "suggested_price",
        "pricing_reasoning",
        "draft_reply",
        "date",
        "time",
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
    ) -> dict[str, Any]:
        if latest_analysis is None:
            latest_analysis = intake.ai_analyses.order_by("-created_at").first()

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
                "tattoo_idea": intake.tattoo_idea,
                "style_tags": intake.style_tags,
                "placement": intake.placement,
                "size_estimate_cm": intake.size_estimate_cm,
                "color_preference": intake.color_preference,
                "suggested_artist": intake.suggested_artist,
                "confidence_level": cls._choice_value(intake.confidence_level),
                "ai_reasoning": intake.ai_reasoning,
                "missing_information": intake.missing_information,
                "risk_level": cls._choice_value(intake.risk_level),
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
                "schedule_status": cls._choice_value(intake.schedule_status),
                "vcita_booking_uid": intake.vcita_booking_uid,
                "payment_status": cls._choice_value(intake.payment_status),
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
    ) -> AIAnalysis:
        normalized = cls.normalize_ai_response(response)

        analysis = AIAnalysis.objects.create(
            intake=intake,
            lead=lead,
            message=message,
            endpoint=endpoint,
            tattoo_idea=normalized["tattoo_idea"],
            style_tags=normalized["style_tags"],
            placement=normalized["placement"],
            size_estimate_cm=normalized["size_estimate_cm"],
            color_preference=normalized["color_preference"],
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
            raw_response=response if isinstance(response, dict) else {},
        )

        status = (
            IntakeStatus.WAITING_FOR_HUMAN
            if normalized["risk_level"] in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.UNKNOWN)
            else IntakeStatus.COLLECTING_INFO
        )

        intake.tattoo_idea = normalized["tattoo_idea"]
        intake.style_tags = normalized["style_tags"]
        intake.placement = normalized["placement"]
        intake.size_estimate_cm = normalized["size_estimate_cm"]
        intake.color_preference = normalized["color_preference"]
        intake.suggested_artist = normalized["suggested_artist"]
        intake.confidence_level = normalized["confidence_level"]
        intake.ai_reasoning = normalized["ai_reasoning"]
        intake.missing_information = normalized["missing_information"]
        intake.risk_level = normalized["risk_level"]
        intake.latest_summary = normalized["summary"]
        intake.ai_suggested_price = normalized["suggested_price"]
        intake.latest_draft_reply = normalized["draft_reply"]
        intake.appointment_date = normalized["date"]
        intake.appointment_time = normalized["time"]
        intake.latest_raw_ai_response = response if isinstance(response, dict) else {}
        intake.status = status
        intake.save(
            update_fields=[
                "tattoo_idea",
                "style_tags",
                "placement",
                "size_estimate_cm",
                "color_preference",
                "suggested_artist",
                "confidence_level",
                "ai_reasoning",
                "missing_information",
                "risk_level",
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
            "tattoo_idea": cls._as_string(data.get("tattoo_idea")),
            "style_tags": cls._as_list(data.get("style_tags")),
            "placement": cls._as_string(data.get("placement")),
            "size_estimate_cm": cls._as_string(data.get("size_estimate_cm")),
            "color_preference": cls._as_string(data.get("color_preference")),
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
        }

    @staticmethod
    def _analysis_state(analysis: AIAnalysis | None) -> dict[str, Any]:
        if analysis is None:
            return {}

        return {
            "id": analysis.pk,
            "endpoint": analysis.endpoint,
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
