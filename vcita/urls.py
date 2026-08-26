from django.urls import path

from .views import VcitaWebhook


urlpatterns = [
    path("webhook/vcita/", VcitaWebhook.as_view(), name="webhook-vcita"),
]
