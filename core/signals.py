from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from .models import WebhookSubscription
from .outlook.subscription_sync import SubscriptionSyncService


@receiver(pre_save, sender=WebhookSubscription)
def webhook_subscription_capture_previous(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_state = None
        return
    instance._previous_state = WebhookSubscription.objects.filter(pk=instance.pk).first()


@receiver(post_save, sender=WebhookSubscription)
def webhook_subscription_saved(sender, instance, created, **kwargs):
    SubscriptionSyncService.handle_save(
        subscription=instance,
        created=created,
        previous_state=getattr(instance, "_previous_state", None),
    )


@receiver(pre_delete, sender=WebhookSubscription)
def webhook_subscription_deleted(sender, instance, **kwargs):
    SubscriptionSyncService.handle_delete(
        subscription=instance,
    )
