"""
FAL.ai image generation service (Flux Dev model).
"""
import os
import httpx
from pathlib import Path

FLUX_MODEL = "fal-ai/flux/dev"

PROMPT_WOMEN = (
    "Ultra-realistic editorial fashion photograph, female model wearing elegant minimalist "
    "dress in ivory or sand tone, standing in vast open Sahara desert landscape, endless "
    "rolling sand dunes background, golden hour sunlight from camera-left at 30 degrees, "
    "long precise directional shadow cast on warm sand following light angle exactly, "
    "shadow detail matches every garment fold, wind slightly catching fabric hem, model "
    "posture confident and still, gaze toward horizon off-camera, expression composed and "
    "cold, skin luminous with natural sun warmth, hair loose natural movement, full-body "
    "vertical composition, extreme photorealism, shot on Phase One XF IQ4 150MP, 85mm "
    "portrait lens, f/2.8, shallow depth of field — model sharp, dunes softly blurred, "
    "color grade: warm golden shadows, editorial desaturation, style of Celine SS campaign, "
    "Vogue Paris, ZARA lookbook 2024, no digital artifacts, grain texture from film scan"
)

PROMPT_MEN = (
    "Ultra-realistic editorial fashion photograph, male model wearing slim tailored linen "
    "trousers and open-collar oversized shirt in off-white or stone, standing on cracked "
    "desert salt flat merging into sand dunes horizon, Sahara desert, golden hour side "
    "lighting from camera-right, long dramatic shadow stretching left across sand surface, "
    "shadow geometry matches model silhouette and clothing wrinkles precisely, model posture "
    "upright, hands in pockets, gaze slightly downward or off-camera, expression neutral and "
    "confident, stubble, natural skin texture with sun warmth, full body vertical shot, "
    "extreme photorealism, Phase One medium format aesthetic, 85mm f/2.0, background dunes "
    "beautifully defocused, color palette: warm amber sand, muted stone clothing tones, "
    "Loro Piana campaign quality, cinematic grain, no plastic AI skin"
)

PROMPT_HERO = (
    "Ultra-realistic high fashion editorial photograph, female model standing in Sahara "
    "desert at golden hour, wide sand dunes stretching to horizon, cinematic landscape "
    "composition, wearing minimalist luxury fashion in neutral sand-ivory tones — flowing "
    "midi dress, single strong light source from camera-left at low 25-degree angle creating "
    "long unified shadows across sand that perfectly match figure and every fabric fold, "
    "photorealistic skin with sun warmth and texture, model gazing away from camera, "
    "tense composed editorial energy, Phase One 150MP aesthetic, 50mm f/2.8, vast desert "
    "depth of field gradient, color grade warm-desaturated like Bottega Veneta FW campaign, "
    "Vogue cover composition, no AI artifacts, cinematic film grain"
)

PRESETS = {
    "women": ("Жіночий — пустеля (вертикаль)", PROMPT_WOMEN, "portrait_4_3"),
    "men":   ("Чоловічий — пустеля (вертикаль)", PROMPT_MEN,   "portrait_4_3"),
    "hero":  ("Головний банер (горизонталь)",     PROMPT_HERO,  "landscape_16_9"),
}


async def generate_image(prompt: str, image_size: str, fal_key: str) -> bytes:
    """Call FAL.ai Flux Dev and return raw image bytes."""
    headers = {
        "Authorization": f"Key {fal_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "image_size": image_size,
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "num_images": 1,
        "enable_safety_checker": False,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        # Submit job
        r = await client.post(
            f"https://queue.fal.run/{FLUX_MODEL}",
            headers=headers,
            json=payload,
        )
        r.raise_for_status()
        job = r.json()
        request_id = job["request_id"]

        # Poll until done
        import asyncio
        for _ in range(120):
            await asyncio.sleep(3)
            status_r = await client.get(
                f"https://queue.fal.run/{FLUX_MODEL}/requests/{request_id}/status",
                headers=headers,
            )
            status_r.raise_for_status()
            st = status_r.json()
            if st.get("status") == "COMPLETED":
                break
            if st.get("status") in ("FAILED", "ERROR"):
                raise RuntimeError(f"FAL job failed: {st}")

        # Get result
        result_r = await client.get(
            f"https://queue.fal.run/{FLUX_MODEL}/requests/{request_id}",
            headers=headers,
        )
        result_r.raise_for_status()
        result = result_r.json()

        image_url = result["images"][0]["url"]
        img_r = await client.get(image_url)
        img_r.raise_for_status()
        return img_r.content
