from django.contrib import admin

from intake.models import AIAnalysis, ArtistProfile, HumanDecision, IntakeRequest, OutboundAction, TelegramMessageLink


@admin.register(ArtistProfile)
class ArtistProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "telegram_user_id",
        "telegram_chat_id",
        "vcita_staff_uid",
        "can_approve",
        "is_active",
        "sort_order",
    )
    list_filter = ("can_approve", "is_active")
    search_fields = ("name", "telegram_user_id", "telegram_chat_id", "vcita_staff_uid")
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
        "approved_price",
        "ai_suggested_price",
        "appointment_date",
        "appointment_time",
        "scheduled_service_code",
        "schedule_status",
        "payment_status",
        "confidence_level",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "status",
        "risk_level",
        "confidence_level",
        "assigned_artist",
        "source",
        "schedule_status",
        "payment_status",
        "is_active",
        "created_at",
    )
    list_editable = ("status", "risk_level", "approved_price", "ai_suggested_price", "is_active")
    search_fields = (
        "lead__name",
        "lead__phone_number",
        "lead__email",
        "tattoo_idea",
        "suggested_artist",
        "latest_summary",
        "approved_price",
        "ai_suggested_price",
        "vcita_booking_uid",
        "scheduled_service_code",
        "scheduled_service_name",
        "scheduled_service_uid",
    )
    readonly_fields = ("latest_raw_ai_response", "created_at", "updated_at")
    raw_id_fields = (
        "lead",
        "conversation",
        "whatsapp_account",
        "outlook_account",
        "last_incoming_message",
        "scheduled_service",
    )
    fieldsets = (
        (
            "Client And Routing",
            {
                "fields": (
                    "lead",
                    "conversation",
                    "source",
                    "whatsapp_account",
                    "outlook_account",
                    "outlook_user_id",
                    "last_incoming_message",
                    "assigned_artist",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "is_active",
                    "risk_level",
                    "confidence_level",
                )
            },
        ),
        (
            "Tattoo Details",
            {
                "fields": (
                    "tattoo_idea",
                    "style_tags",
                    "placement",
                    "size_estimate_cm",
                    "color_preference",
                    "suggested_artist",
                    "missing_information",
                )
            },
        ),
        (
            "Summary And Draft Reply",
            {
                "fields": (
                    "latest_summary",
                    "ai_reasoning",
                    "latest_draft_reply",
                )
            },
        ),
        (
            "Pricing",
            {
                "fields": (
                    "ai_suggested_price",
                    "approved_price",
                    "price_note",
                    "price_approved_by",
                    "price_approved_at",
                )
            },
        ),
        (
            "Scheduling And Payment",
            {
                "fields": (
                    "appointment_date",
                    "appointment_time",
                    "scheduled_date",
                    "scheduled_time",
                    "scheduled_service",
                    "scheduled_service_code",
                    "scheduled_service_name",
                    "scheduled_service_uid",
                    "schedule_status",
                    "schedule_error",
                    "vcita_booking_uid",
                    "payment_status",
                    "payment_reference",
                )
            },
        ),
        (
            "Debug",
            {
                "classes": ("collapse",),
                "fields": (
                    "latest_raw_ai_response",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )
    save_on_top = True
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
        "suggested_price",
        "appointment_date",
        "appointment_time",
        "confidence_level",
        "created_at",
    )
    list_filter = ("endpoint", "risk_level", "confidence_level", "created_at")
    list_editable = ("risk_level", "suggested_price")
    search_fields = (
        "lead__name",
        "lead__phone_number",
        "lead__email",
        "tattoo_idea",
        "suggested_artist",
        "summary",
        "suggested_price",
    )
    readonly_fields = ("created_at",)
    raw_id_fields = ("intake", "lead", "message")
    fieldsets = (
        (
            "Links",
            {
                "fields": (
                    "intake",
                    "lead",
                    "message",
                    "endpoint",
                )
            },
        ),
        (
            "AI Summary And Pricing",
            {
                "fields": (
                    "summary",
                    "suggested_price",
                    "pricing_reasoning",
                    "draft_reply",
                    "appointment_date",
                    "appointment_time",
                )
            },
        ),
        (
            "Tattoo Details",
            {
                "fields": (
                    "tattoo_idea",
                    "style_tags",
                    "placement",
                    "size_estimate_cm",
                    "color_preference",
                    "suggested_artist",
                    "missing_information",
                )
            },
        ),
        (
            "Risk And Reasoning",
            {
                "fields": (
                    "risk_level",
                    "confidence_level",
                    "ai_reasoning",
                )
            },
        ),
        (
            "Debug",
            {
                "classes": ("collapse",),
                "fields": (
                    "raw_response",
                    "created_at",
                ),
            },
        ),
    )
    save_on_top = True
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


@admin.register(OutboundAction)
class OutboundActionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "intake",
        "lead",
        "actor",
        "source",
        "action_type",
        "status",
        "created_at",
        "sent_at",
    )
    list_filter = ("source", "action_type", "status", "actor", "created_at")
    search_fields = ("intake__lead__name", "intake__lead__phone_number", "intake__lead__email", "text", "error_message")
    readonly_fields = ("media_items", "provider_response", "created_at", "updated_at", "sent_at")
    ordering = ("-created_at",)
