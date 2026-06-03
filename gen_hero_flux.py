"""Generate desert hero via Flux Dev (txt2img) — real sand dunes."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from app.services.ai_generator import txt2img_ultra, HERO_BANNER

OUT = "app/static/img/hero-editorial.jpg"

async def main():
    print("→ Generating desert hero via Flux 1.1 Pro Ultra...")
    data = await txt2img_ultra(HERO_BANNER)
    with open(OUT, "wb") as f:
        f.write(data)
    print(f"✓ {OUT} — {len(data)//1024}KB")

asyncio.run(main())
