from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

from core.exceptions import MediaDownloadError
from lead.models import MediaFile, Message

logger = logging.getLogger(__name__)


@dataclass
class MediaDownloadResult:
    media_file: MediaFile
    public_url: str
    file_path: str


class MediaService:
    # WhatsApp media download
    @staticmethod
    def download_whatsapp_media(media_id: str, mime_type: str, access_token: str, message: Message,) -> MediaDownloadResult:
        api_version = settings.WHATSAPP.get("API_VERSION", "v22.0")
        headers = {"Authorization": f"Bearer {access_token}"}

        # Get the download URL ───────────
        try:
            meta_url = f"https://graph.facebook.com/{api_version}/{media_id}"
            resp = requests.get(meta_url, headers=headers, timeout=15)
            resp.raise_for_status()
            download_url = resp.json().get("url")
            if not download_url:
                raise MediaDownloadError(
                    f"Meta media API returned no 'url' for media_id={media_id}"
                )
        except requests.RequestException as exc:
            logger.error("Failed to get media URL for media_id=%s: %s", media_id, exc)
            raise MediaDownloadError(
                f"Failed to retrieve media URL: {exc}"
            ) from exc

        # Download the binary ────────────
        try:
            media_resp = requests.get(download_url, headers=headers, timeout=30)
            media_resp.raise_for_status()
            content_bytes = media_resp.content
        except requests.RequestException as exc:
            logger.error("Failed to download media from %s: %s", download_url, exc)
            raise MediaDownloadError(
                f"Failed to download media binary: {exc}"
            ) from exc

        # Save to disk ────────────────────
        extension = mimetypes.guess_extension(mime_type) or ".bin"
        filename = f"{uuid.uuid4().hex}{extension}"
        relative_dir = os.path.join("whatsapp", str(message.lead_id))

        return MediaService._save_to_disk(
            content_bytes=content_bytes, filename=filename, relative_dir=relative_dir, message=message,
            media_type=mime_type.split("/")[0], mime_type=mime_type,
            provider_media_id=media_id,
        )

    # Outlook attachment save
    @staticmethod
    def save_outlook_attachment(attachment: dict, message: Message,) -> Optional[MediaDownloadResult]:
        import base64

        odata_type = attachment.get("@odata.type", "")
        if odata_type != "#microsoft.graph.fileAttachment":
            logger.info("Skipping non-file attachment type=%s", odata_type)
            return None

        content_b64 = attachment.get("contentBytes", "")
        if not content_b64:
            logger.warning("Attachment '%s' has no contentBytes", attachment.get("name"))
            return None

        try:
            content_bytes = base64.b64decode(content_b64)
        except Exception as exc:
            logger.error("Failed to decode attachment base64: %s", exc)
            raise MediaDownloadError(f"Base64 decode failed: {exc}") from exc

        original_name = attachment.get("name", "attachment")
        mime_type = attachment.get("contentType", "application/octet-stream")
        file_size = attachment.get("size", len(content_bytes))

        # Generate safe filename
        _, ext = os.path.splitext(original_name)
        if not ext:
            ext = mimetypes.guess_extension(mime_type) or ".bin"
        filename = f"{uuid.uuid4().hex}{ext}"

        relative_dir = os.path.join("outlook", str(message.lead_id))

        return MediaService._save_to_disk(
            content_bytes=content_bytes, filename=filename, relative_dir=relative_dir, message=message,
            media_type=mime_type.split("/")[0], mime_type=mime_type, file_name=original_name, file_size=file_size,
        )

    # save binary to disk + create MediaFile record
    @staticmethod
    def _save_to_disk( content_bytes: bytes, filename: str, relative_dir: str, message: Message, media_type: str, mime_type: str, file_name: str = "", file_size: int = 0, provider_media_id: str = "",) -> MediaDownloadResult:
        media_root = settings.MEDIA_ROOT
        abs_dir = os.path.join(media_root, relative_dir)
        os.makedirs(abs_dir, exist_ok=True)

        abs_path = os.path.join(abs_dir, filename)
        try:
            with open(abs_path, "wb") as f:
                f.write(content_bytes)
        except OSError as exc:
            logger.error("Failed to write media file to %s: %s", abs_path, exc)
            raise MediaDownloadError(f"File write failed: {exc}") from exc

        # Build public URL
        relative_path = os.path.join(relative_dir, filename).replace("\\", "/")
        base_url = getattr(settings, "MEDIA_BASE_URL", "")
        public_url = f"{base_url.rstrip('/')}/{relative_path}"

        # Create DB record
        media_file = MediaFile.objects.create(
            message=message,
            media_type=media_type,
            mime_type=mime_type,
            file=os.path.join(relative_dir, filename),
            file_name=file_name or filename,
            file_size=file_size or len(content_bytes),
            download_url=public_url,
            provider_media_id=provider_media_id,
        )

        logger.info(
            "Saved media file id=%s type=%s path=%s for message=%s",
            media_file.pk, media_type, abs_path, message.pk,
        )
        return MediaDownloadResult(
            media_file=media_file,
            public_url=public_url,
            file_path=abs_path,
        )

    # check if MIME type is an image
    @staticmethod
    def is_image_mime(mime_type: str) -> bool:
        return mime_type.lower().startswith("image/")
