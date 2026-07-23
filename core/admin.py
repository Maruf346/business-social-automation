from django.contrib import admin
from .models import WebhookLog, WhatsAppAccount

admin.site.register(WebhookLog)
admin.site.register(WhatsAppAccount)
