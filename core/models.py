from django.db import models
from .choices import WebhookSource
from django.utils import timezone
from datetime import timedelta

class WhatsAppAccount(models.Model):
    meta_business_id = models.CharField(max_length=255, blank=True, null=True)
    waba_id = models.CharField(max_length=255)
    phone_number_id = models.CharField(max_length=255)
    display_phone_number = models.CharField(max_length=50)

    token_data = models.JSONField(blank=True, null=True)
    # refresh_token = models.TextField(null=True, blank=True)
    # token_expiry = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    quality_rating = models.CharField(max_length=50, null=True, blank=True)
    messaging_limit_tier = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['phone_number_id']),
        ]


class OutlookAccount(models.Model):
    business_mail = models.EmailField(unique=True)
    client_id = models.CharField(max_length=255)
    client_secret = models.CharField(max_length=255)
    tenant_id = models.CharField(max_length=255)
    secret_id = models.CharField(max_length=255, blank=True, null=True)
    api_endpoint = models.URLField(default="https://graph.microsoft.com/v1.0")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class WebhookSubscription(models.Model):
    outlook = models.OneToOneField(OutlookAccount, on_delete=models.CASCADE, related_name="subscription")

    subscription_id = models.CharField(max_length=255, blank=True, null=True)
    notification_url = models.URLField()
    resource = models.CharField(max_length=255, default="")
    change_type = models.CharField(max_length=50, default="created")
    client_state = models.CharField(max_length=255, null=True, blank=True)
    expiration_date = models.DateTimeField()
    status = models.CharField(max_length=20, default="pending")
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class OutlookAccessToken(models.Model):
    outlook = models.OneToOneField(OutlookAccount, on_delete=models.CASCADE, related_name="access_token")

    scope = models.CharField(max_length=255, blank=True, null=True)
    grant_type = models.CharField(max_length=50, default="client_credentials")
    token_type = models.CharField(max_length=50, blank=True, null=True)

    expires_in = models.PositiveIntegerField(default=0)
    ext_expires_in = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(blank=True, null=True)

    access_token = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        expires_in = self.expires_in
        self.expires_at = (timezone.now() + timedelta(seconds=expires_in))
        return super().save(*args, **kwargs)



class WebhookLog(models.Model):
    method = models.CharField(max_length=10, blank=True, null=True)
    source = models.CharField(max_length=20, choices=WebhookSource.choices, default=WebhookSource.OTHERS)
    path = models.CharField(max_length=255, blank=True, null=True)
    headers = models.JSONField(default=dict)
    payload = models.JSONField(default=dict)
    body = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

