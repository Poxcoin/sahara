"""
Generate editorial + journal banner images using Fashn.ai tryon-v1.6.
Uses model photo F-001.jpg for realistic editorial backgrounds.
Runs all 8 jobs in parallel.
"""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import tryon

KEY   = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
MODEL = "media/models/F-001.jpg"
KDIR  = "media/koton_originals"
OUT   = "app/static/img"

# (output_file, garment_file, category_hint, label)
JOBS = [
    # ── Editorial collection cards ──────────────────────────────────────
    ("banner_col1.jpg", f"{KDIR}/6SAL80024IW.jpg",  "dress",    "Cotton mini-dress with ruffles"),
    ("banner_col2.jpg", f"{KDIR}/6SAK10029EK.jpg",  "blouse",   "Cotton blouse boat neckline"),
    ("banner_col3.jpg", f"{KDIR}/6SAK80023EK.jpg",  "dress",    "Midi dress on straps"),
    ("banner_col4.jpg", f"{KDIR}/6SAL40010MD.jpg",  "pants",    "Wide jeans decorative stones"),
    ("banner_col5.jpg", f"{KDIR}/6SAK80004EK.jpg",  "dress",    "Midi dress V-neck short sleeves"),
    # ── Journal / trend cards ───────────────────────────────────────────
    ("journal1.jpg",    f"{KDIR}/6SAK80001FW.jpg",  "dress",    "Chiffon mini dress — Spring trends"),
    ("journal2.jpg",    f"{KDIR}/6SAK20005UW.jpg",  "knitwear", "Viscose vest — Wardrobe basics"),
    ("journal3.jpg",    f"{KDIR}/6SAL60029IW.jpg",  "blouse",   "Ruffle blouse — New collection"),
]


async def gen(out_name, garment, cat, label, sem):
    async with sem:
        out = f"{OUT}/{out_name}"
        print(f"  → [{out_name}] {label}")
        try:
            data = await tryon(garment, MODEL, KEY, cat)
            with open(out, "wb") as f:
                f.write(data)
            print(f"  ✓ [{out_name}] {len(data)//1024}KB saved")
        except Exception as e:
            print(f"  ✗ [{out_name}] {e}")


async def main():
    sem = asyncio.Semaphore(4)   # 4 concurrent jobs max
    tasks = [gen(o, g, c, l, sem) for o, g, c, l in JOBS]
    await asyncio.gather(*tasks)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
