# pyrefly: ignore [missing-import]
from django.db import models


class LEAD_SOURCE(models.TextChoices):
    META = "meta", "Meta"
    WHATSAPP = "whatsapp", "Whatsapp"
    FACEBOOK = "facebook", "Facebook"
    INSTAGRAM = "instagram", "Instagram"
    OUTLOOK = "outlook", "Outlook"
    OTHERS = "others", "Others"


class MESSAGE_DIRECTION(models.TextChoices):
    INCOMING = "Incoming"
    OUTGOING = "Outgoing"


class MESSAGE_TYPE(models.TextChoices):
    TEXT = "Text"
    IMAGE = "Image"
    AUDIO = "Audio"
    VIDEO = "Video"
    FILE = "File"


class SEND_BY(models.TextChoices):
    AI = "AI"
    AGENT = "AGENT"
    CLIENT = "CLIENT"


class MESSAGE_STATUS(models.TextChoices):
    SENT = "Sent"
    RECEIVED = "Received"
    DELIVERED = "Delivered"
    READ = "Read"
    FAILED = "Failed"
