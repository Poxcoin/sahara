"""Import downloaded Koton TG photos into the DB."""
import asyncio
import shutil
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.db import init_db, async_session
from app.models import Product, ProductStatus

PHOTOS = sorted(Path("/tmp").glob("tg_koton_*.jpg"))

TITLES = [
    "Жіноча блуза Koton", "Жіноче плаття Koton", "Жіночий топ Koton",
    "Жіноча сукня Koton", "Жіноча футболка Koton", "Жіночий костюм Koton",
    "Жіночий жакет Koton", "Жіночі штани Koton", "Жіноча спідниця Koton",
    "Жіночий кардиган Koton", "Жіноча блузка Koton", "Жіночий светр Koton",
    "Жіночий комбінезон Koton", "Жіноча туніка Koton", "Жіночий джемпер Koton",
    "Жіноча майка Koton", "Жіночий піджак Koton", "Жіночий бомбер Koton",
    "Жіноча сорочка Koton", "Жіноча сукня міді Koton", "Жіночий лонгслів Koton",
    "Жіночий топ з вирізом Koton", "Жіноча блуза з оборками Koton",
    "Жіночий кроп-топ Koton", "Жіноче плаття-сорочка Koton",
    "Жіноча блуза oversize Koton", "Жіноча сукня з поясом Koton",
    "Жіночий топ без рукавів Koton", "Жіноча блуза з принтом Koton",
    "Жіноча сукня з драпіруванням Koton",
]


async def main():
    await init_db()
    originals = Path(settings.media_dir) / "originals"
    originals.mkdir(parents=True, exist_ok=True)

    imported = 0
    async with async_session() as sess:
        for i, src in enumerate(PHOTOS):
            dest_name = f"koton_{src.stem.replace('tg_koton_', '')}.jpg"
            dest = originals / dest_name
            shutil.copy2(src, dest)

            title = TITLES[i] if i < len(TITLES) else f"Одяг Koton #{i+1}"
            p = Product(
                title=title,
                title_ua=title,
                description="Koton — турецький бренд одягу",
                original_photo=f"originals/{dest_name}",
                status=ProductStatus.PENDING,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            sess.add(p)
            imported += 1
            print(f"  + {dest_name} → {title}")

        await sess.commit()

    print(f"\nДодано {imported} товарів.")


asyncio.run(main())
