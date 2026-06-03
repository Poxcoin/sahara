"""
Імпортує ВСІ артикули чоловічого Koton (2xxx-6xxx) в БД SAHARA як PENDING.
Пропускає якщо article_1c вже є в БД.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db import async_session, init_db
from app.models import Product, ProductStatus
from app.services.koton_scraper import (
    fetch_product, fetch_all_photos, fetch_product_description,
    fetch_size_chart, download_image, translate_tr_to_uk,
)
from app.config import settings
from sqlalchemy import select
import httpx

ARTICLES_FILE = Path(__file__).parent / "koton_erkek_articles.txt"
ORIGINALS_DIR = Path(settings.media_dir) / "koton_originals"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


async def get_existing_articles() -> set:
    async with async_session() as session:
        result = await session.execute(
            select(Product.article_1c).where(Product.article_1c.isnot(None))
        )
        return {row[0] for row in result.fetchall()}


async def main():
    await init_db()

    all_articles = [
        a.strip() for a in ARTICLES_FILE.read_text().splitlines() if a.strip()
    ]

    by_year = {}
    for a in all_articles:
        by_year.setdefault(a[0], 0)
        by_year[a[0]] += 1
    for y, cnt in sorted(by_year.items()):
        print(f"  {y}xxx: {cnt}")
    print(f"Разом: {len(all_articles)}")

    existing = await get_existing_articles()
    to_import = [a for a in all_articles if a not in existing]
    print(f"Вже в БД: {len(all_articles) - len(to_import)}")
    print(f"Для імпорту: {len(to_import)}\n")

    added = skipped = failed = 0

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        for i, article in enumerate(to_import):
            print(f"[{i+1}/{len(to_import)}] {article} ... ", end="", flush=True)

            try:
                product = await fetch_product(article, client)
            except Exception as e:
                print(f"помилка: {e}")
                failed += 1
                await asyncio.sleep(1)
                continue

            if not product:
                print("не знайдено")
                skipped += 1
                await asyncio.sleep(1)
                continue

            all_photos = []
            try:
                photo_urls = await fetch_all_photos(product.product_url, client)
                if not photo_urls and product.image_url:
                    photo_urls = [product.image_url]
                for j, url in enumerate(photo_urls[:5]):
                    suffix = "" if j == 0 else f"_{j}"
                    path = ORIGINALS_DIR / f"{article}{suffix}.jpg"
                    if await download_image(url, path, client):
                        all_photos.append(f"koton_originals/{article}{suffix}.jpg")
                    await asyncio.sleep(0.2)
            except Exception:
                pass

            photo_rel = all_photos[0] if all_photos else ""
            extra = json.dumps(all_photos[1:], ensure_ascii=False) if len(all_photos) > 1 else None

            title_ua = desc = ""
            size_chart_json = None
            try:
                title_ua = await translate_tr_to_uk(product.name, client)
                desc = await fetch_product_description(product.product_url, client)
                size_data = await fetch_size_chart(product.product_url, client)
                if size_data:
                    size_chart_json = json.dumps(size_data, ensure_ascii=False)
            except Exception:
                pass

            async with async_session() as session:
                if (await session.execute(
                    select(Product).where(Product.article_1c == article)
                )).scalar_one_or_none():
                    print("вже є")
                    skipped += 1
                    continue

                session.add(Product(
                    article_1c=article,
                    title=product.name,
                    title_ua=title_ua or product.name,
                    description=desc or f"{product.color} | {product.product_url}",
                    price_uah=product.price_try,
                    original_photo=photo_rel,
                    extra_photos=extra,
                    size_chart=size_chart_json,
                    status=ProductStatus.PENDING,
                    gender="men",
                ))
                await session.commit()

            print(f"✓ {(title_ua or product.name)[:40]} | {product.price_try} TRY | фото:{len(all_photos)}")
            added += 1
            await asyncio.sleep(2.0)

    print(f"\n=== Готово ===")
    print(f"Додано: {added} | Пропущено: {skipped} | Помилки: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
