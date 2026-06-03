"""Запуск нового скрапера для товарів без фото.
Якщо точний артикул не знайдено — пробуємо той самий числовий номер в інших сезонах/роках.
"""
import asyncio, sqlite3, json, sys, re
from pathlib import Path

sys.path.insert(0, ".")
from app.services.koton_scraper import (
    fetch_product, fetch_and_download_all_photos, photos_from_product_json,
    translate_tr_to_uk, _search_json, _product_from_json, _best_image
)
import httpx

MEDIA_DIR = Path("media")
ORIGINALS_DIR = MEDIA_DIR / "koton_originals"
ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "tr-TR,tr;q=0.9",
}

async def find_same_number(article: str, client) -> tuple[dict | None, str]:
    """Шукає той самий числовий номер в будь-якому сезоні. Повертає (json_product, match_type)."""
    if len(article) < 9:
        return None, ""
    num_color = article[4:]   # напр "10091MK" з "5SAM10091MK"
    num = article[4:9]        # напр "10091"

    prods = await _search_json(num_color, client)
    for p in prods:
        bc = p.get("base_code", "")
        if num in bc and bc != article:
            return p, "approx"
    return None, ""

async def main():
    conn = sqlite3.connect("data/sahara.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, article_1c FROM products
        WHERE (original_photo IS NULL OR original_photo = '')
          AND stock > 0
        ORDER BY article_1c
    """)
    rows = cur.fetchall()
    print(f"Товарів без фото: {len(rows)}\n")

    enriched = failed = 0

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, (pid, article) in enumerate(rows):
            print(f"[{i+1}/{len(rows)}] {article}", end=" ")
            if i > 0:
                await asyncio.sleep(1.5)

            # Спроба 1: точний збіг
            koton = await fetch_product(article, client)
            json_product = None
            match_type = "exact"

            if koton:
                # знайти json_product для фото
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
            else:
                # Спроба 2: той самий числовий номер, інший сезон
                json_product, match_type = await find_same_number(article, client)
                if json_product:
                    bc = json_product.get("base_code", "")
                    print(f"→ approx ({bc})")
                    koton = _product_from_json(article, json_product)
                    koton = koton.__class__(
                        article=article,
                        name=koton.name,
                        price_try=koton.price_try,
                        color=koton.color,
                        image_url=koton.image_url,
                        product_url=koton.product_url,
                        ean=koton.ean,
                        stock=koton.stock,
                    )

            if not koton:
                print("→ не знайдено")
                failed += 1
                continue

            if match_type == "exact":
                print("→ exact")

            photos = await fetch_and_download_all_photos(
                koton, article, client, ORIGINALS_DIR, json_product
            )
            if not photos:
                print(f"  фото не завантажились")
                failed += 1
                continue

            title_ua = await translate_tr_to_uk(koton.name, client)
            extra = json.dumps(photos[1:], ensure_ascii=False) if len(photos) > 1 else None

            cur.execute("""
                UPDATE products SET
                    original_photo=?, extra_photos=?, title=?, title_ua=?,
                    match_type=?, updated_at=datetime('now')
                WHERE id=?
            """, (photos[0], extra, koton.name, title_ua, match_type, pid))
            conn.commit()

            print(f"  ✓ {title_ua or koton.name[:50]} | {len(photos)} фото")
            enriched += 1

    conn.close()
    print(f"\nГотово: знайдено={enriched}, не знайдено={failed}")

asyncio.run(main())
