from django.db import models


class VcitaWebhookStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    UNMATCHED = "unmatched", "Unmatched"
    FAILED = "failed", "Failed"


class VcitaFinancialRecordType(models.TextChoices):
    INVOICE = "invoice", "Invoice"
    DEPOSIT = "deposit", "Deposit"
    PAYMENT = "payment", "Payment"


class VcitaFinancialRecordStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    ISSUED = "issued", "Issued"
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    RECORDED = "recorded", "Recorded"
    UPDATED = "updated", "Updated"
    CANCELLED = "cancelled", "Cancelled"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class VcitaScheduleProvider(models.TextChoices):
    VCITA = "vcita", "vCita"
    GOOGLE_ONLY = "google_only", "Google Calendar only"


class VcitaAccount(models.Model):
    name = models.CharField(max_length=150, default="Default vCita")
    api_token = models.TextField()
    api_base_url = models.URLField(default="https://api.vcita.biz")
    business_uid = models.CharField(max_length=255, blank=True, default="")
    business_name = models.CharField(max_length=255, blank=True, default="")
    default_service_uid = models.CharField(max_length=255, blank=True, default="")
    external_booking_staff_uid = models.CharField(max_length=255, blank=True, default="")
    vcita_matter_name_field_uid = models.CharField(max_length=255, blank=True, default="")
    default_timezone = models.CharField(max_length=100, default="Europe/Amsterdam")
    webhook_secret = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.name


class VcitaService(models.Model):
    account = models.ForeignKey(
        VcitaAccount,
        on_delete=models.CASCADE,
        related_name="services",
    )
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=255)
    vcita_service_uid = models.CharField(max_length=255)
    schedule_provider = models.CharField(
        max_length=30,
        choices=VcitaScheduleProvider.choices,
        default=VcitaScheduleProvider.VCITA,
        db_index=True,
    )
    use_external_booking_staff = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["account", "code"], name="unique_vcita_service_code_per_account"),
            models.UniqueConstraint(
                fields=["account", "vcita_service_uid"],
                name="unique_vcita_service_uid_per_account",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active", "code"]),
        ]

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"


class VcitaWebhookEvent(models.Model):
    account = models.ForeignKey(
        VcitaAccount,
        on_delete=models.SET_NULL,
        related_name="webhook_events",
        blank=True,
        null=True,
    )
    method = models.CharField(max_length=10, blank=True, default="")
    path = models.CharField(max_length=255, blank=True, default="")
    headers = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    body = models.TextField(blank=True, default="")
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    event_type = models.CharField(max_length=100, blank=True, default="", db_index=True)
    entity = models.CharField(max_length=100, blank=True, default="", db_index=True)
    external_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    status = models.CharField(
        max_length=30,
        choices=VcitaWebhookStatus.choices,
        default=VcitaWebhookStatus.RECEIVED,
        db_index=True,
    )
    processing_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["entity", "created_at"]),
            models.Index(fields=["external_id"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        label = self.event_type or "webhook"
        return f"vCita {label} event #{self.pk}"


class VcitaFinancialRecord(models.Model):
    account = models.ForeignKey(
        VcitaAccount,
        on_delete=models.SET_NULL,
        related_name="financial_records",
        blank=True,
        null=True,
    )
    intake = models.ForeignKey(
        "intake.IntakeRequest",
        on_delete=models.CASCADE,
        related_name="vcita_financial_records",
        blank=True,
        null=True,
    )
    lead = models.ForeignKey(
        "lead.Lead",
        on_delete=models.SET_NULL,
        related_name="vcita_financial_records",
        blank=True,
        null=True,
    )
    last_webhook_event = models.ForeignKey(
        VcitaWebhookEvent,
        on_delete=models.SET_NULL,
        related_name="financial_records",
        blank=True,
        null=True,
    )
    record_type = models.CharField(max_length=20, choices=VcitaFinancialRecordType.choices, db_index=True)
    vcita_uid = models.CharField(max_length=255, db_index=True)
    matter_uid = models.CharField(max_length=255, blank=True, default="", db_index=True)
    status = models.CharField(
        max_length=30,
        choices=VcitaFinancialRecordStatus.choices,
        default=VcitaFinancialRecordStatus.UNKNOWN,
        db_index=True,
    )
    amount = models.CharField(max_length=100, blank=True, default="")
    currency = models.CharField(max_length=20, blank=True, default="")
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "record_type", "vcita_uid"],
                name="unique_vcita_financial_record_uid",
            )
        ]
        indexes = [
            models.Index(fields=["record_type", "vcita_uid"]),
            models.Index(fields=["matter_uid"]),
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["intake", "record_type"]),
        ]

    def __str__(self):
        return f"{self.record_type} {self.vcita_uid}"
