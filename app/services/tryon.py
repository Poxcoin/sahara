import asyncio
import time
from pathlib import Path

import httpx
import replicate

from app.config import settings

MODEL_PHOTO = str(Path(__file__).parents[2] / "media" / "models" / "sahara_woman_1.jpg")


def _idm_vton(model_path: str, garment_path: str, garment_desc: str, category: str) -> str:
    for attempt in range(4):
        try:
            with open(model_path, "rb") as model_f, open(garment_path, "rb") as garm_f:
                out = replicate.run(
                    "cuuupid/idm-vton",
                    input={
                        "human_img": model_f,
                        "garm_img": garm_f,
                        "garment_des": garment_desc,
                        "category": category,
                        "is_checked": True,
                        "is_checked_crop": False,
                        "denoise_steps": 30,
                        "seed": 42,
                    },
                )
            # повертає список з двох зображень — беремо перше (результат try-on)
            urls = list(out)
            return str(urls[0])
        except Exception as e:
            if "429" in str(e) and attempt < 3:
                wait = 25 * (attempt + 1)
                print(f"[rate limit] чекаю {wait}s...")
                time.sleep(wait)
            else:
                raise


async def run_tryon(
    garment_path: str,
    output_path: str,
    model_photo: str = None,
    category: str = "upper_body",
    product_id: int = 0,
) -> str:
    if not Path(garment_path).exists():
        raise FileNotFoundError(f"Photo not found: {garment_path}")

    model_path = model_photo or MODEL_PHOTO
    if not Path(model_path).exists():
        raise FileNotFoundError(f"Model photo not found: {model_path}")

    # назва файлу як підказка для garment_desc
    garment_desc = Path(garment_path).stem

    print(f"[tryon] IDM-VTON: category={category}, garment={garment_path}")
    loop = asyncio.get_event_loop()
    url = await loop.run_in_executor(
        None, _idm_vton, model_path, garment_path, garment_desc, category
    )

    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.get(url)
        r.raise_for_status()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)

    return output_path


def detect_category(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if any(w in text for w in ["сукня", "плаття", "dress", "сарафан"]):
        return "dresses"
    if any(w in text for w in ["штани", "брюки", "джинси", "спідниця", "шорти", "pants", "skirt"]):
        return "lower_body"
    return "upper_body"
