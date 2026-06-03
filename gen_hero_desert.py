import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))
from app.services.fashn import product_to_model

KEY = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"

# Sand/earth tones → maximize chance of outdoor warm desert bg
JOBS = [
    ("app/static/img/hero_desert_1.jpg", "media/koton_originals/6SAK80023EK.jpg", "dress"),
    ("app/static/img/hero_desert_2.jpg", "media/koton_originals/6SAK40071PW.jpg", "pants"),
    ("app/static/img/hero_desert_3.jpg", "media/koton_originals/6SAK80003UW.jpg", "dress"),
]

async def gen(out, garment, cat, sem):
    async with sem:
        print(f"→ {os.path.basename(garment)}")
        data = await product_to_model(garment, KEY, cat)
        with open(out, "wb") as f: f.write(data)
        print(f"✓ {os.path.basename(out)} {len(data)//1024}KB")

async def main():
    sem = asyncio.Semaphore(3)
    await asyncio.gather(*[gen(o, g, c, sem) for o, g, c in JOBS])

asyncio.run(main())
