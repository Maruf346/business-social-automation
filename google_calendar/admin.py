from django.contrib import admin, messages

from .models import GoogleCalendarConfig, GoogleCalendarEvent
from .services import GoogleCalendarError, GoogleCalendarService


@admin.register(GoogleCalendarConfig)
class GoogleCalendarConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "calendar_type",
        "artist",
        "calendar_id",
        "timezone",
        "is_active",
        "updated_at",
    )
    list_filter = ("calendar_type", "is_active", "timezone", "created_at", "updated_at")
    search_fields = ("name", "calendar_id", "artist__name", "notes")
    raw_id_fields = ("artist",)
    actions = ("test_freebusy_access",)
    fieldsets = (
        (
            "Calendar Mapping",
            {
                "fields": (
                    "name",
                    "calendar_type",
                    "artist",
                    "calendar_id",
                    "timezone",
                    "is_active",
                )
            },
        ),
        ("Notes", {"fields": ("notes",)}),
    )

    @admin.action(description="Test selected Google Calendar access")
    def test_freebusy_access(self, request, queryset):
        for calendar in queryset:
            try:
                GoogleCalendarService().test_calendar_access(calendar)
            except GoogleCalendarError as exc:
                self.message_user(
                    request,
                    f"{calendar.name}: Google Calendar check failed: {exc}",
                    level=messages.ERROR,
                )
                continue
            self.message_user(
                request,
                f"{calendar.name}: Google Calendar access succeeded.",
                level=messages.SUCCESS,
            )


@admin.register(GoogleCalendarEvent)
class GoogleCalendarEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "intake",
        "calendar",
        "event_type",
        "google_event_id",
        "status",
        "start_at",
        "end_at",
        "updated_at",
    )
    list_filter = ("event_type", "status", "calendar", "created_at", "updated_at")
    search_fields = (
        "intake__lead__name",
        "intake__lead__phone_number",
        "intake__lead__email",
        "calendar__name",
        "google_event_id",
        "summary",
        "description",
        "sync_error",
    )
    readonly_fields = (
        "intake",
        "calendar",
        "event_type",
        "google_event_id",
        "status",
        "start_at",
        "end_at",
        "summary",
        "description",
        "sync_error",
        "raw_response",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
