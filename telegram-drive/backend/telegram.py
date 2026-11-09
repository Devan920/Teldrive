import httpx
import os
from typing import AsyncGenerator
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

BASE_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
FILE_DOWNLOAD_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MiB

async def send_document(file_bytes: bytes, filename: str, mime_type: str) -> dict:
    """Upload a file to the configured Telegram channel.
    Returns the Telegram "document" object on success.
    """
    async with httpx.AsyncClient() as client:
        files = {"document": (filename, file_bytes, mime_type)}
        data = {"chat_id": TELEGRAM_CHAT_ID}
        resp = await client.post(
            f"{BASE_API_URL}/sendDocument",
            data=data,
            files=files,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error: {payload.get('description')}")
        return payload["result"]["document"]

async def get_file_path(file_id: str) -> str:
    """Retrieve the Telegram file_path for a given file_id."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_API_URL}/getFile",
            params={"file_id": file_id},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram getFile error: {payload.get('description')}")
        return payload["result"]["file_path"]

async def stream_telegram_file(file_path: str) -> AsyncGenerator[bytes, None]:
    """Yield file chunks directly from Telegram without storing locally.
    ``file_path`` is the value returned by :func:`get_file_path`.
    """
    download_url = f"{FILE_DOWNLOAD_BASE}/{file_path}"
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", download_url, timeout=None) as response:
            async for chunk in response.aiter_bytes(chunk_size=8192):
                yield chunk
