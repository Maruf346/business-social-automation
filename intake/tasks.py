from __future__ import annotations

from celery import shared_task
from django.core.management import call_command


@shared_task(name="intake.notify_pending_holds")
def notify_pending_holds_task(limit: int = 20) -> str:
    call_command("notify_pending_holds", limit=limit)
    return "pending hold review scan completed"