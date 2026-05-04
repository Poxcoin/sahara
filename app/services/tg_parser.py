"""
Telegram parser на Telethon (User API).

Може читати БУДЬ-ЯКИЙ канал де ти підписник — без потреби бути адміном.

Запуск:
    python -m app.services.tg_parser

Перший запуск: запитає номер телефону і код з Telegram.
Після цього сесія зберігається у sahara_session.session і наступні
запуски проходять автоматично.

Формат поста:
    [фото]
    Назва товару
    Ціна: 4890
    Опис...
"""
import asyncio
import re
from pathlib import Path
from io import BytesIO

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto

from app.config import settings
from app.db import async_session, init_db
from app.models import Product, ProductStatus
from sqlalchemy import select


SESSION_FILE = "sahara_session"


def extract_price(text: str) -> float | None:
    """Витягує ціну з будь-якого рядка."""
    # "ціна зі знижкою 2430 грн", "ціна 825 грн", "2430₴", "2430 грн"
    m = re.search(r"(?:ціна[^0-9]*|price[^0-9]*)(\d[\d\s]{1,6})\s*(?:грн|₴|uah)?", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(" ", ""))
    m = re.search(r"(\d[\d\s]{1,6})\s*(?:грн|₴)", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(" ", ""))
    return None


def parse_caption(text: str) -> tuple[str, float | None, str]:
    if not text:
        return "Без назви", None, ""

    # Нормалізуємо — розбиваємо по переносу або комі
    raw_lines = text.strip().split("\n")
    if len(raw_lines) == 1:
        # Весь текст в одному рядку — розбиваємо по комі
        parts = [p.strip() for p in raw_lines[0].split(",") if p.strip()]
    else:
        parts = [l.strip() for l in raw_lines if l.strip()]

    if not parts:
        return "Без назви", None, ""

    # Перший елемент — назва (без "розмір...", "ціна...")
    title_raw = parts[0]
    # Очищаємо emoji з назви для заголовку
    title = re.sub(r'[^\w\s\-\/]', '', title_raw).strip() or title_raw.strip()

    # Шукаємо ціну по всьому тексту
    price = extract_price(text)

    # Опис — частини без ціни і без назви
    desc_parts = []
    for p in parts[1:]:
        if re.search(r"ціна|price|грн|₴|\d{3,}", p, re.IGNORECASE):
            continue
        if re.search(r"розмір|размер|size", p, re.IGNORECASE):
            desc_parts.append(p.strip())

    return title, price, ", ".join(desc_parts)


async def save_product(client: TelegramClient, message):
    """Зберігає пост з каналу в БД."""
    if not message.media or not isinstance(message.media, MessageMediaPhoto):
        return

    title, price, description = parse_caption(message.message or "")

    Path(settings.media_dir, "originals").mkdir(parents=True, exist_ok=True)
    photo_path = f"{settings.media_dir}/originals/{message.id}.jpg"

    async with async_session() as session:
        # Дедуплікація
        existing = await session.execute(
            select(Product).where(Product.tg_message_id == message.id)
        )
        if existing.scalar_one_or_none():
            print(f"[skip] message {message.id} already in DB")
            return

        # Завантажуємо фото
        try:
            buf = BytesIO()
            await client.download_media(message.media, file=buf)
            buf.seek(0)
            with open(photo_path, "wb") as f:
                f.write(buf.read())
        except Exception as e:
            print(f"[err] download failed: {e}")
            return

        product = Product(
            tg_message_id=message.id,
            title=title,
            description=description,
            price_uah=price,
            original_photo=f"originals/{message.id}.jpg",
            status=ProductStatus.PENDING,
        )
        session.add(product)
        await session.commit()
        print(f"[+] {title} | {price} ₴ | originals/{message.id}.jpg")


async def resync_metadata(client: TelegramClient):
    """Оновлює назви і ціни вже імпортованих товарів."""
    print(f"[resync] оновлюю метадані з {settings.tg_source}...")
    updated = 0
    async for message in client.iter_messages(settings.tg_source, limit=None):
        if not message.media or not isinstance(message.media, MessageMediaPhoto):
            continue
        async with async_session() as session:
            result = await session.execute(
                select(Product).where(Product.tg_message_id == message.id)
            )
            product = result.scalar_one_or_none()
            if not product:
                continue
            title, price, description = parse_caption(message.message or "")
            product.title = title
            product.price_uah = price
            product.description = description
            await session.commit()
            updated += 1
            print(f"[~] {title} | {price} ₴")
    print(f"[resync] оновлено {updated} товарів")


async def sync_history(client: TelegramClient, limit: int = 0):
    """Завантажує всі старі пости з каналу."""
    print(f"[sync] завантажую історію з {settings.tg_source}...")
    count = 0
    skipped = 0
    async for message in client.iter_messages(settings.tg_source, limit=limit or None):
        if not message.media or not isinstance(message.media, MessageMediaPhoto):
            continue
        try:
            existed_before = await _already_exists(message.id)
            if existed_before:
                skipped += 1
                continue
            await save_product(client, message)
            count += 1
        except Exception as e:
            print(f"[err] msg {message.id}: {e}")
    print(f"[sync] готово: додано {count}, пропущено {skipped} дублів")


async def _already_exists(message_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Product).where(Product.tg_message_id == message_id)
        )
        return result.scalar_one_or_none() is not None


async def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "listen"

    if not settings.tg_api_id or not settings.tg_api_hash:
        print("[err] TG_API_ID або TG_API_HASH не налаштовані у .env")
        print("      Отримай на: https://my.telegram.org/apps")
        return
    if not settings.tg_source:
        print("[err] TG_SOURCE не налаштований у .env")
        return

    await init_db()

    client = TelegramClient(SESSION_FILE, settings.tg_api_id, settings.tg_api_hash)
    await client.start()

    me = await client.get_me()
    print(f"[ok] підключено як {me.first_name} (@{me.username})")

    if mode == "sync":
        await sync_history(client)
        await client.disconnect()
    elif mode == "resync":
        await resync_metadata(client)
        await client.disconnect()
    else:
        # Слухати нові пости в реальному часі
        print(f"[*]  слухаємо канал: {settings.tg_source}")
        print("[*]  очікуємо нові пости... (Ctrl+C для зупинки)")

        @client.on(events.NewMessage(chats=settings.tg_source))
        async def handler(event):
            try:
                await save_product(client, event.message)
            except Exception as e:
                print(f"[err] {e}")

        await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
