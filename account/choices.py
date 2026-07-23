from django.db import models

class UserType(models.TextChoices):
    STAFF = "STAFF", "Staff"
    ADMIN = "ADMIN", "Admin"
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"

class DeviceType(models.TextChoices):
    ANDROID = "ANDROID", "Android"
    IOS = "IOS", "iOS"
    WEB = "WEB", "Web"

