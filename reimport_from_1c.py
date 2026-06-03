"""
Чистий імпорт 6SAM+6WAM з 1С JSON → koton.com scraper.
Для кожного артикула:
  1. Шукає точний збіг на koton.com (base_code)
  2. Завантажує фото через HTML-сторінку товару
  3. Перекладає назву TR→UA
  4. Зберігає в БД як PENDING
"""
import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, ".")
from app.db import async_session, init_db
from app.models import Product, ProductStatus
from app.services.koton_scraper import (
    fetch_product, fetch_all_photos, download_image,
    translate_tr_to_uk, _search_json,
)
from sqlalchemy import select
import httpx

SYNC_FILE = Path("sync/upload_20260516_211651.json")
ORIGINALS_DIR = Path("media/koton_originals")
ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/html",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

CATEGORY_MAP = {
    "Tişört": "Футболка", "T-shirt": "Футболка",
    "Polo": "Поло",
    "Gömlek": "Сорочка",
    "Pantolon": "Штани",
    "Jean": "Джинси", "Kot": "Джинси",
    "Şort": "Шорти",
    "Kazak": "Светр/Кардиган", "Hırka": "Светр/Кардиган", "Triko": "Светр/Кардиган",
    "Sweatshirt": "Світшот",
    "Ceket": "Куртка", "Mont": "Куртка", "Bomber": "Куртка",
    "Atlet": "Майка",
    "Eşofman": "Спортивні штани",
}

def get_category(json_product: dict) -> str:
    attrs = json_product.get("attributes", {})
    text = " ".join([
        attrs.get("filterable_category", ""),
        attrs.get("morhipo_kategori", ""),
        json_product.get("name", ""),
    ])
    for kw, ua in CATEGORY_MAP.items():
        if kw.lower() in text.lower():
            return ua
    return ""


def load_articles() -> list[dict]:
    with open(SYNC_FILE) as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("products", data.get("items", []))
    return [
        i for i in items
        if str(i.get("article", "")).startswith("6SAM")
        or str(i.get("article", "")).startswith("6WAM")
    ]


async def main():
    await init_db()
    articles = load_articles()
    print(f"Артикулів з 1С: {len(articles)}\n")

    found = skipped = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=HEADERS) as client:
        for i, item in enumerate(articles):
            article = item["article"]
            stock = item["stock"]
            print(f"[{i+1}/{len(articles)}] {article} (stock={stock})", end=" ", flush=True)

            if i > 0:
                await asyncio.sleep(1.5)

            # Шукаємо точний збіг на koton.com
            json_product = None
            for term in [article, article[1:] if article[0].isdigit() else None]:
                if not term:
                    continue
                prods = await _search_json(term, client)
                for p in prods:
                    if p.get("base_code") == article:
                        json_product = p
                        break
                if json_product:
                    break

            if not json_product:
                print("→ не знайдено")
                skipped += 1
                continue

            koton = fetch_product.__wrapped__ if hasattr(fetch_product, '__wrapped__') else None
            name = json_product.get("name", article)
            product_url = json_product.get("absolute_url", "")
            if product_url and not product_url.startswith("http"):
                product_url = "https://www.koton.com" + product_url

            price_try = float(json_product.get("retail_price") or json_product.get("price") or 0)
            print(f"→ {name[:45]}")

            # Фото через HTML сторінку товару
            photo_urls = await fetch_all_photos(product_url, client)
            await asyncio.sleep(0.5)

            photos = []
            for j, url in enumerate(photo_urls[:5]):
                suffix = "" if j == 0 else f"_{j}"
                path = ORIGINALS_DIR / f"{article}{suffix}.jpg"
                ok = await download_image(url, path, client)
                if ok:
                    photos.append(f"koton_originals/{article}{suffix}.jpg")
                await asyncio.sleep(0.2)

            if not photos:
                print(f"  фото не завантажились")
                skipped += 1
                continue

            title_ua = await translate_tr_to_uk(name, client)
            category = get_category(json_product)
            extra = json.dumps(photos[1:], ensure_ascii=False) if len(photos) > 1 else None

            async with async_session() as session:
                existing = await session.execute(
                    select(Product).where(Product.article_1c == article)
                )
                if existing.scalar_one_or_none():
                    print(f"  вже є, пропускаємо")
                    skipped += 1
                    continue

                p = Product(
                    article_1c=article,
                    title=name,
                    title_ua=title_ua or name,
                    description="",
                    price_uah=price_try,
                    original_photo=photos[0],
                    extra_photos=extra,
                    stock=stock,
                    category=category,
                    match_type="exact",
                    gender="men",
                    status=ProductStatus.PENDING,
                )
                session.add(p)
                await session.commit()

            print(f"  ✓ {title_ua or name[:40]} | {len(photos)} фото | {category or '?'}")
            found += 1

    print(f"\n=== Готово ===")
    print(f"Додано: {found} | Пропущено/не знайдено: {skipped}")


asyncio.run(main())
