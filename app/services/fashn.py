"""
Fashn.ai API service.

product-to-model: garment photo only → AI generates model wearing it
tryon-v1.6:       garment + model photo → model wearing garment
"""
import asyncio
import base64
import httpx
from pathlib import Path

BASE = "https://api.fashn.ai/v1"


def _b64(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    # Detect actual format by magic bytes
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "webp"
    elif data[:3] == b"\xff\xd8\xff":
        mime = "jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "png"
    else:
        ext = Path(path).suffix.lower().replace(".", "") or "jpeg"
        mime = "jpeg" if ext == "jpg" else ext
    return f"data:image/{mime};base64,{base64.b64encode(data).decode()}"


async def _submit(key: str, model_name: str, inputs: dict) -> str:
    """Submit job, return prediction id."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{BASE}/run",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model_name": model_name, "inputs": inputs},
        )
        r.raise_for_status()
        return r.json()["id"]


async def _poll(key: str, pred_id: str, max_wait: int = 180) -> str:
    """Poll until done, return output image URL."""
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=30) as c:
        for _ in range(max_wait // 3):
            await asyncio.sleep(3)
            r = await c.get(f"{BASE}/status/{pred_id}", headers=headers)
            r.raise_for_status()
            data = r.json()
            st = data.get("status")
            if st == "completed":
                output = data.get("output")
                if isinstance(output, list):
                    return output[0]
                return output
            if st in ("failed", "error", "cancelled"):
                raise RuntimeError(f"Fashn.ai job failed: {data.get('error') or st}")
    raise RuntimeError("Fashn.ai timeout")


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def product_to_model(
    garment_path: str,
    key: str,
    category: str = "tops",
) -> bytes:
    """
    Garment photo only → AI model wearing it.
    category: tops / bottoms / one-pieces
    """
    cat_map = {
        "dress": "one-pieces", "outerwear": "tops",
        "knitwear": "tops", "sweatshirt": "tops",
        "blouse": "tops", "tshirt": "tops", "top": "tops",
        "sport": "tops", "pants": "bottoms", "skirt": "bottoms",
        "shorts": "bottoms", "sport-pants": "bottoms",
    }
    fashn_cat = cat_map.get(category, "tops")

    inputs = {
        "product_image": _b64(garment_path),
        "category": fashn_cat,
    }
    pred_id = await _submit(key, "product-to-model", inputs)
    url = await _poll(key, pred_id)
    return await _download(url)


async def tryon(
    garment_path: str,
    model_path: str,
    key: str,
    category: str = "tops",
) -> bytes:
    """Garment + model photo → model wearing garment (tryon-v1.6)."""
    cat_map = {
        "dress": "one-pieces",
        "pants": "bottoms", "skirt": "bottoms",
        "shorts": "bottoms", "sport-pants": "bottoms",
    }
    fashn_cat = cat_map.get(category, "tops")

    inputs = {
        "model_image": _b64(model_path),
        "garment_image": _b64(garment_path),
        "category": fashn_cat,
    }
    pred_id = await _submit(key, "tryon-v1.6", inputs)
    url = await _poll(key, pred_id)
    return await _download(url)
