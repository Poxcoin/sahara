"""
Compare two hero tryon approaches:
  v1 = F-001.jpg (studio) + camel dress → Fashn generates editorial bg
  v2 = desert hero (492113f2efa6.jpg) + camel dress → keeps real desert bg
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import tryon

KEY     = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
GARMENT = "media/koton_originals/6SAK80023EK.jpg"   # camel midi dress

JOBS = [
    ("app/static/img/hero_v1.jpg", "media/models/F-001.jpg",              "dress", "v1 studio→editorial"),
    ("app/static/img/hero_v2.jpg", "media/hero/492113f2efa6.jpg",         "dress", "v2 desert base"),
]

async def gen(out, model, cat, label, sem):
    async with sem:
        print(f"→ {label}")
        data = await tryon(GARMENT, model, KEY, cat)
        with open(out, "wb") as f:
            f.write(data)
        print(f"✓ {label} — {len(data)//1024}KB → {out}")

async def main():
    sem = asyncio.Semaphore(2)
    await asyncio.gather(*[gen(o, m, c, l, sem) for o, m, c, l in JOBS])
    print("\nДва варіанти готові — порівняй hero_v1.jpg і hero_v2.jpg")

asyncio.run(main())
