"""
Generate editorial photos for hero + journal sections.
All via Fashn.ai product-to-model (no TG photos, no model photos).
Luxury editorial aesthetic.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import product_to_model

KEY  = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
KDIR = "media/koton_originals"
OUT  = "app/static/img"

JOBS = [
    # (output, garment, category, label)
    (f"{OUT}/hero-editorial.jpg", f"{KDIR}/6SAK80001FW.jpg", "dress",    "Hero — chiffon mini dress"),
    (f"{OUT}/journal1.jpg",       f"{KDIR}/6SAK10029EK.jpg", "blouse",   "Journal1 — cotton blouse boat neck"),
    (f"{OUT}/journal2.jpg",       f"{KDIR}/6SAK20005UW.jpg", "knitwear", "Journal2 — viscose vest"),
    (f"{OUT}/journal3.jpg",       f"{KDIR}/6SAL60029IW.jpg", "blouse",   "Journal3 — ruffle blouse"),
]


async def gen(out, garment, cat, label, sem):
    async with sem:
        print(f"  → {label}")
        try:
            data = await product_to_model(garment, KEY, cat)
            with open(out, "wb") as f:
                f.write(data)
            print(f"  ✓ {os.path.basename(out)} — {len(data)//1024}KB")
        except Exception as e:
            print(f"  ✗ {os.path.basename(out)} — {e}")


async def main():
    sem = asyncio.Semaphore(2)
    await asyncio.gather(*[gen(o, g, c, l, sem) for o, g, c, l in JOBS])
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
