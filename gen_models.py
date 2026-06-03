"""
Generate model showcase photos for:
  1) Homepage tryon section — 3 editorial cards with different garments
  2) Tryon page reference models — F-002.jpg, F-003.jpg
All via Fashn.ai tryon-v1.6 using F-001.jpg as base model.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import tryon

KEY   = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
MODEL = "media/models/F-001.jpg"
KDIR  = "media/koton_originals"

JOBS = [
    # Homepage tryon showcase cards
    ("media/models/tryon_card1.jpg", f"{KDIR}/6SAK80023EK.jpg", "dress",  "Card1 — midi dress straps"),
    ("media/models/tryon_card2.jpg", f"{KDIR}/6SAK10028EK.jpg", "blouse", "Card2 — asymmetric blouse"),
    ("media/models/tryon_card3.jpg", f"{KDIR}/6SAL80024IW.jpg", "dress",  "Card3 — ruffle cotton dress"),
    # Tryon page reference models (different garments so they look distinct)
    ("media/models/F-002.jpg",       f"{KDIR}/6SAK40036UW.jpg", "pants",  "F-002 — cigarette trousers"),
    ("media/models/F-003.jpg",       f"{KDIR}/6SAK20005UW.jpg", "blouse", "F-003 — viscose vest"),
]


async def gen(out, garment, cat, label, sem):
    async with sem:
        print(f"  → {label}")
        try:
            data = await tryon(garment, MODEL, KEY, cat)
            with open(out, "wb") as f:
                f.write(data)
            print(f"  ✓ {os.path.basename(out)} — {len(data)//1024}KB")
        except Exception as e:
            print(f"  ✗ {os.path.basename(out)} — {e}")


async def main():
    sem = asyncio.Semaphore(3)
    await asyncio.gather(*[gen(o, g, c, l, sem) for o, g, c, l in JOBS])
    print("\nDone.")

if __name__ == "__main__":
    asyncio.run(main())
