from .choices import MESSAGE_DIRECTION, MESSAGE_TYPE, MESSAGE_STATUS, SEND_BY, LEAD_SOURCE
from django.db import models
import uuid
from django.utils import timezone

class Lead(models.Model):
    source = models.CharField(max_length=20, choices=LEAD_SOURCE.choices, default=LEAD_SOURCE.OTHERS)

    name = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=20)

    profile_pic = models.URLField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)
    
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('source', 'phone_number')
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['source', 'phone_number'])
        ]
    
    def __str__(self):
        return self.phone_number or self.pk

class Message(models.Model):
    system_id = models.CharField(max_length=500, blank=True, null=True)

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="messages", editable=False)
    send_by = models.CharField(max_length=50, choices=SEND_BY.choices, default=SEND_BY.AI)

    direction = models.CharField(max_length=20, choices=MESSAGE_DIRECTION.choices)
    message_type = models.CharField(max_length=50, choices=MESSAGE_TYPE.choices, default=MESSAGE_TYPE.TEXT)
    
    content = models.TextField(null=True, blank=True)
    file = models.FileField(upload_to='messages/', null=True, blank=True)

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
            models.Index(fields=['system_id']),
            models.Index(fields=['lead']),
        ]

class MediaFile(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="media_files")
    media_type = models.CharField(max_length=50)
    file = models.FileField(upload_to="media/")
    meta_media_id = models.CharField(max_length=255)
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



