from django.contrib import admin
from .models import Lead, Message, MediaFile, Tag, LeadTag


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "source", "phone_number", "email", "last_message_at", "created_at")
    list_filter = ("source", "is_blocked", "created_at")
    search_fields = ("name", "phone_number", "email")
    ordering = ("-created_at",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "conversation", "direction", "send_by", "message_type", "status", "timestamp")
    list_filter = ("direction", "send_by", "message_type", "status", "created_at")
    search_fields = ("lead__name", "lead__phone_number", "lead__email", "content", "provider_message_id")
    ordering = ("-timestamp",)


admin.site.register(MediaFile)
admin.site.register(Tag)
admin.site.register(LeadTag)

