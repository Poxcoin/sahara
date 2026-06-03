"""
AI image generation via Replicate (Flux Dev).

Two modes:
  img2img  — takes an existing garment photo + prompt → fashion editorial photo
  txt2img  — pure text prompt → hero banner
"""
import asyncio
import base64
import httpx
from pathlib import Path

from app.config import settings

FLUX_MODEL = "black-forest-labs/flux-dev"
FLUX_ULTRA = "black-forest-labs/flux-1.1-pro-ultra"

PROMPT_TEMPLATE = (
    "Ultra-realistic high fashion editorial photograph, model wearing this exact garment, "
    "Sahara desert sand dunes backdrop, golden hour sunlight from camera-left, long "
    "directional shadows on warm sand, model full body, confident pose, composed expression, "
    "professional fashion photography on Phase One medium format camera, 85mm lens, "
    "shallow depth of field, Vogue editorial style, cinematic color grade, film grain, "
    "no AI artifacts, {extra}"
)

HERO_WOMEN = (
    "Ultra-realistic editorial fashion photograph, female model wearing elegant minimalist "
    "dress in ivory tone, vast open Sahara desert, endless sand dunes, golden hour light "
    "from camera-left, long precise shadow on warm sand matching every fabric fold, "
    "wind gently moving fabric, model gazing at horizon, composed cold expression, "
    "Phase One 150MP medium format, 85mm f/2.8, model sharp dunes blurred, "
    "Celine SS campaign quality, Vogue Paris style, warm desaturated grade, film grain"
)

HERO_MEN = (
    "Ultra-realistic editorial fashion photograph, male model wearing slim tailored linen "
    "trousers and open-collar oversized shirt in stone tone, Sahara desert salt flat and "
    "dunes horizon, golden hour side light from camera-right, long dramatic shadow on sand, "
    "model upright hands in pockets gaze off-camera, stubble, natural skin texture, "
    "full body shot, Phase One 85mm f/2.0, dunes defocused, Loro Piana campaign quality, "
    "Bottega Veneta editorial, cinematic grain, no plastic skin"
)

HERO_BANNER = (
    "RAW photo, hyperrealistic, tack sharp, 8K UHD, shot on Sony A7R V with 85mm f/1.4 lens, "
    "ISO 100, shutter 1/500s, perfect focus on subject, every detail crisp and clear, "
    "female fashion model in elegant ivory flowing maxi dress standing on vast Sahara desert sand dunes, "
    "golden hour warm light from the side, long dramatic shadow on textured sand ripples, "
    "model facing away looking at horizon, hair moving in wind, fabric catching light, "
    "photorealistic skin texture, sharp fabric detail, sand grain visible, "
    "wide cinematic composition, dunes stretching to horizon, clear warm sky, "
    "luxury fashion campaign quality, Vogue Paris editorial, "
    "NOT blurry, NOT soft focus, NOT painterly, NOT illustration, NOT AI looking"
)

PRESETS = {
    "women": ("Жіночий — пустеля (вертикаль)", HERO_WOMEN, "portrait_4_3"),
    "men":   ("Чоловічий — пустеля (вертикаль)", HERO_MEN,   "portrait_4_3"),
    "hero":  ("Головний банер 16:9",              HERO_BANNER, "landscape_16_9"),
}

_SIZE_MAP = {
    "portrait_4_3":   {"width": 768,  "height": 1024},
    "landscape_16_9": {"width": 1344, "height": 768},
    "square_hd":      {"width": 1024, "height": 1024},
}


async def _replicate_wait(payload: dict) -> str:
    """Submit prediction to Replicate with Prefer:wait, return image URL."""
    headers = {
        "Authorization": f"Bearer {settings.replicate_api_token}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"https://api.replicate.com/v1/models/{FLUX_MODEL}/predictions",
            headers=headers,
            json={"input": payload},
        )
        r.raise_for_status()
        data = r.json()

        # If still processing, poll
        if data.get("status") not in ("succeeded", "failed"):
            pred_id = data["id"]
            for _ in range(60):
                await asyncio.sleep(4)
                pr = await client.get(
                    f"https://api.replicate.com/v1/predictions/{pred_id}",
                    headers={"Authorization": f"Bearer {settings.replicate_api_token}"},
                )
                pr.raise_for_status()
                data = pr.json()
                if data["status"] in ("succeeded", "failed", "canceled"):
                    break

        if data.get("status") != "succeeded":
            raise RuntimeError(f"Replicate failed: {data.get('error') or data.get('status')}")

        output = data.get("output")
        if isinstance(output, list):
            return output[0]
        return output


async def img2img(image_path: str, prompt: str, strength: float = 0.80) -> bytes:
    """Take garment photo + prompt → new fashion editorial image bytes."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    url = await _replicate_wait({
        "image": f"data:image/jpeg;base64,{b64}",
        "prompt": prompt,
        "prompt_strength": strength,
        "num_outputs": 1,
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "output_format": "jpg",
    })

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
    return r.content


async def txt2img_ultra(prompt: str) -> bytes:
    """Flux 1.1 Pro Ultra — max sharpness, photorealistic, 4MP."""
    headers = {
        "Authorization": f"Bearer {settings.replicate_api_token}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            f"https://api.replicate.com/v1/models/{FLUX_ULTRA}/predictions",
            headers=headers,
            json={"input": {
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "output_format": "jpg",
                "raw": True,
            }},
        )
        r.raise_for_status()
        data = r.json()

        if data.get("status") not in ("succeeded", "failed"):
            pred_id = data["id"]
            for _ in range(80):
                await asyncio.sleep(4)
                pr = await client.get(
                    f"https://api.replicate.com/v1/predictions/{pred_id}",
                    headers={"Authorization": f"Bearer {settings.replicate_api_token}"},
                )
                pr.raise_for_status()
                data = pr.json()
                if data["status"] in ("succeeded", "failed", "canceled"):
                    break

        if data.get("status") != "succeeded":
            raise RuntimeError(f"Ultra failed: {data.get('error') or data.get('status')}")

        url = data.get("output")
        if isinstance(url, list):
            url = url[0]

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
    return r.content


async def txt2img(prompt: str, image_size: str = "landscape_16_9") -> bytes:
    """Pure text → image for hero banners."""
    dims = _SIZE_MAP.get(image_size, _SIZE_MAP["landscape_16_9"])
    url = await _replicate_wait({
        "prompt": prompt,
        "num_outputs": 1,
        "num_inference_steps": 50,
        "guidance_scale": 7.5,
        "output_format": "jpg",
        "output_quality": 100,
        **dims,
    })

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
    return r.content
