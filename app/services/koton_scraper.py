"""
Koton.com scraper — витягує дані товару за артикулом постачальника.

Пошук: GET https://www.koton.com/list/?search_text={article}&format=json
Перевірка: base_code у відповіді повинен точно збігатись з артикулом.

Запуск для тесту:
    python -m app.services.koton_scraper 6SAM10006MK
"""
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.config import settings

SEARCH_URL = "https://www.koton.com/list/?search_text={article}&format=json"
CDN_BASE = "https://ktnimg2.mncdn.com"
IMAGE_SIZE = "size870x1142"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

# Headers for fetching product page HTML (for photos / size chart)
HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def photos_from_product_json(p: dict) -> list[str]:
    """Повертає всі URL фото з JSON-продукту (productimage_set), max 5, розмір 870x1142."""
    imgs = p.get("productimage_set", [])
    seen: set[str] = set()
    result: list[str] = []
    for img in imgs:
        raw = img.get("image", "")
        if not raw:
            continue
        clean = re.sub(r"_size\d+x\d+", "", raw)
        key = clean.split("/")[-1]
        if key not in seen:
            seen.add(key)
            result.append(re.sub(r"\.jpg$", f"_{IMAGE_SIZE}.jpg", clean))
    return result[:5]


async def fetch_all_photos(product_url: str, client: httpx.AsyncClient) -> list[str]:
    """Повертає всі URL фото з HTML-сторінки товару як fallback."""
    try:
        resp = await client.get(product_url, headers=HTML_HEADERS, timeout=15)
        html = resp.text
    except Exception:
        return []
    imgs = re.findall(r'https://ktnimg2\.mncdn\.com/products/[^\s"<>]+\.jpg', html)
    seen: set[str] = set()
    result: list[str] = []
    for img in imgs:
        base = re.sub(r'_size\d+x\d+', '', img)
        key = base.split('/')[-1]
        if key not in seen and "size48x80" not in img and "size112x148" not in img and "cropCenter" not in img:
            seen.add(key)
            result.append(re.sub(r'\.jpg$', f'_{IMAGE_SIZE}.jpg', base))
    return result[:5]


@dataclass
class KotonProduct:
    article: str          # артикул постачальника (з накладної)
    name: str             # назва турецькою
    price_try: float      # ціна в TL (роздрібна, Туреччина)
    color: str
    image_url: str        # найбільше фото _size870x1142
    product_url: str      # повний URL сторінки товару
    ean: str              # штрих-код / SKU Koton
    stock: int


async def _search_json(article: str, client: httpx.AsyncClient) -> list[dict]:
    """Шукає товар через JSON API koton.com. Повертає список продуктів."""
    try:
        r = await client.get(
            SEARCH_URL.format(article=article),
            headers=HEADERS,
            follow_redirects=True,
            timeout=15,
        )
        if r.status_code != 200:
            return []
        return r.json().get("products", [])
    except Exception:
        return []


def _best_image(url: str) -> str:
    """Перетворює будь-який CDN URL на найбільший розмір."""
    # видаляємо будь-який існуючий _sizeNxM суфікс
    clean = re.sub(r"_size\d+x\d+", "", url)
    # вставляємо потрібний розмір перед .jpg
    return re.sub(r"\.jpg$", f"_{IMAGE_SIZE}.jpg", clean)


# Переклад турецьких назв замірів → українська
_TR_MEASURE_UA: dict[str, str] = {
    "Beden": "Розмір",
    "Göğüs": "Груди",
    "Bel": "Талія",
    "Kalça": "Стегна",
    "Basen": "Стегна",
    "Omuz": "Плечі",
    "Uzunluk": "Довжина",
    "Kol Boyu": "Рукав",
    "Ön Ağ": "Передній крок",
    "Arka Ağ": "Задній крок",
    "Paça": "Штанина",
    "Boy": "Зріст",
    "Ağ": "Крок",
    "İç Bacak": "Внутр. шов",
    "Dış Bacak": "Зовн. шов",
    "Etek Boyu": "Довжина спідниці",
    "Yaka": "Комір",
    "Kol Ucu": "Манжет",
}


def _translate_size_chart(chart: dict) -> dict:
    """Перекладає назви рядків таблиці замірів з турецької на українську."""
    if not chart:
        return chart
    new_rows = []
    for row in chart.get("rows", []):
        if row:
            row = list(row)
            row[0] = _TR_MEASURE_UA.get(row[0], row[0])
        new_rows.append(row)
    return {"headers": chart.get("headers", []), "rows": new_rows}


