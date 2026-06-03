"""Generate professional editorial model for banner_col1 (Жіноча Колекція)."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import product_to_model

KEY  = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
OUT  = "app/static/img/banner_col1.jpg"

GARMENTS = [
    ("media/koton_originals/6SAK80023EK.jpg", "dress"),
]

async def main():
    for garment, cat in GARMENTS:
        print(f"  → generating with {os.path.basename(garment)}")
        try:
            data = await product_to_model(garment, KEY, cat)
            with open(OUT, "wb") as f:
                f.write(data)
            print(f"  ✓ {OUT} — {len(data)//1024}KB")
        except Exception as e:
            print(f"  ✗ {e}")

if __name__ == "__main__":
    asyncio.run(main())
