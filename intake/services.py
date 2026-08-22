from __future__ import annotations

from typing import Any

from django.db import transaction

from intake.models import AIAnalysis, ConfidenceLevel, IntakeRequest, IntakeStatus, RiskLevel
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
        "draft_reply",
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
                "latest_draft_reply": intake.latest_draft_reply,
            },
            "latest_ai_analysis": cls._analysis_state(latest_analysis),
        }

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
            draft_reply=normalized["draft_reply"],
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
        intake.latest_draft_reply = normalized["draft_reply"]
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
                "latest_draft_reply",
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
            "draft_reply": cls._as_string(data.get("draft_reply")),
        }

    @staticmethod
    def _analysis_state(analysis: AIAnalysis | None) -> dict[str, Any]:
        if analysis is None:
            return {}

        return {
            "id": analysis.pk,
            "endpoint": analysis.endpoint,
            "ai_reasoning": analysis.ai_reasoning,
            "draft_reply": analysis.draft_reply,
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
