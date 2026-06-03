"""Debug Fashn.ai API - try different input formats."""
import asyncio
import base64
import httpx

KEY = "fa-DptlWuPkbR3P-WEBoj20nqF7kFuNOqyLBZgdD"
BASE = "https://api.fashn.ai/v1"
GARMENT = "media/koton_originals/6SAK80003UW.jpg"


def _b64(path):
    with open(path, "rb") as f:
        data = f.read()
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"


async def try_run(payload, label):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{BASE}/run",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json=payload,
        )
        print(f"\n[{label}] status={r.status_code}: {r.text[:300]}")


async def main():
    b64 = _b64(GARMENT)

    # Try 1: no category
    await try_run({
        "model_name": "product-to-model",
        "inputs": {"product_image": b64}
    }, "no category")

    # Try 2: garment_class instead of category
    await try_run({
        "model_name": "product-to-model",
        "inputs": {"product_image": b64, "garment_class": "one-pieces"}
    }, "garment_class")

    # Try 3: clothing_type
    await try_run({
        "model_name": "product-to-model",
        "inputs": {"product_image": b64, "clothing_type": "dress"}
    }, "clothing_type")

    # Try 4: check available models
    async with httpx.AsyncClient(timeout=30) as c:
        for endpoint in ["/models", "/v1/models", ""]:
            r = await c.get(f"https://api.fashn.ai{endpoint}", headers={"Authorization": f"Bearer {KEY}"})
            if r.status_code == 200:
                print(f"\n{endpoint}: {r.text[:500]}")
                break

asyncio.run(main())
