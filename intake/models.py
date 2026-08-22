from django.db import models


class IntakeStatus(models.TextChoices):
    COLLECTING_INFO = "collecting_info", "Collecting Info"
    WAITING_FOR_HUMAN = "waiting_for_human", "Waiting for Human"
    READY_FOR_REVIEW = "ready_for_review", "Ready for Review"
    ASSIGNED = "assigned", "Assigned"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
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


class IntakeSource(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    OUTLOOK = "outlook", "Outlook"
    OTHER = "other", "Other"


class HumanDecisionAction(models.TextChoices):
    APPROVE_AI_REPLY = "approve_ai_reply", "Approve AI Reply"
    REJECT = "reject", "Reject"
    ASSIGN_ARTIST = "assign_artist", "Assign Artist"
    NEEDS_MANUAL_REPLY = "needs_manual_reply", "Needs Manual Reply"
    ARTIST_REPLY = "artist_reply", "Artist Reply"


class TelegramMessagePurpose(models.TextChoices):
    GROUP_REVIEW = "group_review", "Group Review"
    ARTIST_ASSIGNMENT = "artist_assignment", "Artist Assignment"
    CLIENT_UPDATE = "client_update", "Client Update"
    BOT_INFO = "bot_info", "Bot Info"


class ArtistProfile(models.Model):
    name = models.CharField(max_length=100, unique=True)
    telegram_user_id = models.BigIntegerField(blank=True, null=True, unique=True)
    telegram_chat_id = models.BigIntegerField(blank=True, null=True)
    can_approve = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    specialties = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [
            models.Index(fields=["is_active", "sort_order"]),
            models.Index(fields=["can_approve"]),
        ]

    def __str__(self):
        return self.name


class IntakeRequest(models.Model):
    lead = models.ForeignKey("lead.Lead", on_delete=models.CASCADE, related_name="intake_requests")
    conversation = models.ForeignKey(
        "lead.Conversation",
        on_delete=models.SET_NULL,
        related_name="intake_requests",
        blank=True,
        null=True,
    )
    assigned_artist = models.ForeignKey(
        ArtistProfile,
        on_delete=models.SET_NULL,
        related_name="assigned_intakes",
        blank=True,
        null=True,
    )
    source = models.CharField(
        max_length=20,
        choices=IntakeSource.choices,
        default=IntakeSource.OTHER,
        db_index=True,
    )
    whatsapp_account = models.ForeignKey(
        "core.WhatsAppAccount",
        on_delete=models.SET_NULL,
        related_name="intake_requests",
        blank=True,
        null=True,
    )
    outlook_account = models.ForeignKey(
        "core.OutlookAccount",
        on_delete=models.SET_NULL,
        related_name="intake_requests",
        blank=True,
        null=True,
    )
    last_incoming_message = models.ForeignKey(
        "lead.Message",
        on_delete=models.SET_NULL,
        related_name="latest_for_intakes",
        blank=True,
        null=True,
    )
    outlook_user_id = models.CharField(max_length=255, blank=True, default="")

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
            models.Index(fields=["assigned_artist", "is_active"]),
            models.Index(fields=["source"]),
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


class HumanDecision(models.Model):
    intake = models.ForeignKey(IntakeRequest, on_delete=models.CASCADE, related_name="human_decisions")
    actor = models.ForeignKey(
        ArtistProfile,
        on_delete=models.SET_NULL,
        related_name="human_decisions",
        blank=True,
        null=True,
    )
    assigned_artist = models.ForeignKey(
        ArtistProfile,
        on_delete=models.SET_NULL,
        related_name="assignment_decisions",
        blank=True,
        null=True,
    )
    action = models.CharField(max_length=40, choices=HumanDecisionAction.choices, db_index=True)
    note = models.TextField(blank=True, default="")
    telegram_chat_id = models.BigIntegerField(blank=True, null=True)
    telegram_message_id = models.BigIntegerField(blank=True, null=True)
    telegram_callback_id = models.CharField(max_length=255, blank=True, default="")
    raw_update = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intake", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.action} for intake #{self.intake_id}"


class TelegramMessageLink(models.Model):
    intake = models.ForeignKey(IntakeRequest, on_delete=models.CASCADE, related_name="telegram_links")
    lead = models.ForeignKey("lead.Lead", on_delete=models.CASCADE, related_name="telegram_links")
    artist = models.ForeignKey(
        ArtistProfile,
        on_delete=models.SET_NULL,
        related_name="telegram_links",
        blank=True,
        null=True,
    )
    purpose = models.CharField(max_length=40, choices=TelegramMessagePurpose.choices, db_index=True)
    telegram_chat_id = models.BigIntegerField(db_index=True)
    telegram_message_id = models.BigIntegerField(db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    raw_message = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["telegram_chat_id", "telegram_message_id"],
                name="unique_telegram_message_link",
            )
        ]
        indexes = [
            models.Index(fields=["telegram_chat_id", "telegram_message_id"]),
            models.Index(fields=["intake", "purpose"]),
            models.Index(fields=["artist", "is_active"]),
        ]

    def __str__(self):
        return f"{self.purpose} message {self.telegram_message_id} for intake #{self.intake_id}"
