import requests
from django.core.exceptions import ImproperlyConfigured
from site_config import settings

class TelegramBotService:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.review_chat_id = settings.TELEGRAM_REVIEW_CHAT_ID

    def send_message(self, text, chat_id=None):
        resolved_chat_id = chat_id or self.review_chat_id
        if not self.bot_token:
            raise ImproperlyConfigured("TELEGRAM_BOT_TOKEN is not configured.")
        if not resolved_chat_id:
            raise ImproperlyConfigured("TELEGRAM_REVIEW_CHAT_ID is not configured.")

        url = (
            f"https://api.telegram.org/bot"
            f"{self.bot_token}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": resolved_chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


