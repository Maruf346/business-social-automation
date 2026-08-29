from datetime import timedelta, timezone as dt_timezone
from django.db import transaction
import requests
from core.models import OutlookAccessToken
from django.utils import timezone


class GraphSubscriptionService:
    GRAPH_SCOPE = "https://graph.microsoft.com/.default"

    @staticmethod
    def _graph_datetime(value):
        if not value:
            return None
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def create_subscription(cls, subscription):
        token = cls.get_access_token(subscription.outlook)
        url = "https://graph.microsoft.com/v1.0/subscriptions"
        payload = {
            "changeType": subscription.change_type,
            "notificationUrl": subscription.notification_url,
            "resource": subscription.resource,
            "expirationDateTime": cls._graph_datetime(subscription.expiration_date),
            "clientState": subscription.client_state,
        }
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}"
            }
        )
        response.raise_for_status()
        return response.json()

    @classmethod
    def renew_subscription(cls, subscription):
        token = cls.get_access_token(subscription.outlook)
        url = (
            f"https://graph.microsoft.com/v1.0/"
            f"subscriptions/{subscription.subscription_id}"
        )
        payload = {
            "expirationDateTime": cls._graph_datetime(subscription.expiration_date)
        }
        response = requests.patch(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}"
            }
        )
        response.raise_for_status()
        return response.json()

    @classmethod
    def delete_subscription(cls, subscription):
        token = cls.get_access_token(subscription.outlook)
        url = (
            f"https://graph.microsoft.com/v1.0/"
            f"subscriptions/{subscription.subscription_id}"
        )
        response = requests.delete(
            url,
            headers={
                "Authorization": f"Bearer {token}"
            }
        )
        response.raise_for_status()

    @classmethod
    def get_access_token(cls, outlook):
        token_obj, _ = OutlookAccessToken.objects.get_or_create(
            outlook=outlook,
            defaults={
                "grant_type": "client_credentials"
            }
        )
        if (
            token_obj.access_token
            and token_obj.expires_at
            and token_obj.expires_at > timezone.now() + timedelta(minutes=5)
        ):
            return token_obj.access_token
        return cls._generate_new_access_token(outlook, token_obj,)

    @classmethod
    @transaction.atomic
    def _generate_new_access_token(cls, outlook, token_obj,):
        token_url = (
            f"https://login.microsoftonline.com/"
            f"{outlook.tenant_id}/oauth2/v2.0/token"
        )
        payload = {
            "grant_type": "client_credentials",
            "client_id": outlook.client_id,
            "client_secret": outlook.client_secret,
            "scope": cls.GRAPH_SCOPE,
        }
        response = requests.post(
            token_url,
            data=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        expires_in = int(data["expires_in"])
        token_obj.scope = data.get("scope")
        token_obj.token_type = data.get("token_type")
        token_obj.expires_in = expires_in
        token_obj.ext_expires_in = int(
            data.get("ext_expires_in", expires_in)
        )
        token_obj.access_token = data["access_token"]
        token_obj.expires_at = (
            timezone.now()
            + timedelta(seconds=expires_in)
        )
        token_obj.save()
        return token_obj.access_token


