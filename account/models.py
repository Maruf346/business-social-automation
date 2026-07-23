from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .choices import UserType, DeviceType
from .managers import UserManager

class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(max_length=200, unique=True, db_index=True)
    name = models.CharField(max_length=100, blank=True)
    user_type = models.CharField(max_length=20, choices=UserType.choices, default=UserType.ADMIN)

    is_phone_verified = models.BooleanField(default=False)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    last_password_changed_at = models.DateTimeField(blank=True, null=True)
    last_activity_at = models.DateTimeField(blank=True, null=True, db_index=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["last_activity_at"]),
        ]

    def __str__(self):
        return self.email


class Device(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=255)
    device_name = models.CharField(max_length=255)
    device_type = models.CharField(max_length=20, choices=DeviceType.choices)
    
    os_version = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=50, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    
    fcm_token = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    last_seen_at = models.DateTimeField(auto_now=True, db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "user_devices"
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "device_id"],
                name="unique_user_device",
            )
        ]

        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["device_type"]),
            models.Index(fields=["last_seen_at"]),
        ]

    def __str__(self):
        return f"{self.user.phone_number} - {self.device_name}"



