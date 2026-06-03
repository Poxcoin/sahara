"""
Повний ресет:
1. Видаляє всі продукти
2. Імпортує 6SAM+6WAM з 1С JSON як PENDING
3. Шукає кожен артикул на koton.com (JSON API + base_code match)
4. Завантажує фото + перекладає назву для знайдених
"""
import asyncio, json, sys, sqlite3
from pathlib import Path

sys.path.insert(0, ".")
from app.services.koton_scraper import (
    fetch_and_download_all_photos, translate_tr_to_uk,
    _search_json, _product_from_json,
)
import httpx

SYNC_FILE = Path("sync/upload_20260516_211651.json")
DB_PATH = "data/sahara.db"
MEDIA_DIR = Path("media")
ORIGINALS_DIR = MEDIA_DIR / "koton_originals"
ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def load_1c_articles() -> list[dict]:
    with open(SYNC_FILE) as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("products", data.get("items", []))
    return [
        i for i in items
        if str(i.get("article", "")).startswith("6SAM")
        or str(i.get("article", "")).startswith("6WAM")
    ]


async def find_on_koton(article: str, client) -> tuple[dict | None, str]:
    """Шукає артикул через JSON API. Повертає (json_product, match_type)."""
    # Спроба 1: точний артикул
    prods = await _search_json(article, client)
    for p in prods:
        if p.get("base_code") == article:
            return p, "exact"

    # Спроба 2: без першої цифри (якщо 6SAM → SAM)
    if article[0].isdigit():
        prods2 = await _search_json(article[1:], client)
        for p in prods2:
            if p.get("base_code") == article:
                return p, "exact"

    return None, ""


async def main():
    articles_1c = load_1c_articles()
    print(f"Артикулів з 1С (6SAM+6WAM): {len(articles_1c)}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Очищаємо всі продукти
    cur.execute("DELETE FROM products")
    conn.commit()
    print("БД очищено\n")

    # Вставляємо всі артикули як PENDING без фото
    for item in articles_1c:
        cur.execute("""
            INSERT INTO products (article_1c, stock, status, title, description, original_photo, created_at, updated_at)
            VALUES (?, ?, 'PENDING', ?, '', '', datetime('now'), datetime('now'))
        """, (item["article"], item["stock"], item["article"]))
    conn.commit()
    print(f"Вставлено {len(articles_1c)} записів як PENDING\n")

    found = not_found = 0

    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS) as client:
        for i, item in enumerate(articles_1c):
            article = item["article"]
            stock = item["stock"]
            print(f"[{i+1}/{len(articles_1c)}] {article} (stock={stock})", end=" ")

            if i > 0:
                await asyncio.sleep(1.2)

            json_product, match_type = await find_on_koton(article, client)

            if not json_product:
                print("→ не знайдено на koton")
                cur.execute(
                    "UPDATE products SET match_type=NULL WHERE article_1c=?",
                    (article,)
                )
                conn.commit()
                not_found += 1
                continue

            koton = _product_from_json(article, json_product)
            print(f"→ {match_type} | {koton.name[:45]}")

            photos = await fetch_and_download_all_photos(koton, article, client, ORIGINALS_DIR, json_product)
            if not photos:
                print(f"  фото не завантажились")
                cur.execute(
                    "UPDATE products SET match_type=? WHERE article_1c=?",
                    (match_type, article)
                )
                conn.commit()
                not_found += 1
                continue

            title_ua = await translate_tr_to_uk(koton.name, client)
            extra = json.dumps(photos[1:], ensure_ascii=False) if len(photos) > 1 else None

            # Визначаємо категорію з атрибутів
            attrs = json_product.get("attributes", {})
            cat_tr = attrs.get("filterable_category", attrs.get("morhipo_kategori", ""))
            category = map_category(cat_tr)

            cur.execute("""
                UPDATE products SET
                    title=?, title_ua=?, original_photo=?, extra_photos=?,
                    match_type=?, category=?,
                    price_uah=?,
                    updated_at=datetime('now')
                WHERE article_1c=?
            """, (
                koton.name, title_ua, photos[0], extra,
                match_type, category,
                koton.price_try,
                article
            ))
            conn.commit()

            print(f"  ✓ {title_ua or koton.name[:40]} | {len(photos)} фото | {category or '?'}")
            found += 1

    conn.close()
    print(f"\n=== Готово ===")
    print(f"Знайдено на koton: {found}")
    print(f"Не знайдено:       {not_found}")


CATEGORY_MAP_TR = {
    "Tişört": "Футболка",
    "T-shirt": "Футболка",
    "Gömlek": "Сорочка",
    "Pantolon": "Штани",
    "Jean": "Джинси",
    "Kot": "Джинси",
    "Şort": "Шорти",
    "Kazak": "Светр/Кардиган",
    "Hırka": "Светр/Кардиган",
    "Triko": "Светр/Кардиган",
    "Sweatshirt": "Світшот",
    "Ceket": "Куртка",
    "Mont": "Куртка",
    "Bomber": "Куртка",
    "Polo": "Поло",
    "Şort": "Шорти",
}

def map_category(cat_tr: str) -> str:
    if not cat_tr:
        return ""
    for kw, ua in CATEGORY_MAP_TR.items():
        if kw.lower() in cat_tr.lower():
            return ua
    return ""


asyncio.run(main())
