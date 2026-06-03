#!/usr/bin/env python3
"""
Знаходить нові CDN URL фото Koton через Google Images і завантажує їх.
Запуск: python3 fetch_photos_google.py
"""
import asyncio
import re
import sys
import json
import datetime
from pathlib import Path
import httpx

sys.path.insert(0, '.')
from app.db import async_session
from app.models import Product, ProductStatus
from sqlalchemy import select

BASE_DIR = Path(__file__).parent
MEDIA = BASE_DIR / 'media' / 'koton_originals'
HEADERS_DL = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.koton.com/",
}


async def download_url(url: str, dest: Path, client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get(url, headers=HEADERS_DL, timeout=30, follow_redirects=True)
        if r.status_code == 200 and len(r.content) > 5000:
            dest.write_bytes(r.content)
            return True
    except Exception as e:
        print(f"    download error: {e}")
    return False


async def find_koton_cdn_urls_google(article: str, page) -> list[str]:
    """Шукає нові CDN URL через Google Images."""
    url = f"https://www.google.com/search?q=koton+{article}&tbm=isch"
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(2)

    urls = await page.evaluate("""() => {
        const html = document.documentElement.innerHTML;
        const matches = html.match(/https:\\/\\/ktnimg2\\.mncdn\\.com\\/products\\/\\d{4}\\/[^"\\\\]+\\.jpg/g) || [];
        return [...new Set(matches)].slice(0, 8);
    }""")
    return urls or []


async def main():
    # Завантажуємо список pending products
    async with async_session() as s:
        r = await s.execute(
            select(Product).where(Product.status == ProductStatus.PENDING)
        )
        products = r.scalars().all()

    # Фільтруємо тільки ті де файл порожній або відсутній
    MEDIA_ROOT = BASE_DIR / 'media'
    to_fix = []
    for p in products:
        if not p.original_photo:
            to_fix.append(p)
        else:
            full = MEDIA_ROOT / p.original_photo
            if not full.exists() or full.stat().st_size == 0:
                to_fix.append(p)
    products = to_fix

    print(f"Знайдено {len(products)} товарів з порожнім/відсутнім фото")

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="tr-TR",
        )
        page = await ctx.new_page()

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for i, prod in enumerate(products):
                art = prod.article_1c
                print(f"\n[{i+1}/{len(products)}] {art}")

                cdn_urls = await find_koton_cdn_urls_google(art, page)
                if not cdn_urls:
                    print(f"  ✗ Google не знайшов CDN URL")
                    await asyncio.sleep(3)
                    continue

                print(f"  Знайдено {len(cdn_urls)} URL: {cdn_urls[0][:80]}...")

                # Завантажуємо перше фото як основне
                dest_main = MEDIA / f"{art}.jpg"
                ok = await download_url(cdn_urls[0], dest_main, client)
                if not ok:
                    print(f"  ✗ Не вдалося завантажити перший URL")
                    continue

                rel_main = f"koton_originals/{art}.jpg"

                # Завантажуємо додаткові фото
                extras_rel = []
                for j, url in enumerate(cdn_urls[1:4]):
                    edest = MEDIA / f"{art}_{j+1}.jpg"
                    if await download_url(url, edest, client):
                        extras_rel.append(f"koton_originals/{art}_{j+1}.jpg")

                # Зберігаємо в БД
                async with async_session() as s:
                    p = await s.get(Product, prod.id)
                    if p:
                        p.original_photo = rel_main
                        p.extra_photos = json.dumps(extras_rel) if extras_rel else None
                        p.updated_at = datetime.datetime.now(datetime.UTC)
                        await s.commit()

                print(f"  ✓ {rel_main} + {len(extras_rel)} extra")
                await asyncio.sleep(2)

        await browser.close()

    print("\n=== Готово ===")

    # Підсумок
    async with async_session() as s:
        r = await s.execute(select(Product).where(Product.status == ProductStatus.PENDING))
        remaining = r.scalars().all()
        no_photo = [p for p in remaining if not p.original_photo]
        print(f"Залишилось без фото: {len(no_photo)}")


if __name__ == "__main__":
    asyncio.run(main())
