from django.db import models


class GoogleCalendarType(models.TextChoices):
    PENDING = "pending", "Pending Appointments"
    ARTIST = "artist", "Artist Calendar"
    SHARED_VCITA = "shared_vcita", "Shared vCita Calendar"


class GoogleCalendarEventType(models.TextChoices):
    CONFIRMED_APPOINTMENT = "confirmed_appointment", "Confirmed Appointment"
    PENDING_HOLD = "pending_hold", "Pending Hold"


class GoogleCalendarSyncStatus(models.TextChoices):
    SYNCED = "synced", "Synced"
    FAILED = "failed", "Failed"
    RELEASED = "released", "Released"


class GoogleCalendarConfig(models.Model):
    name = models.CharField(max_length=150)
    calendar_type = models.CharField(
        max_length=30,
        choices=GoogleCalendarType.choices,
        db_index=True,
    )
    artist = models.ForeignKey(
        "intake.ArtistProfile",
        on_delete=models.SET_NULL,
        related_name="google_calendars",
        blank=True,
        null=True,
    )
    calendar_id = models.CharField(max_length=255, unique=True)
    timezone = models.CharField(max_length=100, default="Europe/Amsterdam")
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["calendar_type", "name"]
        indexes = [
            models.Index(fields=["calendar_type", "is_active"]),
            models.Index(fields=["artist", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_calendar_type_display()})"


class GoogleCalendarEvent(models.Model):
    intake = models.ForeignKey(
        "intake.IntakeRequest",
        on_delete=models.CASCADE,
        related_name="google_calendar_events",
    )
    calendar = models.ForeignKey(
        GoogleCalendarConfig,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(
        max_length=40,
        choices=GoogleCalendarEventType.choices,
        default=GoogleCalendarEventType.CONFIRMED_APPOINTMENT,
        db_index=True,
    )
    google_event_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    status = models.CharField(
        max_length=30,
        choices=GoogleCalendarSyncStatus.choices,
        default=GoogleCalendarSyncStatus.SYNCED,
        db_index=True,
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    summary = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    sync_error = models.TextField(blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intake", "event_type"]),
            models.Index(fields=["calendar", "status"]),
            models.Index(fields=["google_event_id"]),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} for intake #{self.intake_id}"
