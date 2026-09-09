from django.contrib import admin

from intake.models import AIAnalysis, ArtistProfile, ExternalArtistOffer, HumanDecision, IntakeRequest, OutboundAction, TelegramMessageLink


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
        "client_name",
        "status",
        "risk_level",
        "assigned_artist",
        "suggested_artist",
        "approved_price",
        "ai_suggested_price",
        "appointment_type",
        "preferred_artist",
        "appointment_date",
        "appointment_time",
        "scheduled_service_code",
        "schedule_status",
        "pending_hold_status",
        "pending_hold_expires_at",
        "payment_status",
        "confidence_level",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "status",
        "risk_level",
        "confidence_level",
        "appointment_type",
        "auto_reply_allowed",
        "telegram_review_required",
        "assigned_artist",
        "source",
        "schedule_status",
        "pending_hold_status",
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
        "client_name",
        "preferred_artist",
        "appointment_type",
        "tattoo_project_type",
        "suggested_artist",
        "latest_summary",
        "approved_price",
        "ai_suggested_price",
        "vcita_matter_uid",
        "vcita_booking_uid",
        "scheduled_service_code",
        "scheduled_service_name",
        "scheduled_service_uid",
        "pending_hold_service_code",
        "pending_hold_service_name",
        "pending_hold_service_uid",
        "pending_hold_error",
    )
    readonly_fields = ("latest_raw_ai_response", "created_at", "updated_at")
    raw_id_fields = (
        "lead",
        "conversation",
        "whatsapp_account",
        "outlook_account",
        "last_incoming_message",
        "scheduled_service",
        "pending_hold_service",
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
                    "auto_reply_allowed",
                    "telegram_review_required",
                )
            },
        ),
        (
            "Tattoo Details",
            {
                "fields": (
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
                    "vcita_matter_uid",
                    "vcita_booking_uid",
                    "pending_hold_status",
                    "pending_hold_date",
                    "pending_hold_time",
                    "pending_hold_service",
                    "pending_hold_service_code",
                    "pending_hold_service_name",
                    "pending_hold_service_uid",
                    "pending_hold_expires_at",
                    "pending_hold_review_notified_at",
                    "pending_hold_released_at",
                    "pending_hold_finalized_at",
                    "pending_hold_error",

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
        "client_name",
        "suggested_artist",
        "suggested_price",
        "appointment_type",
        "appointment_date",
        "appointment_time",
        "confidence_level",
        "created_at",
    )
    list_filter = (
        "endpoint",
        "risk_level",
        "confidence_level",
        "appointment_type",
        "auto_reply_allowed",
        "telegram_review_required",
        "created_at",
    )
    list_editable = ("risk_level", "suggested_price")
    search_fields = (
        "lead__name",
        "lead__phone_number",
        "lead__email",
        "tattoo_idea",
        "client_name",
        "preferred_artist",
        "appointment_type",
        "tattoo_project_type",
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
                    "auto_reply_allowed",
                    "telegram_review_required",
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



@admin.register(ExternalArtistOffer)
class ExternalArtistOfferAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "intake",
        "artist",
        "offered_by",
        "status",
        "telegram_chat_id",
        "telegram_message_id",
        "client_contact_released_at",
        "responded_at",
        "created_at",
    )
    list_filter = ("status", "artist", "offered_by", "created_at", "responded_at")
    search_fields = (
        "intake__lead__name",
        "intake__lead__phone_number",
        "intake__lead__email",
        "artist__name",
        "safe_brief",
    )
    readonly_fields = (
        "safe_brief",
        "telegram_chat_id",
        "telegram_message_id",
        "client_contact_released_at",
        "responded_at",
        "raw_update",
        "created_at",
        "updated_at",
    )
    raw_id_fields = ("intake", "artist", "offered_by")
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
