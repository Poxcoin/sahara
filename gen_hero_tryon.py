"""
Desert hero via tryon-v1.6:
  model_image  = hero-editorial.jpg (desert scene with model already in it)
  garment_image = camel midi dress from catalog
→ Fashn.ai dresses the desert model in our actual garment
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.fashn import tryon

KEY     = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
MODEL   = "app/static/img/hero-editorial.jpg"   # desert background with model
OUT     = "app/static/img/hero-editorial.jpg"

GARMENTS = [
    ("media/koton_originals/6SAK80023EK.jpg", "dress"),   # camel midi dress
]

async def main():
    garment, cat = GARMENTS[0]
    print(f"→ tryon: {os.path.basename(garment)} on desert model...")
    data = await tryon(garment, MODEL, KEY, cat)
    with open(OUT, "wb") as f:
        f.write(data)
    print(f"✓ {OUT} — {len(data)//1024}KB")

asyncio.run(main())
