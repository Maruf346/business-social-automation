from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from .models import WebhookSubscription
from .outlook.subscription_sync import SubscriptionSyncService


@receiver(post_save, sender=WebhookSubscription)
def webhook_subscription_saved(sender, instance, created, **kwargs):
    SubscriptionSyncService.handle_save(
        subscription=instance,
        created=created,
    )

@receiver(pre_delete, sender=WebhookSubscription)
def webhook_subscription_deleted(sender, instance, **kwargs):
    SubscriptionSyncService.handle_delete(
        subscription=instance,
    )

