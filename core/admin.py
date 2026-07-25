from django.contrib import admin
from .models import WebhookLog, WhatsAppAccount, OutlookAccount, WebhookSubscription, OutlookAccessToken




from django.contrib import admin
from .models import WebhookLog


@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source",
        "method",
        "path",
        "ip_address",
        "created_at",
    )

    list_filter = (
        "source",
        "method",
        "created_at",
    )

    search_fields = (
        "path",
        "ip_address",
        "body",
    )

    readonly_fields = (
        "method",
        "source",
        "path",
        "headers",
        "payload",
        "body",
        "ip_address",
        "created_at",
    )

    ordering = ("-created_at",)

    date_hierarchy = "created_at"

    list_per_page = 50

    list_select_related = False

    fieldsets = (
        (
            "Request Information",
            {
                "fields": (
                    "source",
                    "method",
                    "path",
                    "ip_address",
                    "created_at",
                )
            },
        ),
        (
            "Headers",
            {
                "fields": ("headers",),
                "classes": ("collapse",),
            },
        ),
        (
            "Payload",
            {
                "fields": ("payload",),
            },
        ),
        (
            "Raw Body",
            {
                "fields": ("body",),
                "classes": ("collapse",),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

admin.site.register(WhatsAppAccount)
admin.site.register(OutlookAccount)
admin.site.register(WebhookSubscription)
admin.site.register(OutlookAccessToken)
