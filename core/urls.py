from django.urls import path
from .views import WhatsappWebhook, OutlookWebhook


urlpatterns = [
    path("webhook/meta/", WhatsappWebhook.as_view(), name="webhook-meta"),
    path("webhook/outlook/", OutlookWebhook.as_view(), name="webhook-outlook")
]

