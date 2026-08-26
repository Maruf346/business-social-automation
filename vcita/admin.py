from django.contrib import admin, messages

from .api import VcitaAPIClient, VcitaAPIError
from .models import VcitaAccount, VcitaWebhookEvent


@admin.register(VcitaAccount)
class VcitaAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "api_base_url", "is_active", "updated_at")
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("name", "api_base_url", "notes")
    actions = ("test_api_token",)
    fieldsets = (
        ("Account", {"fields": ("name", "is_active", "api_base_url")}),
        ("Credentials", {"fields": ("api_token",)}),
        ("Notes", {"fields": ("notes",)}),
    )

    @admin.action(description="Test selected vCita API token")
    def test_api_token(self, request, queryset):
        for account in queryset:
            try:
                response = VcitaAPIClient(account).list_webhooks()
            except VcitaAPIError as exc:
                self.message_user(
                    request,
                    f"{account.name}: API check failed ({exc.status_code or 'no status'}): {exc}",
                    level=messages.ERROR,
                )
                continue
            status_value = response.get("status", "OK")
            self.message_user(request, f"{account.name}: API check succeeded ({status_value}).", level=messages.SUCCESS)


@admin.register(VcitaWebhookEvent)
class VcitaWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "entity", "external_id", "status", "account", "created_at")
    list_filter = ("status", "event_type", "entity", "created_at")
    search_fields = ("event_type", "entity", "external_id", "body", "processing_error")
    readonly_fields = (
        "account",
        "method",
        "path",
        "headers",
        "payload",
        "body",
        "ip_address",
        "event_type",
        "entity",
        "external_id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Event", {"fields": ("account", "status", "event_type", "entity", "external_id")}),
        ("Request", {"fields": ("method", "path", "ip_address", "headers")}),
        ("Payload", {"fields": ("payload", "body")}),
        ("Processing", {"fields": ("processing_error", "created_at", "updated_at")}),
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50

    def has_add_permission(self, request):
        return False
