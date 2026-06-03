"""Шукає фото для товарів з турецькою назвою але без фото.
Стратегія: пошук по ключових словах тайтлу → беремо лише якщо morhipo_kategori або
filterable_category відповідає очікуваній категорії.
Результат позначається match_type='approx'.
"""
import asyncio, sqlite3, json, sys
from pathlib import Path

sys.path.insert(0, ".")
from app.services.koton_scraper import (
    fetch_and_download_all_photos, photos_from_product_json,
    translate_tr_to_uk, _product_from_json, _best_image, download_image
)
import httpx

MEDIA_DIR = Path("media")
ORIGINALS_DIR = MEDIA_DIR / "koton_originals"
ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

# Категорія → турецькі ключові слова в morhipo_kategori / filterable_category
CATEGORY_MAP = {
    "Футболка": ["Tişört", "T-shirt"],
    "Сорочка":  ["Gömlek"],
    "Штани":    ["Pantolon"],
    "Джинси":   ["Jean", "Kot Pantolon"],
    "Шорти":    ["Şort"],
    "Светр/Кардиган": ["Kazak", "Hırka", "Triko"],
    "Світшот":  ["Sweatshirt"],
    "Куртка":   ["Ceket", "Mont", "Bomber"],
}

def category_ok(p: dict, category: str) -> bool:
    """Перевіряє що знайдений товар відповідає очікуваній категорії."""
    if not category:
        return True
    attrs = p.get("attributes", {})
    kw_fields = [
        attrs.get("morhipo_kategori", ""),
        attrs.get("filterable_category", ""),
        attrs.get("filterable_kategori", ""),
        p.get("name", ""),
    ]
    expected_kws = CATEGORY_MAP.get(category, [])
    if not expected_kws:
        return True
    text = " ".join(kw_fields).lower()
    return any(kw.lower() in text for kw in expected_kws)

def title_keywords(title: str) -> str:
    """Бере перші 3 значущих слова тайтлу для пошуку."""
    words = [w for w in title.split() if len(w) > 3][:3]
    return " ".join(words)

async def search_by_keywords(keywords: str, client) -> list[dict]:
    url = f"https://www.koton.com/list/?search_text={keywords}&format=json"
    try:
        r = await client.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        return r.json().get("products", [])
    except Exception:
        return []

async def main():
    conn = sqlite3.connect("data/sahara.db")
    cur = conn.cursor()

    # Тільки товари з нормальним тайтлом (не garbled) і без фото
    cur.execute("""
        SELECT id, article_1c, title, category FROM products
        WHERE (original_photo IS NULL OR original_photo = '')
          AND stock > 0
          AND title IS NOT NULL
          AND title NOT LIKE '%Koton%'
          AND title NOT LIKE '%?%'
          AND status != 'rejected'
        ORDER BY article_1c
    """)
    rows = cur.fetchall()
    print(f"Товарів з тайтлом для пошуку: {len(rows)}")
    for _, art, title, cat in rows:
        print(f"  {art} [{cat or '?'}] {title[:60]}")
    print()

    enriched = failed = 0

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, (pid, article, title, category) in enumerate(rows):
            print(f"[{i+1}/{len(rows)}] {article} [{category or '?'}]")
            if i > 0:
                await asyncio.sleep(1.5)

            # Пошук по ключових словах тайтлу
            keywords = title_keywords(title)
            print(f"  пошук: '{keywords}'")
            products = await search_by_keywords(keywords, client)

            # Фільтруємо: тільки чоловічий одяг + відповідна категорія
            candidates = []
            for p in products:
                attrs = p.get("attributes", {})
                gender = attrs.get("filterable_gender", attrs.get("morhipo_cinsiyet", "")).lower()
                is_men = "erkek" in gender or "men" in gender
                if is_men and category_ok(p, category):
                    candidates.append(p)

            if not candidates:
                # Спробуємо без gender фільтру
                candidates = [p for p in products if category_ok(p, category)]

            if not candidates:
                print(f"  → не знайдено відповідного товару")
                failed += 1
                continue

            best = candidates[0]
            bc = best.get("base_code", "")
            name = best.get("name", "")[:50]
            print(f"  → знайдено: {bc} | {name}")

            # Завантажуємо фото
            product_url = best.get("absolute_url", "")
            if product_url and not product_url.startswith("http"):
                product_url = "https://www.koton.com" + product_url

            from app.services.koton_scraper import KotonProduct, IMAGE_SIZE
            import re
            koton = KotonProduct(
                article=article,
                name=best.get("name", ""),
                price_try=float(best.get("retail_price") or best.get("price") or 0),
                color=best.get("attributes", {}).get("integration_color_desc", ""),
                image_url="",
                product_url=product_url,
                ean=best.get("sku", ""),
                stock=1 if best.get("in_stock") else 0,
            )

            photos = await fetch_and_download_all_photos(koton, article, client, ORIGINALS_DIR, best)
            if not photos:
                print(f"  → фото не завантажились")
                failed += 1
                continue

            title_ua = await translate_tr_to_uk(best.get("name", ""), client)
            extra = json.dumps(photos[1:], ensure_ascii=False) if len(photos) > 1 else None

            cur.execute("""
                UPDATE products SET
                    original_photo=?, extra_photos=?, title=?, title_ua=?,
                    match_type='approx', updated_at=datetime('now')
                WHERE id=?
            """, (photos[0], extra, best.get("name", ""), title_ua, pid))
            conn.commit()

            print(f"  ✓ {title_ua or name} | {len(photos)} фото")
            enriched += 1

    conn.close()
    print(f"\nГотово: знайдено={enriched}, не знайдено={failed}")

asyncio.run(main())
