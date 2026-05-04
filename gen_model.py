import replicate, httpx, os
from dotenv import load_dotenv
load_dotenv()

print("Генерую reference модель...")
output = replicate.run(
    "black-forest-labs/flux-schnell",
    input={
        "prompt": "elegant fashion model, full body shot, neutral pose facing camera, plain white tank top and beige trousers, minimalist studio, warm beige background, soft natural light from the side, COS Zara premium aesthetic, photorealistic, sharp focus, 4k editorial fashion photography",
        "width": 768,
        "height": 1024,
        "num_outputs": 1,
    }
)
url = str(list(output)[0])
print(f"URL: {url}")
print("Завантажую...")
os.makedirs("media/models", exist_ok=True)
r = httpx.get(url, timeout=60)
with open("media/models/sahara_woman_1.jpg", "wb") as f:
    f.write(r.content)
print("Готово: media/models/sahara_woman_1.jpg")
