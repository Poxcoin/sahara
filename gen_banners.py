"""
Generate 5 editorial banner images for the homepage collection grid
using Fashn.ai product-to-model API.
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import product_to_model

FASHN_KEY = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
BASE = "media/koton_originals"
OUT = "app/static/img"

BANNERS = [
    # (filename, garment_file, category, label)
    ("banner_col1.jpg", f"{BASE}/6SAK80003UW.jpg", "dress",    "Asymmetric Draped Mini Dress"),
    ("banner_col2.jpg", f"{BASE}/6SAL60029IW.jpg", "blouse",   "Blouse with V-Neck Ruffle"),
    ("banner_col3.jpg", f"{BASE}/6SAK80001FW.jpg", "dress",    "Chiffon Mini Dress"),
    ("banner_col4.jpg", f"{BASE}/6SAK40071PW.jpg", "pants",    "Wide Straight Trousers"),
    ("banner_col5.jpg", f"{BASE}/6SAK40067NK.jpg", "skirt",    "Embroidered Mini Skirt-Shorts"),
]


async def generate_one(out_name, garment, category, label):
    out_path = f"{OUT}/{out_name}"
    print(f"[{out_name}] Generating: {label} ({category})")
    try:
        data = await product_to_model(garment, FASHN_KEY, category)
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"[{out_name}] Saved {len(data)//1024}KB → {out_path}")
        return True
    except Exception as e:
        print(f"[{out_name}] ERROR: {e}")
        return False


async def main():
    results = []
    for out_name, garment, category, label in BANNERS:
        ok = await generate_one(out_name, garment, category, label)
        results.append((out_name, ok))
        await asyncio.sleep(1)  # small pause between submissions

    print("\n=== Summary ===")
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")


if __name__ == "__main__":
    asyncio.run(main())
