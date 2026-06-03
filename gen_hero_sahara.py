"""Generate SAHARA-themed hero photo: camel/sand midi dress → desert editorial."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import product_to_model

KEY = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
OUT = "app/static/img/hero-editorial.jpg"

async def main():
    print("→ generating SAHARA hero (camel midi dress)...")
    data = await product_to_model("media/koton_originals/6SAK80023EK.jpg", KEY, "dress")
    with open(OUT, "wb") as f:
        f.write(data)
    print(f"✓ {OUT} — {len(data)//1024}KB")

if __name__ == "__main__":
    asyncio.run(main())
