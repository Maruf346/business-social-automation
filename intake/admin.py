from django.contrib import admin

from intake.models import AIAnalysis, IntakeRequest


@admin.register(IntakeRequest)
class IntakeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "lead",
        "status",
        "risk_level",
        "suggested_artist",
        "confidence_level",
        "is_active",
        "updated_at",
    )
    list_filter = ("status", "risk_level", "confidence_level", "is_active", "created_at")
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
