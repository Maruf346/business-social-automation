import os
import uuid

import requests
from django.core.exceptions import ImproperlyConfigured
from site_config import settings

class TelegramBotService:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.review_chat_id = settings.TELEGRAM_REVIEW_CHAT_ID

    def send_message(self, text, chat_id=None, reply_markup=None):
        resolved_chat_id = chat_id or self.review_chat_id
        if not self.bot_token:
            raise ImproperlyConfigured("TELEGRAM_BOT_TOKEN is not configured.")
        if not resolved_chat_id:
            raise ImproperlyConfigured("TELEGRAM_REVIEW_CHAT_ID is not configured.")

        url = (
            f"https://api.telegram.org/bot"
            f"{self.bot_token}/sendMessage"
        )

        payload = {
            "chat_id": resolved_chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def answer_callback_query(self, callback_query_id, text="", show_alert=False):
        url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
        response = requests.post(
            url,
            json={
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_file(self, file_id):
        url = f"https://api.telegram.org/bot{self.bot_token}/getFile"
        response = requests.get(url, params={"file_id": file_id}, timeout=30)
        response.raise_for_status()
        return response.json()

    def download_file(self, file_id, original_name="telegram-file"):
        file_info = self.get_file(file_id)
        file_path = file_info.get("result", {}).get("file_path", "")
        if not file_path:
            raise ValueError("Telegram file response did not include file_path.")

        download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
        response = requests.get(download_url, timeout=60)
        response.raise_for_status()

        _, ext = os.path.splitext(file_path)
        filename = f"{uuid.uuid4().hex}{ext or ''}"
        relative_dir = os.path.join("telegram")
        abs_dir = os.path.join(settings.MEDIA_ROOT, relative_dir)
        os.makedirs(abs_dir, exist_ok=True)
        abs_path = os.path.join(abs_dir, filename)

        with open(abs_path, "wb") as file_obj:
            file_obj.write(response.content)

        relative_path = os.path.join(relative_dir, filename).replace("\\", "/")
        public_url = f"{settings.MEDIA_BASE_URL.rstrip('/')}/{relative_path}"
        return {
            "url": public_url,
            "file_name": original_name,
            "path": abs_path,
        }


