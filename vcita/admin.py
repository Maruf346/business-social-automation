from django.contrib import admin, messages

from .api import VcitaAPIClient, VcitaAPIError
from .models import VcitaAccount, VcitaWebhookEvent


@admin.register(VcitaAccount)
class VcitaAccountAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "business_uid",
        "default_service_uid",
        "default_timezone",
        "api_base_url",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("name", "business_uid", "business_name", "default_service_uid", "api_base_url", "notes")
    actions = ("test_api_token", "sync_userinfo", "show_active_staff", "show_services")
    fieldsets = (
        (
            "Account",
            {
                "fields": (
                    "name",
                    "is_active",
                    "api_base_url",
                    "business_uid",
                    "business_name",
                    "default_service_uid",
                    "default_timezone",
                    "webhook_secret",
                )
            },
        ),
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

    @admin.action(description="Sync vCita business info from token")
    def sync_userinfo(self, request, queryset):
        for account in queryset:
            try:
                response = VcitaAPIClient(account).userinfo()
            except VcitaAPIError as exc:
                self.message_user(
                    request,
                    f"{account.name}: user info sync failed ({exc.status_code or 'no status'}): {exc}",
                    level=messages.ERROR,
                )
                continue
            business_uid = response.get("business_uid") or response.get("business_id") or ""
            business_name = response.get("business_name") or ""
            if not business_uid:
                self.message_user(request, f"{account.name}: user info did not include business UID.", level=messages.ERROR)
                continue
            account.business_uid = business_uid
            account.business_name = business_name
            account.save(update_fields=["business_uid", "business_name", "updated_at"])
            self.message_user(
                request,
                f"{account.name}: synced business UID {business_uid} ({business_name or 'no business name'}).",
                level=messages.SUCCESS,
            )

    @admin.action(description="Show active vCita staff IDs")
    def show_active_staff(self, request, queryset):
        for account in queryset:
            if not account.business_uid:
                self.message_user(request, f"{account.name}: add or sync business UID first.", level=messages.ERROR)
                continue
            try:
                response = VcitaAPIClient(account).list_staff(account.business_uid)
            except VcitaAPIError as exc:
                self.message_user(
                    request,
                    f"{account.name}: staff lookup failed ({exc.status_code or 'no status'}): {exc}",
                    level=messages.ERROR,
                )
                continue
            preview = self._format_reference_preview(response)
            self.message_user(request, f"{account.name}: staff response preview: {preview}", level=messages.INFO)

    @admin.action(description="Show vCita service IDs")
    def show_services(self, request, queryset):
        for account in queryset:
            if not account.business_uid:
                self.message_user(request, f"{account.name}: add or sync business UID first.", level=messages.ERROR)
                continue
            try:
                response = VcitaAPIClient(account).list_services(account.business_uid)
            except VcitaAPIError as exc:
                self.message_user(
                    request,
                    f"{account.name}: service lookup failed ({exc.status_code or 'no status'}): {exc}",
                    level=messages.ERROR,
                )
                continue
            preview = self._format_reference_preview(response)
            self.message_user(request, f"{account.name}: service response preview: {preview}", level=messages.INFO)

    @staticmethod
    def _format_reference_preview(response):
        text = str(response)
        if len(text) > 1200:
            return f"{text[:1200]}..."
        return text


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
