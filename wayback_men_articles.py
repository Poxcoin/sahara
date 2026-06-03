"""
Шукає архівні сторінки Koton в Wayback Machine для конкретних артикулів з 1С чоловічого.
Для кожного артикулу перевіряє koton.com/list/?search_text={article} за 2024-2026.
Якщо знаходить — витягує назву, фото, URL.
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

CDX_URL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=www.koton.com/list/*{article}*"
    "&matchType=prefix"
    "&output=json"
    "&from=20240101"
    "&to=20261231"
    "&fl=timestamp,original"
    "&collapse=urlkey"
    "&limit=5"
    "&filter=statuscode:200"
)
SEARCH_URL = "https://www.koton.com/list/?search_text={article}"
WAYBACK = "https://web.archive.org/web/{timestamp}/{original}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept-Language": "tr-TR,tr;q=0.9",
}

ARTICLES = """6WAM10032HK
6WAM10043HK
6WAM10053HK
6WAM10058HK
6WAM10073HK
6WAM40002AA
6WAM40003AA
6WAM40004HK
6WAM40004NK
6WAM40005HK
6WAM40005ND
6WAM40006HK
6WAM40006ND
6WAM40007AA
6WAM40007HK
6WAM40008NK
6WAM40010ID
6WAM40013MK
6WAM40016MK
6WAM40017MK
6WAM40019ID
6WAM40020MK
6WAM40022ID
6WAM40022ND
6WAM40025ND
6WAM40032NK
6WAM40038HW
6WAM40050HW
6WAM40054ND
6WAM40055ND
6WAM40063HW
6WAM40071ND
6WAM40095HW
6WAM40098HW
6WAM50002AA
6WAM50003AA
6WAM50012ND
6WAM50023AA
6WAM50025AA
6WAM50026AA
6WAM50039AA
6WAM50082AA
6WAM50093AA
6WAM60061HW
6WAM60062HW
6WAM60066HW
6WAM60084HW
6WAM60101HW
6WAM60102HW
6WAM60104HW
6WAM60189HW
6WAM70008HT
6WAM70016MK
6WAM70018MK
6WAM70019MK
6WAM70021MK
6WAM70022MK
6WAM70023MK
6WAM70025MK
6WAM70028MK
6WAM70029MK
6WAM70033MK
6WAM70034MK
6WAM70043MK
6WAM70049MK
6WAM70077MK
6WAM70122MK
6WAM70158MK
6WAM70159MK""".strip().splitlines()


def parse_products(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for div in soup.select(".js-insider-product"):
        try:
            d = json.loads(div.get_text(strip=True))
            if d.get("name") and d.get("product_image_url"):
                results.append(d)
        except Exception:
            pass
    return results


async def check_live(article: str, client: httpx.AsyncClient) -> list[dict]:
    """Спочатку пробуємо живий сайт."""
    url = SEARCH_URL.format(article=article)
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        products = parse_products(resp.text)
        if products:
            return products
    except Exception:
        pass
    return []


async def check_wayback(article: str, client: httpx.AsyncClient) -> list[dict]:
    """Шукаємо в архіві Wayback Machine."""
    # Шукаємо будь-які snapshot з цим артикулом в URL
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url=www.koton.com/list/*{article}*"
        "&matchType=prefix&output=json&from=20240101&to=20261231"
        "&fl=timestamp,original&collapse=urlkey&limit=3&filter=statuscode:200"
    )
    try:
        resp = await client.get(cdx_url, timeout=20)
        data = resp.json()
        snapshots = data[1:] if len(data) > 1 else []
    except Exception:
        snapshots = []

    # Також перевіряємо пряму search сторінку
    if not snapshots:
        cdx_url2 = (
            "https://web.archive.org/cdx/search/cdx"
            f"?url=www.koton.com/list/?search_text={article}"
            "&output=json&from=20240101&to=20261231"
            "&fl=timestamp,original&limit=3&filter=statuscode:200"
        )
        try:
            resp = await client.get(cdx_url2, timeout=20)
            data = resp.json()
            snapshots = data[1:] if len(data) > 1 else []
        except Exception:
            pass

    for ts, orig in snapshots:
        wb_url = WAYBACK.format(timestamp=ts, original=orig)
        try:
            resp = await client.get(wb_url, headers=HEADERS, timeout=20, follow_redirects=True)
            products = parse_products(resp.text)
            if products:
                return products
        except Exception:
            pass
        await asyncio.sleep(0.3)

    return []


async def main():
    found = []
    not_found = []

    print(f"Перевіряю {len(ARTICLES)} артикулів чоловічого магазину...\n")

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for i, article in enumerate(ARTICLES):
            print(f"[{i+1}/{len(ARTICLES)}] {article} ... ", end="", flush=True)

            products = await check_live(article, client)
            source = "live"

            if not products:
                await asyncio.sleep(0.5)
                products = await check_wayback(article, client)
                source = "wayback"

            if products:
                p = products[0]
                name = p.get("name", "")[:50]
                price = p.get("unit_sale_price") or p.get("unit_price") or 0
                url = p.get("url", "")
                if url and not url.startswith("http"):
                    url = "https://www.koton.com" + url
                print(f"✓ [{source}] {name} | {price} TRY")
                found.append({
                    "article": article,
                    "name": name,
                    "price_try": price,
                    "url": url,
                    "source": source,
                })
            else:
                print("✗ не знайдено")
                not_found.append(article)

            await asyncio.sleep(1.0)

    print(f"\n=== Результат ===")
    print(f"Знайдено: {len(found)}/{len(ARTICLES)}")
    print(f"Не знайдено: {len(not_found)}")

    if not_found:
        print(f"\nАртикули без результату:")
        for a in not_found:
            print(f"  {a}")

    out = Path(__file__).parent / "men_articles_wayback_result.json"
    out.write_text(json.dumps(found, ensure_ascii=False, indent=2))
    print(f"\nРезультат збережено: {out}")


if __name__ == "__main__":
    asyncio.run(main())
