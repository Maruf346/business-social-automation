from django.db import models


class IntakeStatus(models.TextChoices):
    COLLECTING_INFO = "collecting_info", "Collecting Info"
    WAITING_FOR_HUMAN = "waiting_for_human", "Waiting for Human"
    READY_FOR_REVIEW = "ready_for_review", "Ready for Review"
    APPROVED = "approved", "Approved"
    CLOSED = "closed", "Closed"


class RiskLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    UNKNOWN = "unknown", "Unknown"


class ConfidenceLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    UNKNOWN = "unknown", "Unknown"


class IntakeRequest(models.Model):
    lead = models.ForeignKey("lead.Lead", on_delete=models.CASCADE, related_name="intake_requests")
    conversation = models.ForeignKey(
        "lead.Conversation",
        on_delete=models.SET_NULL,
        related_name="intake_requests",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=40,
        choices=IntakeStatus.choices,
        default=IntakeStatus.COLLECTING_INFO,
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)

    tattoo_idea = models.TextField(blank=True, default="")
    style_tags = models.JSONField(default=list, blank=True)
    placement = models.CharField(max_length=255, blank=True, default="")
    size_estimate_cm = models.CharField(max_length=100, blank=True, default="")
    color_preference = models.CharField(max_length=100, blank=True, default="")

    suggested_artist = models.CharField(max_length=100, blank=True, default="")
    confidence_level = models.CharField(
        max_length=20,
        choices=ConfidenceLevel.choices,
        default=ConfidenceLevel.UNKNOWN,
        db_index=True,
    )
    ai_reasoning = models.TextField(blank=True, default="")
    missing_information = models.JSONField(default=list, blank=True)
    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
        default=RiskLevel.UNKNOWN,
        db_index=True,
    )
    latest_draft_reply = models.TextField(blank=True, default="")
    latest_raw_ai_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["lead", "is_active"]),
            models.Index(fields=["conversation", "is_active"]),
            models.Index(fields=["risk_level"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Intake #{self.pk} for lead #{self.lead_id}"


class AIAnalysis(models.Model):
    intake = models.ForeignKey(IntakeRequest, on_delete=models.CASCADE, related_name="ai_analyses")
    lead = models.ForeignKey("lead.Lead", on_delete=models.CASCADE, related_name="ai_analyses")
    message = models.ForeignKey(
        "lead.Message",
        on_delete=models.SET_NULL,
        related_name="ai_analyses",
        blank=True,
        null=True,
    )

    endpoint = models.CharField(max_length=100, default="analyze")

    tattoo_idea = models.TextField(blank=True, default="")
    style_tags = models.JSONField(default=list, blank=True)
    placement = models.CharField(max_length=255, blank=True, default="")
    size_estimate_cm = models.CharField(max_length=100, blank=True, default="")
    color_preference = models.CharField(max_length=100, blank=True, default="")
    suggested_artist = models.CharField(max_length=100, blank=True, default="")
    confidence_level = models.CharField(
        max_length=20,
        choices=ConfidenceLevel.choices,
        default=ConfidenceLevel.UNKNOWN,
        db_index=True,
    )
    ai_reasoning = models.TextField(blank=True, default="")
    missing_information = models.JSONField(default=list, blank=True)
    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
        default=RiskLevel.UNKNOWN,
        db_index=True,
    )
    draft_reply = models.TextField(blank=True, default="")
    raw_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intake", "created_at"]),
            models.Index(fields=["lead", "created_at"]),
            models.Index(fields=["message"]),
            models.Index(fields=["risk_level"]),
        ]

    def __str__(self):
        return f"AI analysis #{self.pk} for intake #{self.intake_id}"
