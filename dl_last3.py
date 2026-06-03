"""Download last 3 photos from Telegram saved messages (self-chat)."""
import asyncio
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto

import sys
sys.path.insert(0, str(Path(__file__).parent))
from app.config import settings

SESSION = str(Path(__file__).parent / "sahara_session")


async def main():
    async with TelegramClient(SESSION, settings.tg_api_id, settings.tg_api_hash) as client:
        saved = await client.get_entity("me")
        photos = []
        async for msg in client.iter_messages(saved, limit=50):
            if msg.media and isinstance(msg.media, MessageMediaPhoto):
                photos.append(msg)
                if len(photos) >= 3:
                    break

        if not photos:
            print("Фото не знайдено")
            return

        for i, msg in enumerate(photos):
            out = f"/tmp/banner_last_{i+1}.jpg"
            await client.download_media(msg, out)
            print(f"  #{i+1} msg_id={msg.id} → {out}")


asyncio.run(main())
