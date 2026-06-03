#!/usr/bin/env python3
"""
Кронджоб: читає найновіший JSON/CSV з ./sync/ і оновлює сайт.

Запуск вручну:
    cd /home/minus/Desktop/sahara/sahara
    source venv/bin/activate
    python sync_1c_runner.py

Cron (кожні 30 хв):
    */30 * * * * /home/minus/Desktop/sahara/sahara/venv/bin/python \
        /home/minus/Desktop/sahara/sahara/sync_1c_runner.py \
        >> /home/minus/Desktop/sahara/sahara/sync_1c.log 2>&1
"""
import asyncio
import sys
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.services.sync_1c import (
    load_newest_export, save_state,
)

from sqlalchemy import select
from app.db import async_session, init_db
from app.models import Product

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_1c")


async def run():
    await init_db()
    products, file_path = load_newest_export()

    if not products:
        msg = "sync/: файл не знайдено або порожній"
        log.warning(msg)
        save_state(None, 0, 0, 0, error=msg)
        return

    log.info("Файл: %s  |  Рядків: %d", file_path.name, len(products))

    updated = created = skipped = 0

    async with async_session() as session:
        for item in products:
            article = item["article"]
            stock = item["stock"]
            price = item["price"]

            result = await session.execute(
                select(Product).where(Product.article_1c == article)
            )
            product = result.scalar_one_or_none()

            if product:
                product.stock = stock
                if price is not None:
                    product.price_uah = price
                updated += 1
            else:
                log.debug("Артикул %s не знайдено в БД — пропускаємо", article)
                skipped += 1

        await session.commit()

    state = save_state(file_path, len(products), updated, created)
    log.info(
        "Готово: оновлено=%d  не знайдено=%d  файл=%s",
        updated, skipped, file_path.name,
    )
    return state


if __name__ == "__main__":
    asyncio.run(run())
