"""Generate 2 hero candidates for desert/new collection theme."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import product_to_model

KEY = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"

JOBS = [
    ("app/static/img/hero_cand_a.jpg", "media/koton_originals/6SAK40071PW.jpg", "pants"),
    ("app/static/img/hero_cand_b.jpg", "media/koton_originals/6SAK80023EK.jpg", "dress"),
]

async def gen(out, garment, cat, sem):
    async with sem:
        print(f"→ {os.path.basename(garment)}")
        data = await product_to_model(garment, KEY, cat)
        with open(out, "wb") as f: f.write(data)
        print(f"✓ {os.path.basename(out)} — {len(data)//1024}KB")

async def main():
    sem = asyncio.Semaphore(2)
    await asyncio.gather(*[gen(o, g, c, sem) for o, g, c in JOBS])

if __name__ == "__main__":
    asyncio.run(main())
