"""Populate match_type using JSON API with exact base_code verification.

exact  = article found on koton.com and base_code matches exactly
approx = article not found OR found but base_code doesn't match (wrong product!)
"""
import asyncio, sqlite3, json
import httpx

SEARCH_URL = "https://www.koton.com/list/?search_text={article}&format=json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

async def _search(client, article: str) -> list[str]:
    """Return list of base_codes found for given search term."""
    try:
        r = await client.get(SEARCH_URL.format(article=article), headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        d = r.json()
        return [p.get("base_code", "") for p in d.get("products", [])]
    except Exception:
        return []

async def classify(client, article: str) -> str:
    if not article:
        return "approx"

    # 1. Search with full article
    codes = await _search(client, article)
    if article in codes:
        return "exact"

    # 2. Search stripping year digit
    if article[0].isdigit() and len(article) > 1:
        codes2 = await _search(client, article[1:])
        if article in codes2:
            return "exact"

    return "approx"

async def main():
    conn = sqlite3.connect("data/sahara.db")
    cur = conn.cursor()
    cur.execute("SELECT id, article_1c FROM products WHERE original_photo IS NOT NULL AND original_photo != ''")
    rows = cur.fetchall()
    print(f"Перевіряємо {len(rows)} товарів...")

    sem = asyncio.Semaphore(5)

    async def process(pid, article):
        async with sem:
            mt = await classify(client, article or "")
            print(f"  {article} → {mt}")
            return pid, mt

    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(*[process(pid, art) for pid, art in rows])

    exact = sum(1 for _, mt in results if mt == "exact")
    approx = sum(1 for _, mt in results if mt == "approx")
    print(f"\nТочно (base_code match): {exact}")
    print(f"Не факт (не знайдено або чужий товар): {approx}")

    for pid, mt in results:
        cur.execute("UPDATE products SET match_type=? WHERE id=?", (mt, pid))
    conn.commit()
    conn.close()
    print("Збережено.")

if __name__ == "__main__":
    asyncio.run(main())
