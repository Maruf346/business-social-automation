from django.db import transaction
from django.utils import timezone
import requests

from core.models import WebhookSubscription
from core.outlook.graph_subscription import GraphSubscriptionService


class SubscriptionSyncService:
    @classmethod
    def handle_save(cls, subscription, created):
        if created:
            cls.create(subscription)
            return
        cls.update(subscription)

    @classmethod
    def handle_delete(cls, subscription):
        if subscription.subscription_id:
            GraphSubscriptionService.delete_subscription(
                subscription
            )

    @classmethod
    def create(cls, subscription):
        try:
            response = GraphSubscriptionService.create_subscription(
                subscription
            )
        except Exception as exc:
            cls._mark_failed(subscription, exc)
            return
        WebhookSubscription.objects.filter(
            pk=subscription.pk
        ).update(
            subscription_id=response["id"],
            expiration_date=response["expirationDateTime"],
            status="ACTIVE",
            last_synced_at=timezone.now(),
            sync_error="",
        )

    @classmethod
    def update(cls, subscription):
        old = WebhookSubscription.objects.get(pk=subscription.pk)
        recreate = any([
            old.notification_url != subscription.notification_url,
            old.resource != subscription.resource,
            old.client_state != subscription.client_state,
            old.change_type != subscription.change_type,
        ])
        if recreate:
            try:
                GraphSubscriptionService.delete_subscription(old)
                response = GraphSubscriptionService.create_subscription(
                    subscription
                )
            except Exception as exc:
                cls._mark_failed(subscription, exc)
                return
            WebhookSubscription.objects.filter(
                pk=subscription.pk
            ).update(
                subscription_id=response["id"],
                expiration_date=response["expirationDateTime"],
                last_synced_at=timezone.now(),
                sync_error="",
            )
            return

        if old.expiration_date != subscription.expiration_date:
            try:
                response = GraphSubscriptionService.renew_subscription(
                    subscription
                )
            except Exception as exc:
                cls._mark_failed(subscription, exc)
                return
            WebhookSubscription.objects.filter(
                pk=subscription.pk
            ).update(
                expiration_date=response["expirationDateTime"],
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
    def _format_error(exc):
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            try:
                body = exc.response.json()
            except ValueError:
                body = exc.response.text
            return f"Microsoft Graph error {exc.response.status_code}: {body}"
        return str(exc)



