import requests
from site_config import settings

class TelegramBotService:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN

    def send_message(self, text, chat_id="8145617629"):
        url = (
            f"https://api.telegram.org/bot"
            f"{self.bot_token}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


