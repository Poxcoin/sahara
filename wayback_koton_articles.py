"""
Витягує артикули Koton з Wayback Machine за 2024-2026.

Логіка:
1. CDX API → список всіх заархівованих URL сторінок Koton за 2024-2026
2. Для кожного унікального snapshot категорії → парсимо .js-insider-product JSON
3. Збираємо всі артикули (поле "id" = EAN/артикул Koton)
4. Зберігаємо в wayback_koton_articles.txt
"""

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

CDX_URL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url={url_pattern}"
    "&matchType=prefix"
    "&output=json"
    "&from={from_date}"
    "&to={to_date}"
    "&fl=timestamp,original"
    "&collapse=urlkey"
    "&limit=50000"
    "&filter=statuscode:200"
)

WAYBACK_BASE = "https://web.archive.org/web/{timestamp}/{original}"

# Категорії які шукаємо (жінки + чоловіки)
KOTON_PATTERNS = [
    "www.koton.com/kadin",
    "www.koton.com/erkek",
    "www.koton.com/list",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
}

OUTPUT_FILE = Path(__file__).parent / "wayback_koton_articles.txt"


def parse_articles_from_html(html: str) -> list[str]:
    """Витягує всі артикули з .js-insider-product JSON блоків."""
    articles = []
    soup = BeautifulSoup(html, "html.parser")

    for div in soup.select(".js-insider-product"):
        raw = div.get_text(strip=True)
        try:
            data = json.loads(raw)
            aid = data.get("id", "")
            if aid:
                articles.append(str(aid))
        except Exception:
            pass

    # Також шукаємо в data-atрибутах .js-product-wrapper
    for div in soup.select(".js-product-wrapper"):
        ean = div.get("data-sku", "")
        if ean:
            articles.append(str(ean))

    # І артикули з search_text= в URL
    for a in soup.select("a[href*='search_text=']"):
        m = re.search(r"search_text=([A-Z0-9]+)", a.get("href", ""))
        if m:
            articles.append(m.group(1))

    return list(set(articles))


async def get_cdx_snapshots(pattern: str, from_date: str, to_date: str, client: httpx.AsyncClient) -> list[tuple[str, str]]:
    """Повертає список (timestamp, original_url) з CDX API."""
    url = CDX_URL.format(
        url_pattern=pattern,
        from_date=from_date,
        to_date=to_date,
    )
    try:
        resp = await client.get(url, timeout=60)
        data = resp.json()
        if not data or len(data) < 2:
            return []
        # data[0] = заголовки, data[1:] = рядки
        return [(row[0], row[1]) for row in data[1:]]
    except Exception as e:
        print(f"  [CDX ERROR] {pattern}: {e}")
        return []


async def fetch_snapshot(timestamp: str, original: str, client: httpx.AsyncClient) -> str | None:
    """Завантажує один архівний snapshot."""
    url = WAYBACK_BASE.format(timestamp=timestamp, original=original)
    try:
        resp = await client.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


async def main():
    from_date = "20240101"
    to_date = "20261231"

    all_articles: set[str] = set()

    # Завантажуємо поточні артикули щоб не дублювати
    if OUTPUT_FILE.exists():
        existing = set(OUTPUT_FILE.read_text().splitlines())
        all_articles.update(existing)
        print(f"Завантажено {len(existing)} існуючих артикулів")

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for pattern in KOTON_PATTERNS:
            print(f"\n[CDX] Шукаю snapshots для: {pattern} ({from_date}–{to_date})")
            snapshots = await get_cdx_snapshots(pattern, from_date, to_date, client)
            print(f"  → знайдено {len(snapshots)} унікальних сторінок")

            # Обмежуємо кількість - беремо рівномірно по часу
            if len(snapshots) > 200:
                step = len(snapshots) // 200
                snapshots = snapshots[::step][:200]
                print(f"  → відібрано {len(snapshots)} для парсингу")

            for i, (timestamp, original) in enumerate(snapshots):
                # Пропускаємо CSS, JS, images
                if any(ext in original for ext in ['.css', '.js', '.jpg', '.png', '.gif', '.svg', '.ico']):
                    continue

                # Тільки сторінки з товарами (category/list pages)
                if not any(x in original for x in ['/kadin', '/erkek', '/list', 'koton.com']):
                    continue

                sys.stdout.write(f"\r  [{i+1}/{len(snapshots)}] {original[:80]:<80}")
                sys.stdout.flush()

                html = await fetch_snapshot(timestamp, original, client)
                if not html:
                    continue

                found = parse_articles_from_html(html)
                if found:
                    new_count = len(all_articles)
                    all_articles.update(found)
                    added = len(all_articles) - new_count
                    if added > 0:
                        sys.stdout.write(f"\r  [{i+1}/{len(snapshots)}] +{added} артикулів (всього: {len(all_articles)})  \n")

                await asyncio.sleep(0.5)

    print(f"\n\n=== Готово: {len(all_articles)} унікальних артикулів ===")

    # Зберігаємо
    sorted_articles = sorted(all_articles)
    OUTPUT_FILE.write_text("\n".join(sorted_articles))
    print(f"Збережено в: {OUTPUT_FILE}")

    return sorted_articles


if __name__ == "__main__":
    asyncio.run(main())
