from django.db import models

class WebhookSource(models.TextChoices):
    META = "meta", "Meta"
    WHATSAPP = "whatsapp", "Whatsapp"
    FACEBOOK = "facebook", "Facebook"
    INSTAGRAM = "instagram", "Instagram"
    OUTLOOK = "outlook", "Outlook"
    OTHERS = "others", "Others"
