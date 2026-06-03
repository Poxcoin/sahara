"""
Витягує ВСІ артикули чоловічого одягу Koton з живого сайту.

Артикул формату: 6WAM40002AA / 6SAM10385MK
  [0]   = рік колекції (6=2026, 5=2025...)
  [1]   = сезон (W=Winter, S=Spring/Summer)
  [2]   = A=?
  [3]   = M=men (erkek)
  [4-8] = код стилю
  [9-10]= колір/варіант

Метод: regex по HTML listing сторінок — без заходу на detail.
"""

import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# Regex для артикулів Koton чоловічого: 6WAM40002AA, 6SAM10385MK тощо
ARTICLE_RE = re.compile(r'\b([0-9][WS]A?M\d{5}[A-Z]{2,3})\b')

# Всі чоловічі категорії одягу
ERKEK_CATEGORIES = [
    "https://www.koton.com/erkek-tisort/",
    "https://www.koton.com/erkek-gomlek/",
    "https://www.koton.com/erkek-pantolon/",
    "https://www.koton.com/erkek-esofman-alti/",
    "https://www.koton.com/erkek-sort/",
    "https://www.koton.com/erkek-polo/",
    "https://www.koton.com/erkek-sweatshirt/",
    "https://www.koton.com/erkek-hirka-triko/",
    "https://www.koton.com/erkek-kazak/",
    "https://www.koton.com/erkek-jean/",
    "https://www.koton.com/erkek-ceket/",
    "https://www.koton.com/erkek-mont/",
    "https://www.koton.com/erkek-yelek/",
    "https://www.koton.com/erkek-takim/",
    "https://www.koton.com/erkek-pijama/",
    "https://www.koton.com/erkek-ic-giyim/",
    "https://www.koton.com/erkek-esofman-takimi/",
    "https://www.koton.com/erkek-atlet/",
    "https://www.koton.com/erkek-dis-giyim/",
]

OUTPUT_JSON = Path(__file__).parent / "koton_erkek_articles.json"
OUTPUT_TXT = Path(__file__).parent / "koton_erkek_articles.txt"


def get_pagination_total(html: str) -> int:
    """Витягує total з <pz-pagination total='984'>."""
    m = re.search(r'<pz-pagination[^>]+total=["\'](\d+)["\']', html)
    if m:
        total = int(m.group(1))
        per_page = 24
        m2 = re.search(r'per-page=["\'](\d+)["\']', html)
        if m2:
            per_page = int(m2.group(1))
        return (total + per_page - 1) // per_page
    return 1


def extract_articles_from_html(html: str) -> list[str]:
    """Витягує всі артикули чоловічого одягу з HTML."""
    return list(set(ARTICLE_RE.findall(html)))


def extract_products_from_listing(html: str) -> list[dict]:
    """Витягує базові дані продуктів з listing сторінки."""
    soup = BeautifulSoup(html, "html.parser")
    products = []

    for div in soup.select(".js-product-wrapper"):
        ean = div.get("data-sku", "")
        url = div.get("data-url", "")
        if url and not url.startswith("http"):
            url = "https://www.koton.com" + url
        products.append({"ean": ean, "url": url})

    return products


async def scrape_category(cat_url: str, client: httpx.AsyncClient, all_articles: set, product_map: dict):
    """Скрапить одну категорію — всі сторінки."""
    print(f"\n[CAT] {cat_url}")

    try:
        resp = await client.get(cat_url, headers=HEADERS, timeout=20, follow_redirects=True)
        html = resp.text
    except Exception as e:
        print(f"  → помилка: {e}")
        return

    total_pages = get_pagination_total(html)
    found_before = len(all_articles)

    # Обробляємо першу сторінку
    arts = extract_articles_from_html(html)
    all_articles.update(arts)
    prods = extract_products_from_listing(html)
    for p in prods:
        if p["url"]:
            product_map[p["ean"]] = p["url"]

    print(f"  → {total_pages} сторінок")

    # Решта сторінок
    for page in range(2, total_pages + 1):
        await asyncio.sleep(0.8)
        page_url = cat_url.rstrip("/") + f"/?page={page}"
        try:
            resp = await client.get(page_url, headers=HEADERS, timeout=20, follow_redirects=True)
            html = resp.text
            arts = extract_articles_from_html(html)
            all_articles.update(arts)
            prods = extract_products_from_listing(html)
            for p in prods:
                if p["url"]:
                    product_map[p["ean"]] = p["url"]

            sys.stdout.write(f"\r  сторінка {page}/{total_pages} | артикулів: {len(all_articles)}  ")
            sys.stdout.flush()
        except Exception:
            break

    added = len(all_articles) - found_before
    print(f"\n  → +{added} нових артикулів (всього: {len(all_articles)})")


async def main():
    all_articles: set = set()
    product_map: dict = {}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for cat_url in ERKEK_CATEGORIES:
            await scrape_category(cat_url, client, all_articles, product_map)
            await asyncio.sleep(1.5)

    # Сортуємо і групуємо по роках
    sorted_arts = sorted(all_articles)
    by_year = defaultdict(list)
    for a in sorted_arts:
        by_year[a[0]].append(a)

    print(f"\n=== Готово: {len(sorted_arts)} унікальних артикулів ===")
    for year, arts in sorted(by_year.items()):
        print(f"  Колекція {year}xxx: {len(arts)} артикулів")

    # Зберігаємо TXT
    OUTPUT_TXT.write_text("\n".join(sorted_arts))
    print(f"\nАртикули: {OUTPUT_TXT}")

    # Зберігаємо JSON з URL
    result = [{"article": a} for a in sorted_arts]
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"JSON: {OUTPUT_JSON}")


if __name__ == "__main__":
    asyncio.run(main())
