"""
Тест двох підходів для заміни фону:
A) rembg (вирізаємо) + Flux Schnell (генеруємо фон) + composite
B) Flux Fill Pro (inpainting з маскою фону)
"""
import asyncio
import io
import os
import time

import httpx
import replicate
from PIL import Image
from rembg import remove

os.environ["REPLICATE_API_TOKEN"] = "r8_9DecGOUmuDWJqmNS11Ql8e0XlBwgQhq2ChhZe"

TEST_IMAGE = "media/originals/106.jpg"
OUTPUT_A = "media/test_A_rembg.jpg"
OUTPUT_B = "media/test_B_fluxfill.jpg"

BG_PROMPT = (
    "luxury minimalist fashion editorial background, warm marble walls, "
    "beige sand tones, large floor-to-ceiling windows, soft natural diffused light, "
    "elegant empty room, no people, 4k"
)


def alpha_to_mask(alpha_channel: Image.Image) -> Image.Image:
    """Конвертує alpha: прозорий піксель (фон) → білий, непрозорий (людина) → чорний."""
    lut = [255 if i < 128 else 0 for i in range(256)]
    return alpha_channel.point(lut)


# ── Test A: rembg + Flux Schnell background ──────────────────────────────────

async def test_rembg():
    print("\n=== Test A: rembg + Flux Schnell фон ===")
    t = time.time()

    with open(TEST_IMAGE, "rb") as f:
        raw = f.read()

    person_rgba = Image.open(io.BytesIO(remove(raw))).convert("RGBA")
    orig_w, orig_h = person_rgba.size
    print(f"Вирізано людину: {orig_w}x{orig_h}")

    print("Генеруємо фон через Flux Schnell...")
    bg_out = replicate.run(
        "black-forest-labs/flux-schnell",
        input={
            "prompt": BG_PROMPT,
            "aspect_ratio": "3:4",
            "output_format": "jpg",
            "num_outputs": 1,
        },
    )
    bg_url = str(bg_out[0]) if isinstance(bg_out, list) else str(bg_out)

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(bg_url)

    bg = Image.open(io.BytesIO(r.content)).convert("RGBA").resize(
        (orig_w, orig_h), Image.LANCZOS
    )
    bg.paste(person_rgba, (0, 0), person_rgba)
    bg.convert("RGB").save(OUTPUT_A, quality=95)
    print(f"Збережено: {OUTPUT_A}  ({time.time()-t:.1f}s)")


# ── Test B: Flux Fill Pro inpainting ─────────────────────────────────────────

async def test_flux_fill():
    print("\n=== Test B: Flux Fill Pro inpainting ===")
    t = time.time()

    with open(TEST_IMAGE, "rb") as f:
        raw = f.read()

    person_rgba = Image.open(io.BytesIO(remove(raw))).convert("RGBA")
    mask = alpha_to_mask(person_rgba.split()[3])

    img_buf = io.BytesIO()
    Image.open(TEST_IMAGE).save(img_buf, format="JPEG")
    img_buf.seek(0)

    mask_buf = io.BytesIO()
    mask.save(mask_buf, format="PNG")
    mask_buf.seek(0)

    print("Запускаємо Flux Fill Pro...")
    out = replicate.run(
        "black-forest-labs/flux-fill-pro",
        input={
            "image": img_buf,
            "mask": mask_buf,
            "prompt": BG_PROMPT,
            "output_quality": 95,
            "safety_tolerance": 3,
        },
    )
    url = str(out)

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(url)

    with open(OUTPUT_B, "wb") as f:
        f.write(r.content)
    print(f"Збережено: {OUTPUT_B}  ({time.time()-t:.1f}s)")


async def main():
    await test_rembg()
    await test_flux_fill()
    print("\nГотово! Відкрий:")
    print(f"  {OUTPUT_A}")
    print(f"  {OUTPUT_B}")

asyncio.run(main())
