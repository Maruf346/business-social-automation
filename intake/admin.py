from django.contrib import admin

from intake.models import AIAnalysis, ArtistProfile, HumanDecision, IntakeRequest, TelegramMessageLink


@admin.register(ArtistProfile)
class ArtistProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "telegram_user_id",
        "telegram_chat_id",
        "can_approve",
        "is_active",
        "sort_order",
    )
    list_filter = ("can_approve", "is_active")
    search_fields = ("name", "telegram_user_id", "telegram_chat_id")
    ordering = ("sort_order", "name")


@admin.register(IntakeRequest)
class IntakeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "lead",
        "status",
        "risk_level",
        "assigned_artist",
        "suggested_artist",
        "confidence_level",
        "is_active",
        "updated_at",
    )
    list_filter = ("status", "risk_level", "confidence_level", "assigned_artist", "source", "is_active", "created_at")
    search_fields = ("lead__name", "lead__phone_number", "lead__email", "tattoo_idea", "suggested_artist")
    readonly_fields = ("latest_raw_ai_response", "created_at", "updated_at")
    ordering = ("-updated_at",)


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "intake",
        "lead",
        "message",
        "risk_level",
        "suggested_artist",
        "confidence_level",
        "created_at",
    )
    list_filter = ("endpoint", "risk_level", "confidence_level", "created_at")
    search_fields = ("lead__name", "lead__phone_number", "lead__email", "tattoo_idea", "suggested_artist")
    readonly_fields = ("raw_response", "created_at")
    ordering = ("-created_at",)


@admin.register(HumanDecision)
class HumanDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "intake",
        "actor",
        "assigned_artist",
        "action",
        "telegram_chat_id",
        "telegram_message_id",
        "created_at",
    )
    list_filter = ("action", "actor", "assigned_artist", "created_at")
    search_fields = ("intake__lead__name", "intake__lead__phone_number", "intake__lead__email", "note")
    readonly_fields = ("raw_update", "created_at")
    ordering = ("-created_at",)


@admin.register(TelegramMessageLink)
class TelegramMessageLinkAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "intake",
        "artist",
        "purpose",
        "telegram_chat_id",
        "telegram_message_id",
        "is_active",
        "created_at",
    )
    list_filter = ("purpose", "artist", "is_active", "created_at")
    search_fields = ("intake__lead__name", "intake__lead__phone_number", "intake__lead__email")
    readonly_fields = ("raw_message", "created_at")
    ordering = ("-created_at",)
