from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
import requests

from core.models import WebhookSubscription
from core.outlook.graph_subscription import GraphSubscriptionService


class SubscriptionSyncService:
    @classmethod
    def handle_save(cls, subscription, created, previous_state=None):
        if created:
            cls.create(subscription)
            return
        cls.update(subscription, previous_state=previous_state)

    @classmethod
    def handle_delete(cls, subscription):
        if not subscription.subscription_id:
            return
        try:
            GraphSubscriptionService.delete_subscription(subscription)
        except Exception as exc:
            if not cls._is_graph_not_found(exc):
                raise

    @classmethod
    def renew_due(cls, lookahead_hours=24, extension_hours=48, limit=100):
        now = timezone.now()
        renew_before = now + timedelta(hours=lookahead_hours)
        candidates = WebhookSubscription.objects.select_related("outlook").filter(
            outlook__is_active=True,
        ).filter(
            Q(subscription_id__isnull=True)
            | Q(subscription_id="")
            | Q(expiration_date__lte=renew_before)
            | Q(status__iexact="failed")
            | Q(status__iexact="pending")
        ).order_by("expiration_date")[:limit]

        result = {"checked": 0, "renewed": 0, "failed": 0}
        for subscription in candidates:
            result["checked"] += 1
            ok = cls.renew_one(subscription, extension_hours=extension_hours, now=now)
            if ok:
                result["renewed"] += 1
            else:
                result["failed"] += 1
        return result

    @classmethod
    def renew_one(cls, subscription, extension_hours=48, now=None):
        now = now or timezone.now()
        current_expiration = subscription.expiration_date
        subscription.expiration_date = now + timedelta(hours=extension_hours)

        if not subscription.subscription_id or not current_expiration or current_expiration <= now:
            cls.create(subscription)
        else:
            try:
                response = GraphSubscriptionService.renew_subscription(subscription)
            except Exception as exc:
                if cls._is_graph_not_found(exc):
                    cls.create(subscription)
                else:
                    cls._mark_failed(subscription, exc)
                    return False
            else:
                WebhookSubscription.objects.filter(pk=subscription.pk).update(
                    expiration_date=response["expirationDateTime"],
                    status="ACTIVE",
                    last_synced_at=timezone.now(),
                    sync_error="",
                )
        refreshed = WebhookSubscription.objects.filter(pk=subscription.pk).values("status", "sync_error").first()
        return bool(refreshed and refreshed["status"] == "ACTIVE" and not refreshed["sync_error"])

    @classmethod
    def create(cls, subscription):
        try:
            response = GraphSubscriptionService.create_subscription(subscription)
        except Exception as exc:
            cls._mark_failed(subscription, exc)
            return
        WebhookSubscription.objects.filter(pk=subscription.pk).update(
            subscription_id=response["id"],
            expiration_date=response["expirationDateTime"],
            status="ACTIVE",
            last_synced_at=timezone.now(),
            sync_error="",
        )

    @classmethod
    def update(cls, subscription, previous_state=None):
        if not subscription.subscription_id:
            cls.create(subscription)
            return

        old = previous_state
        if old is None:
            old = WebhookSubscription.objects.filter(pk=subscription.pk).first()
        if old is None:
            cls.create(subscription)
            return

        recreate = any([
            old.notification_url != subscription.notification_url,
            old.resource != subscription.resource,
            old.client_state != subscription.client_state,
            old.change_type != subscription.change_type,
        ])
        if recreate:
            if old.subscription_id:
                try:
                    GraphSubscriptionService.delete_subscription(old)
                except Exception as exc:
                    if not cls._is_graph_not_found(exc):
                        cls._mark_failed(subscription, exc)
                        return
            cls.create(subscription)
            return

        if old.expiration_date and old.expiration_date <= timezone.now():
            cls.create(subscription)
            return

        if old.expiration_date != subscription.expiration_date:
            try:
                response = GraphSubscriptionService.renew_subscription(subscription)
            except Exception as exc:
                if cls._is_graph_not_found(exc):
                    cls.create(subscription)
                    return
                cls._mark_failed(subscription, exc)
                return
            WebhookSubscription.objects.filter(pk=subscription.pk).update(
                expiration_date=response["expirationDateTime"],
                status="ACTIVE",
                last_synced_at=timezone.now(),
                sync_error="",
            )

    @classmethod
    def _mark_failed(cls, subscription, exc):
        WebhookSubscription.objects.filter(pk=subscription.pk).update(
            status="FAILED",
            last_synced_at=timezone.now(),
            sync_error=cls._format_error(exc),
        )

    @staticmethod
    def _is_graph_not_found(exc):
        return isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 404

    @staticmethod
    def _format_error(exc):
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            try:
                body = exc.response.json()
            except ValueError:
                body = exc.response.text
            return f"Microsoft Graph error {exc.response.status_code}: {body}"
        return str(exc)