async def _fetch_html(url: str, client: httpx.AsyncClient) -> str | None:
    """Завантажує HTML сторінки товару (для фото та таблиці розмірів)."""
    try:
        resp = await client.get(url, headers=HTML_HEADERS, follow_redirects=True, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


async def enrich_missing(gender: str = "men") -> dict:
    """
    Для товарів без фото: спочатку поточний koton.com, потім Wayback Machine.
    Використовує виправлену fetch_product (1 результат = збіг).
    """
    from app.db import async_session
    from app.models import Product, ProductStatus
    from sqlalchemy import select, and_
    import datetime

    originals_dir = Path(settings.media_dir) / "koton_originals"
    enriched = failed = 0

    async with async_session() as session:
        q = select(Product).where(
            and_(
                Product.stock > 0,
                Product.article_1c.isnot(None),
                Product.original_photo == "",
            )
        )
        if gender in ("men", "women"):
            q = q.where(Product.gender == gender)
        result = await session.execute(q)
        products = result.scalars().all()

    print(f"[enrich] {len(products)} товарів без фото → шукаю на koton.com")

    async with httpx.AsyncClient() as client:
        for i, db_prod in enumerate(products):
            if i > 0:
                await asyncio.sleep(1.5)

            article = db_prod.article_1c
            print(f"[enrich] [{i+1}/{len(products)}] {article}")

            koton = await fetch_product(article, client)
            if not koton:
                print(f"  → не знайдено")
                failed += 1
                continue

            all_photos = await fetch_and_download_all_photos(koton, article, client, originals_dir)
            if not all_photos:
                print(f"  → знайдено але фото не завантажились")
                failed += 1
                continue

            photo_rel = all_photos[0]
            extra = json.dumps(all_photos[1:], ensure_ascii=False) if len(all_photos) > 1 else None
            size_chart_data = await fetch_size_chart(koton.product_url, client)
            size_chart_json = json.dumps(size_chart_data, ensure_ascii=False) if size_chart_data else None
            desc = await fetch_product_description(koton.product_url, client)
            title_ua = await translate_tr_to_uk(koton.name, client)

            async with async_session() as session:
                prod = await session.get(Product, db_prod.id)
                if prod:
                    prod.title = koton.name
                    prod.title_ua = title_ua
                    prod.description = desc or f"{koton.color} | {koton.product_url}"
                    prod.original_photo = photo_rel
                    prod.extra_photos = extra
                    if size_chart_json:
                        prod.size_chart = size_chart_json
                    prod.updated_at = datetime.datetime.utcnow()
                    await session.commit()

            print(f"  → знайдено: {title_ua} | фото:{len(all_photos)}")
            enriched += 1

    print(f"[enrich] готово: знайдено={enriched}, не знайдено={failed}")
    return {"enriched": enriched, "failed": failed, "total": len(products)}


def _product_from_json(article: str, p: dict) -> "KotonProduct":
    """Будує KotonProduct з JSON-відповіді koton.com."""
    images = p.get("productimage_set", [])
    img_url = _best_image(images[0]["image"]) if images else ""

    product_url = p.get("absolute_url", "")
    if product_url and not product_url.startswith("http"):
        product_url = "https://www.koton.com" + product_url

    return KotonProduct(
        article=article,
        name=p.get("name", ""),
        price_try=float(p.get("retail_price") or p.get("price") or 0),
        color=p.get("attributes", {}).get("integration_color_desc", ""),
        image_url=img_url,
        product_url=product_url,
        ean=p.get("sku", ""),
        stock=1 if p.get("in_stock") else 0,
    )


async def fetch_product(article: str, client: httpx.AsyncClient) -> "KotonProduct | None":
    """Шукає товар за артикулом через JSON API з перевіркою base_code."""
    # Спробуємо: повний артикул, потім без першої цифри (якщо починається з digit)
    search_terms = [article]
    if article and article[0].isdigit() and len(article) > 1:
        search_terms.append(article[1:])  # "6SAM10006MK" → "SAM10006MK"

    for term in search_terms:
        products = await _search_json(term, client)
        for p in products:
            if p.get("base_code") == article:
                count = len(products)
                print(f"[koton] {article} → знайдено (base_code збігається, {count} варіантів)")
                return _product_from_json(article, p)

    print(f"[koton] {article} → не знайдено на koton.com")
    return None


async def fetch_and_download_all_photos(
    product: "KotonProduct",
    article: str,
    client: httpx.AsyncClient,
    originals_dir: Path,
    json_product: dict | None = None,
) -> list[str]:
    """Завантажує всі фото товару. Повертає список відносних шляхів."""
    # Спочатку беремо фото з JSON (productimage_set), потім fallback на HTML парсинг
    all_urls = []
    if json_product:
        all_urls = photos_from_product_json(json_product)
    if not all_urls and product.product_url:
        all_urls = await fetch_all_photos(product.product_url, client)
    if not all_urls:
        all_urls = [product.image_url]

    saved = []
    for i, url in enumerate(all_urls):
        suffix = "" if i == 0 else f"_{i}"
        path = originals_dir / f"{article}{suffix}.jpg"
        ok = await download_image(url, path, client)
        if ok:
            saved.append(f"koton_originals/{article}{suffix}.jpg")
        await asyncio.sleep(0.5)
    return saved


async def fetch_product_description(product_url: str, client: httpx.AsyncClient) -> str:
    """Дістає опис товару з мета-тегу сторінки Koton."""
    if not product_url:
        return ""
    try:
        resp = await client.get(product_url, headers=HEADERS, timeout=15, follow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")
        # спочатку шукаємо Open Graph description
        og = soup.find("meta", property="og:description")
        if og and og.get("content", "").strip():
            return og["content"].strip()
        # потім звичайний meta description
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content", "").strip():
            return meta["content"].strip()
    except Exception:
        pass
    return ""


async def fetch_size_chart(product_url: str, client: httpx.AsyncClient) -> dict | None:
    """
    Fetches size chart from a Koton product page.
    Returns dict like {"headers": ["Beden","Göğüs","Bel","Kalça"], "rows": [["XS","80-84","62-66","88-92"], ...]}
    or None if not found.
    """
    if not product_url:
        return None
    try:
        resp = await client.get(product_url, headers=HEADERS, timeout=15, follow_redirects=True)
        html = resp.text
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Try multiple selectors Koton uses for size charts
    table = (
        soup.select_one(".size-guide-table table") or
        soup.select_one(".size-guide table") or
        soup.select_one("table.size-table") or
        soup.select_one("[class*='sizeGuide'] table") or
        soup.select_one("[class*='size-chart'] table") or
        soup.select_one("[id*='sizeGuide'] table")
    )

    if not table:
        # Try to find any table with size-related headers
        for t in soup.find_all("table"):
            text = t.get_text().lower()
            if any(w in text for w in ["beden", "göğüs", "bel", "xs", " s ", " m ", " l "]):
                table = t
                break

    if not table:
        return None

    headers: list[str] = []
    rows: list[list[str]] = []

    # Extract headers
    th_row = table.find("tr")
    if th_row:
        headers = [th.get_text(strip=True) for th in th_row.find_all(["th", "td"])]

    # Extract data rows
    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if cells and any(c for c in cells):
            rows.append(cells)

    if not headers and not rows:
        return None

    return _translate_size_chart({"headers": headers, "rows": rows})


async def translate_tr_to_uk(text: str, client: httpx.AsyncClient) -> str:
    """Перекладає текст з турецької на українську через Google Translate (без ключа)."""
    if not text:
        return text
    try:
        import urllib.parse
        encoded = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=tr&tl=uk&dt=t&q={encoded}"
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = resp.json()
        parts = data[0] if data and data[0] else []
        result = "".join(p[0] for p in parts if p and p[0]).strip()
        return result or text
    except Exception:
        return text


async def download_image(image_url: str, save_path: Path, client: httpx.AsyncClient) -> bool:
    """Завантажує фото в save_path. Повертає True при успіху."""
    if not image_url:
        return False
    try:
        resp = await client.get(image_url, timeout=30)
        resp.raise_for_status()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"[koton] помилка завантаження фото: {e}")
        return False


async def scrape_articles(
    articles: list[str],
    download_photos: bool = True,
    rate_limit_sec: float = 3.0,
) -> list[KotonProduct]:
    """
    Масовий скрапінг списку артикулів.
    Завантажує фото в media/koton_originals/{article}.jpg
    """
    results = []
    originals_dir = Path(settings.media_dir) / "koton_originals"

    async with httpx.AsyncClient() as client:
        for i, article in enumerate(articles):
            if i > 0:
                await asyncio.sleep(rate_limit_sec)

            print(f"[koton] [{i+1}/{len(articles)}] шукаю {article}...")
            product = await fetch_product(article, client)
            if not product:
                continue

            print(f"  → {product.name} | {product.price_try} TRY | {product.color}")

            if download_photos and product.image_url:
                photo_path = originals_dir / f"{article}.jpg"
                ok = await download_image(product.image_url, photo_path, client)
                if ok:
                    print(f"  → фото: koton_originals/{article}.jpg")

            results.append(product)

    return results


async def scrape_and_save_to_db(articles: list[str], gender: str = "women") -> int:
    """
    Скрапить артикули і зберігає нові товари в БД SAHARA зі статусом PENDING.
    Повертає кількість доданих товарів.
    """
    from app.db import async_session, init_db
    from app.models import Product, ProductStatus
    from sqlalchemy import select

    await init_db()
    originals_dir = Path(settings.media_dir) / "koton_originals"
    added = 0

    async with httpx.AsyncClient() as client:
        for i, article in enumerate(articles):
            if i > 0:
                await asyncio.sleep(3.0)

            print(f"[koton] [{i+1}/{len(articles)}] {article}...")
            product = await fetch_product(article, client)
            if not product:
                continue

            async with async_session() as session:
                # перевірка дублів по назві + артикулу
                existing = await session.execute(
                    select(Product).where(Product.title == product.name)
                )
                if existing.scalar_one_or_none():
                    print(f"  → вже є: {product.name}")
                    continue

                all_photos = await fetch_and_download_all_photos(
                    product, article, client, originals_dir
                )
                photo_rel = all_photos[0] if all_photos else ""
                extra = json.dumps(all_photos[1:], ensure_ascii=False) if len(all_photos) > 1 else None

                size_chart_data = await fetch_size_chart(product.product_url, client)
                size_chart_json = json.dumps(size_chart_data, ensure_ascii=False) if size_chart_data else None
                desc = await fetch_product_description(product.product_url, client)

                db_product = Product(
                    title=product.name,
                    description=desc or f"{product.color} | {product.product_url}",
                    price_uah=product.price_try,
                    original_photo=photo_rel,
                    extra_photos=extra,
                    size_chart=size_chart_json,
                    status=ProductStatus.PENDING,
                    gender=gender,
                )
                session.add(db_product)
                await session.commit()
                print(f"  → додано: {product.name} | {product.price_try} TRY")
                added += 1

    return added


async def enrich_pending_from_1c(gender: str | None = None) -> dict:
    """
    Знаходить PENDING товари що прийшли з 1С (мають article_1c але немає фото),
    шукає їх на Koton.com і заповнює назву, фото, таблицю розмірів.
    Ціна (UAH) з 1С залишається — не перезаписується.
    """
    from app.db import async_session
    from app.models import Product, ProductStatus
    from sqlalchemy import select, and_
    import datetime

    originals_dir = Path(settings.media_dir) / "koton_originals"
    enriched = skipped = failed = 0

    async with async_session() as session:
        q = select(Product).where(
            and_(
                Product.status == ProductStatus.PENDING,
                Product.article_1c.isnot(None),
                Product.article_1c != "",
                Product.original_photo == "",
            )
        )
        if gender in ("men", "women"):
            q = q.where(Product.gender == gender)
        result = await session.execute(q)
        pending = result.scalars().all()

    if not pending:
        print(f"[koton-enrich] нема PENDING товарів для збагачення")
        return {"enriched": 0, "skipped": 0, "failed": 0, "total": 0}

    print(f"[koton-enrich] знайдено {len(pending)} товарів для скрапінгу")

    async with httpx.AsyncClient() as client:
        for i, db_prod in enumerate(pending):
            if i > 0:
                await asyncio.sleep(3.0)

            article = db_prod.article_1c
            print(f"[koton-enrich] [{i+1}/{len(pending)}] {article}...")

            koton = await fetch_product(article, client)
            if not koton:
                print(f"  → не знайдено на Koton")
                failed += 1
                continue

            all_photos = await fetch_and_download_all_photos(koton, article, client, originals_dir)
            photo_rel = all_photos[0] if all_photos else ""
            extra = json.dumps(all_photos[1:], ensure_ascii=False) if len(all_photos) > 1 else None

            size_chart_data = await fetch_size_chart(koton.product_url, client)
            size_chart_json = json.dumps(size_chart_data, ensure_ascii=False) if size_chart_data else None
            desc = await fetch_product_description(koton.product_url, client)

            async with async_session() as session:
                prod = await session.get(Product, db_prod.id)
                if not prod:
                    continue
                prod.title = koton.name
                prod.description = desc or f"{koton.color} | {koton.product_url}"
                prod.original_photo = photo_rel
                prod.extra_photos = extra
                prod.size_chart = size_chart_json
                prod.updated_at = datetime.datetime.utcnow()
                await session.commit()

            print(f"  → збагачено: {koton.name} | фото: {photo_rel}")
            enriched += 1

    print(f"[koton-enrich] готово: збагачено={enriched}, не знайдено={failed}, пропущено={skipped}")
    return {"enriched": enriched, "skipped": skipped, "failed": failed, "total": len(pending)}


async def bulk_translate_titles() -> dict:
    """Перекладає всі турецькі назви на українську для товарів без title_ua."""
    from app.db import async_session
    from app.models import Product
    from sqlalchemy import select, or_
    import datetime

    translated = skipped = failed = 0

    async with async_session() as session:
        q = select(Product).where(
            or_(Product.title_ua.is_(None), Product.title_ua == "")
        ).where(Product.title.isnot(None)).where(Product.title != "")
        result = await session.execute(q)
        products = result.scalars().all()

    print(f"[translate] знайдено {len(products)} товарів без title_ua")

    async with httpx.AsyncClient() as client:
        for i, db_prod in enumerate(products):
            if i > 0:
                await asyncio.sleep(0.3)

            title_ua = await translate_tr_to_uk(db_prod.title, client)
            if not title_ua or title_ua == db_prod.title:
                skipped += 1
                continue

            async with async_session() as session:
                prod = await session.get(Product, db_prod.id)
                if prod:
                    prod.title_ua = title_ua
                    prod.updated_at = datetime.datetime.utcnow()
                    await session.commit()
            translated += 1

            if i % 20 == 0:
                print(f"[translate] [{i+1}/{len(products)}] {db_prod.title} → {title_ua}")

    print(f"[translate] готово: перекладено={translated}, пропущено={skipped}, помилки={failed}")
    return {"translated": translated, "skipped": skipped, "total": len(products)}


async def re_enrich_all_koton_products(gender: str | None = None, force: bool = False, article_prefix: str | None = None) -> dict:
    """
    Повторно збагачує ВСІ товари з article_1c (не тільки PENDING, не тільки без фото).
    Оновлює: extra_photos, size_chart, price_uah (з Koton TRY), original_photo якщо порожнє.
    Пропускає тільки якщо вже є всі три поля (extra_photos + size_chart + price_uah),
    якщо force=False.
    article_prefix — фільтр по першому символу артикулу (наприклад "6").
    """
    from app.db import async_session
    from app.models import Product
    from sqlalchemy import select, and_
    import datetime

    originals_dir = Path(settings.media_dir) / "koton_originals"
    enriched = skipped = failed = 0

    async with async_session() as session:
        q = select(Product).where(
            and_(
                Product.article_1c.isnot(None),
                Product.article_1c != "",
            )
        )
        if gender in ("men", "women"):
            q = q.where(Product.gender == gender)
        if article_prefix:
            q = q.where(Product.article_1c.like(f"{article_prefix}%"))
        result = await session.execute(q)
        products = result.scalars().all()

    if not products:
        print("[koton-enrich] нема товарів з article_1c")
        return {"enriched": 0, "skipped": 0, "failed": 0, "total": 0}

    print(f"[koton-enrich] знайдено {len(products)} товарів для переперевірки")

    async with httpx.AsyncClient() as client:
        for i, db_prod in enumerate(products):
            if i > 0:
                await asyncio.sleep(2.0)

            article = db_prod.article_1c

            if not force:
                has_all = (
                    db_prod.extra_photos is not None
                    and db_prod.size_chart is not None
                    and db_prod.price_uah is not None
                )
                if has_all:
                    skipped += 1
                    continue

            print(f"[koton-enrich] [{i+1}/{len(products)}] {article}...")

            koton = await fetch_product(article, client)
            if not koton:
                print(f"  → не знайдено на Koton")
                failed += 1
                continue

            all_photos = await fetch_and_download_all_photos(koton, article, client, originals_dir)
            photo_rel = all_photos[0] if all_photos else ""
            extra = json.dumps(all_photos[1:], ensure_ascii=False) if len(all_photos) > 1 else None

            size_chart_data = await fetch_size_chart(koton.product_url, client)
            size_chart_json = json.dumps(size_chart_data, ensure_ascii=False) if size_chart_data else None

            title_ua = await translate_tr_to_uk(koton.name, client)
            desc = await fetch_product_description(koton.product_url, client)

            async with async_session() as session:
                prod = await session.get(Product, db_prod.id)
                if not prod:
                    continue
                if not prod.original_photo:
                    prod.original_photo = photo_rel
                prod.extra_photos = extra
                if size_chart_json:
                    prod.size_chart = size_chart_json
                # Не перезаписуємо ціну якщо вона вже є з 1С
                if not prod.price_uah:
                    prod.price_uah = koton.price_try
                prod.title = koton.name
                prod.title_ua = title_ua
                prod.description = desc or f"{koton.color} | {koton.product_url}"
                prod.updated_at = datetime.datetime.utcnow()
                await session.commit()

            print(f"  → оновлено: {title_ua} | {koton.price_try} TRY | фото:{len(all_photos)}")
            enriched += 1

    print(f"[koton-enrich] готово: збагачено={enriched}, не знайдено={failed}, пропущено={skipped}")
    return {"enriched": enriched, "skipped": skipped, "failed": failed, "total": len(products)}


KOTON_WOMEN_CATEGORIES = [
    "https://www.koton.com/kadin-giyim/elbise/?sortby=newest",
    "https://www.koton.com/kadin-giyim/bluz/?sortby=newest",
    "https://www.koton.com/kadin-giyim/pantolon/?sortby=newest",
    "https://www.koton.com/kadin-giyim/etek/?sortby=newest",
    "https://www.koton.com/kadin-giyim/tisort/?sortby=newest",
    "https://www.koton.com/kadin-giyim/hirka-triko/?sortby=newest",
]

# ────────────────────────────────────────────────────────────
#  Wayback Machine — категорійний скрапінг по датах замовлень
# ────────────────────────────────────────────────────────────

# Дати замовлень → сезон (використовуються для визначення колекції)
ORDER_DATE_SEASONS = [
    ("20250228", "Зима/Весна 2025"),
    ("20250529", "Весна/Літо 2025"),
    ("20250911", "Осінь 2025"),
    ("20251205", "Зима 2025/2026"),
    ("20260319", "Весна 2026"),
]

KOTON_MEN_CATS = [
    ("https://www.koton.com/erkek-giyim/tisort/", "Футболка"),
    ("https://www.koton.com/erkek-giyim/gomlek/", "Сорочка"),
    ("https://www.koton.com/erkek-giyim/pantolon/", "Штани"),
    ("https://www.koton.com/erkek-giyim/sort/", "Шорти"),
    ("https://www.koton.com/erkek-giyim/hirka-triko/", "Светр/Кардиган"),
    ("https://www.koton.com/erkek-giyim/mont/", "Куртка"),
    ("https://www.koton.com/erkek-giyim/sweatshirt/", "Світшот"),
    ("https://www.koton.com/erkek-giyim/esofman/", "Спортивні штани"),
    ("https://www.koton.com/erkek-giyim/polo-tisort/", "Поло"),
    ("https://www.koton.com/erkek-giyim/denim/", "Джинси"),
    ("https://www.koton.com/erkek-giyim/atlet-ic-giyim/", "Майка"),
]

KOTON_WOMEN_CATS = [
    ("https://www.koton.com/kadin-giyim/elbise/", "Сукня"),
    ("https://www.koton.com/kadin-giyim/bluz/", "Блуза"),
    ("https://www.koton.com/kadin-giyim/pantolon/", "Штани"),
    ("https://www.koton.com/kadin-giyim/etek/", "Спідниця"),
    ("https://www.koton.com/kadin-giyim/tisort/", "Футболка"),
    ("https://www.koton.com/kadin-giyim/hirka-triko/", "Светр/Кардиган"),
    ("https://www.koton.com/kadin-giyim/mont/", "Куртка"),
    ("https://www.koton.com/kadin-giyim/sort/", "Шорти"),
    ("https://www.koton.com/kadin-giyim/jean/", "Джинси"),
    ("https://www.koton.com/kadin-giyim/gomlek/", "Сорочка"),
    ("https://www.koton.com/kadin-giyim/sweatshirt/", "Світшот"),
    ("https://www.koton.com/kadin-giyim/atlet-ic-giyim/", "Майка/Нижня білизна"),
]


# URL slug → category (from Koton URL path)
_URL_SLUG_TO_CAT: dict[str, str] = {
    "tisort": "Футболка",
    "polo-tisort": "Поло",
    "gomlek": "Сорочка",
    "pantolon": "Штани",
    "sort": "Шорти",
    "hirka-triko": "Светр/Кардиган",
    "mont": "Куртка",
    "sweatshirt": "Світшот",
    "esofman": "Спортивні штани",
    "denim": "Джинси",
    "jean": "Джинси",
    "atlet-ic-giyim": "Майка",
    "elbise": "Сукня",
    "bluz": "Блуза",
    "etek": "Спідниця",
}

# Turkish title keywords → category (ordered: longer/specific first)
_TITLE_KEYWORDS: list[tuple[str, str]] = [
    ("eşofman altı", "Спортивні штани"),
    ("esofman alti", "Спортивні штани"),
    ("polo tişört", "Поло"),
    ("polo tisort", "Поло"),
    ("sweatshirt", "Світшот"),
    ("hırka", "Светр/Кардиган"),
    ("hirka", "Светр/Кардиган"),
    ("triko", "Светр/Кардиган"),
    ("kazak", "Светр/Кардиган"),
    ("tişört", "Футболка"),
    ("tisort", "Футболка"),
    ("gömlek", "Сорочка"),
    ("gomlek", "Сорочка"),
    ("jean pantolon", "Джинси"),
    ("denim pantolon", "Джинси"),
    ("jean", "Джинси"),
    ("denim", "Джинси"),
    ("pantolon", "Штани"),
    ("şort", "Шорти"),
    (" sort", "Шорти"),
    ("mont", "Куртка"),
    ("parka", "Куртка"),
    ("ceket", "Пальто/Жакет"),
    ("elbise", "Сукня"),
    ("bluz", "Блуза"),
    ("etek", "Спідниця"),
    ("atlet", "Майка"),
]

# Article letter-code → season mapping (from Koton's internal coding)
# Pattern: 5/6 + letter1 (A=AW=autumn/winter, S=SS=spring/summer, W=winter?) + letter2 (A/K=men, D/E=women?)
_ARTICLE_SEASON_CODES: dict[str, str] = {
    "SAK": "Весна/Літо 2025",
    "SAM": "Весна/Літо 2025",
    "WAM": "Зима 2025/2026",
    "WAK": "Зима 2025/2026",
    "FAM": "Осінь 2025",
    "FAK": "Осінь 2025",
    "BAM": "Зима/Весна 2025",
    "BAK": "Зима/Весна 2025",
    "NAK": "Весна 2026",
    "NAM": "Весна 2026",
}


def _category_from_url(product_url: str) -> str | None:
    """Extracts category from a Koton product URL path slug."""
    for slug, cat in _URL_SLUG_TO_CAT.items():
        if f"/{slug}/" in product_url:
            return cat
    return None


def _category_from_title(title: str) -> str | None:
    """Extracts category from a Turkish product title using keyword matching."""
    t = title.lower()
    for kw, cat in _TITLE_KEYWORDS:
        if kw in t:
            return cat
    return None


def _season_from_article(article: str) -> str | None:
    """Infers season from the 3-letter code inside a Koton article number."""
    art = article.upper()
    # Articles like 6WAM40022ID — extract chars 1-4 as the season code
    if len(art) >= 4:
        code = art[1:4]
        if code in _ARTICLE_SEASON_CODES:
            return _ARTICLE_SEASON_CODES[code]
    return None


async def _cdx_article_to_category(articles: list[str], client: httpx.AsyncClient) -> dict[str, str]:
    """
    Uses Wayback Machine CDX API to find archived koton.com product URLs for the given articles.
    Extracts category from the URL path. Much faster than fetching full HTML pages.
    """
    CDX_API = "https://web.archive.org/cdx/search/cdx"
    result: dict[str, str] = {}

    for article in articles:
        if article in result:
            continue
        params = {
            "url": f"www.koton.com/*{article.lower()}*",
            "output": "json",
            "limit": "5",
            "fl": "original",
            "filter": "statuscode:200",
        }
        try:
            resp = await client.get(CDX_API, params=params, timeout=15)
            rows = resp.json()
            for row in rows[1:]:
                url = row[0] if row else ""
                cat = _category_from_url(url)
                if cat:
                    result[article.upper()] = cat
                    break
        except Exception:
            pass
        await asyncio.sleep(0.5)

    return result


async def assign_categories_from_order_dates(
    gender: str = "men",
    dates: list[tuple[str, str]] | None = None,
) -> dict:
    """
    Assigns category + season to all products in the DB that are missing them.
    Strategy (fastest first):
      1. Extract category from product URL (if stored in description)
      2. Extract category from Turkish product title keywords
      3. Infer season from article letter-code (Koton internal coding)
      4. Use Wayback CDX API for any articles still missing a category
    """
    from app.db import async_session
    from app.models import Product
    from sqlalchemy import select, and_
    import datetime

    updated = 0

    async with async_session() as session:
        q = select(Product).where(
            and_(
                Product.article_1c.isnot(None),
                Product.article_1c != "",
                Product.category.is_(None),
            )
        )
        if gender in ("men", "women"):
            q = q.where(Product.gender == gender)
        result = await session.execute(q)
        products = result.scalars().all()

    print(f"[cat] {len(products)} товарів без категорії ({gender})")

    # Pass 1: URL + title + article code
    still_missing: list = []
    for db_prod in products:
        cat = None
        season = None

        # Try URL in description field (stored as "color | url")
        desc = db_prod.description or ""
        if "koton.com" in desc:
            url_part = desc.split("|")[-1].strip()
            cat = _category_from_url(url_part)

        # Fallback: title keywords
        if not cat and db_prod.title:
            cat = _category_from_title(db_prod.title)

        # Season from article code
        if db_prod.article_1c:
            season = _season_from_article(db_prod.article_1c)

        if cat or season:
            async with async_session() as session:
                prod = await session.get(Product, db_prod.id)
                if prod:
                    if cat:
                        prod.category = cat
                    if season:
                        prod.season = season
                    prod.updated_at = datetime.datetime.utcnow()
                    await session.commit()
            if cat:
                updated += 1
                print(f"  {db_prod.article_1c} → {cat or '?'} / {season or '?'}")
        else:
            still_missing.append(db_prod)

    # Pass 2: CDX API for remaining articles
    if still_missing:
        print(f"[cat] CDX пошук для {len(still_missing)} артикулів...")
        async with httpx.AsyncClient() as client:
            missing_articles = [p.article_1c for p in still_missing if p.article_1c]
            cdx_map = await _cdx_article_to_category(missing_articles, client)

        for db_prod in still_missing:
            art_upper = (db_prod.article_1c or "").upper()
            cat = cdx_map.get(art_upper)
            season = _season_from_article(db_prod.article_1c or "")
            if cat or season:
                async with async_session() as session:
                    prod = await session.get(Product, db_prod.id)
                    if prod:
                        if cat:
                            prod.category = cat
                        if season:
                            prod.season = season
                        prod.updated_at = datetime.datetime.utcnow()
                        await session.commit()
                if cat:
                    updated += 1
                    print(f"  [cdx] {db_prod.article_1c} → {cat} / {season or '?'}")

    print(f"\n[cat] готово: категоризовано={updated} з {len(products)}")
    return {"updated": updated, "total": len(products), "gender": gender}


async def scrape_koton_women_catalog(limit: int = 50) -> dict:
    """
    Скрейпить нові жіночі товари з категорій Koton.com.
    Додає тільки нові (перевіряє дублі по назві).
    Повертає кількість доданих.
    """
    from app.db import async_session
    from app.models import Product, ProductStatus
    from sqlalchemy import select
    import datetime

    originals_dir = Path(settings.media_dir) / "koton_originals"
    added = skipped = failed = 0

    async with httpx.AsyncClient() as client:
        for cat_url in KOTON_WOMEN_CATEGORIES:
            if added >= limit:
                break

            print(f"[koton-women] категорія: {cat_url}")
            html = await _fetch_html(cat_url, client)
            if not html:
                print(f"  → не вдалось завантажити")
                continue

            products_json = _parse_product_json(html)
            wrappers = _parse_wrapper_attrs(html)
            print(f"  → знайдено {len(products_json)} товарів")

            for i, p in enumerate(products_json):
                if added >= limit:
                    break

                name = p.get("name", "").strip()
                if not name:
                    continue

                # перевірка дубліката по назві
                async with async_session() as session:
                    existing = await session.execute(select(Product).where(Product.title == name))
                    if existing.scalar_one_or_none():
                        skipped += 1
                        continue

                image_raw = p.get("product_image_url", "")
                image_url = _best_image(image_raw) if image_raw else ""
                product_url = p.get("url", "")
                if product_url and not product_url.startswith("http"):
                    product_url = "https://www.koton.com" + product_url

                ean = p.get("id", "")
                price_try = float(p.get("unit_sale_price") or p.get("unit_price") or 0)

                koton = KotonProduct(
                    article=ean or f"w{i}",
                    name=name,
                    price_try=price_try,
                    color=p.get("color", ""),
                    image_url=image_url,
                    product_url=product_url,
                    ean=ean,
                    stock=int(p.get("stock") or 0),
                )

                await asyncio.sleep(1.5)

                all_photos = await fetch_and_download_all_photos(koton, ean or f"w_{name[:20]}", client, originals_dir)
                if not all_photos:
                    failed += 1
                    continue

                photo_rel = all_photos[0]
                extra = json.dumps(all_photos[1:], ensure_ascii=False) if len(all_photos) > 1 else None

                size_chart_data = await fetch_size_chart(product_url, client)
                size_chart_json = json.dumps(size_chart_data, ensure_ascii=False) if size_chart_data else None

                desc = await fetch_product_description(product_url, client)
                title_ua = await translate_tr_to_uk(name, client)

                async with async_session() as session:
                    db_product = Product(
                        title=name,
                        title_ua=title_ua,
                        description=desc or "",
                        price_uah=price_try,
                        original_photo=photo_rel,
                        extra_photos=extra,
                        size_chart=size_chart_json,
                        status=ProductStatus.PENDING,
                        gender="women",
                    )
                    session.add(db_product)
                    await session.commit()

                print(f"  → [{added+1}] {title_ua} | {price_try} TRY")
                added += 1

    print(f"[koton-women] готово: додано={added}, пропущено={skipped}, без фото={failed}")
    return {"added": added, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    articles = sys.argv[1:] if len(sys.argv) > 1 else ["6SAK80003UW"]

    async def main():
        results = await scrape_articles(articles)
        print(f"\n=== Результат: {len(results)} товарів ===")
        for p in results:
            print(f"  {p.article} | {p.name} | {p.price_try} TRY | {p.color}")
            print(f"    фото: {p.image_url}")
            print(f"    url:  {p.product_url}")

    asyncio.run(main())
