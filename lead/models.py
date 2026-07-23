from django.db.models import Q

from .choices import MESSAGE_DIRECTION, MESSAGE_TYPE, MESSAGE_STATUS, SEND_BY, LEAD_SOURCE
from django.db import models
import uuid
from django.utils import timezone


class Lead(models.Model):
    source = models.CharField(max_length=20, choices=LEAD_SOURCE.choices, default=LEAD_SOURCE.OTHERS)

    name = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True ,null=True)
    email = models.EmailField(max_length=255, blank=True ,null=True)

    profile_pic = models.URLField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)
    
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "phone_number"],
                condition=Q(phone_number__isnull=False),
                name="unique_phone_source"
            ),
            models.UniqueConstraint(
                fields=["source", "email"],
                condition=Q(email__isnull=False),
                name="unique_email_source"
            )
        ]
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['source', 'phone_number'])
        ]
    
    def __str__(self):
        return self.phone_number or self.email or self.pk

class Conversation(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="conversations")
    conversation_id = models.CharField(max_length=255, unique=True, db_index=True)
    subject = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, db_index=True)
    is_active = models.BooleanField(default=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Message(models.Model):
    provider_message_id = models.CharField(max_length=500, blank=True, null=True)
    internet_message_id = models.CharField(max_length=500, blank=True, null=True)
    conversation_message_id = models.CharField(max_length=500, blank=True, null=True)

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="messages", editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, blank=True, null=True)
    send_by = models.CharField(max_length=50, choices=SEND_BY.choices, default=SEND_BY.AI)

    direction = models.CharField(max_length=20, choices=MESSAGE_DIRECTION.choices)
    message_type = models.CharField(max_length=50, choices=MESSAGE_TYPE.choices, default=MESSAGE_TYPE.TEXT)

    subject = models.CharField(max_length=500, blank=True, null=True)
    content = models.TextField(null=True, blank=True)
    html_content = models.TextField(null=True, blank=True)
    file = models.FileField(upload_to='messages/', null=True, blank=True)
    meta_data = models.JSONField(default=dict)
    raw_payload = models.JSONField(default=dict)

    status = models.CharField(max_length=50, choices=MESSAGE_STATUS.choices, default=MESSAGE_STATUS.SENT)
    error_message = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    read = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.status == MESSAGE_STATUS.READ:
            self.read = True
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=['provider_message_id']),
            models.Index(fields=['lead']),
        ]

class MediaFile(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="media_files")
    media_type = models.CharField(max_length=50, db_index=True)
    mime_type = models.CharField(max_length=100, blank=True, default="")
    file = models.FileField(upload_to="media/")
    file_name = models.CharField(max_length=255, blank=True, default="")
    file_size = models.PositiveBigIntegerField(default=0)

    download_url = models.URLField(blank=True, default="")
    provider_media_id = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Tag(models.Model):
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class LeadTag(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("lead", "tag")



