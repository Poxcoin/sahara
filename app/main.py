"""
Головний FastAPI-додаток.

Маршрути:
    /                  — публічний каталог (live товари)
    /product/{id}      — сторінка товару
    /admin             — адмінка (потрібен пароль)
    /admin/generate/{id} — запустити try-on для товару
    /admin/publish/{id}  — опублікувати готовий товар
    /admin/reject/{id}   — відхилити
    /media/...         — статика (фото)
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
import secrets

from fastapi import FastAPI, Request, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import init_db, get_session, async_session
from app.models import Product, ProductStatus
from app.services.tryon import run_tryon, detect_category


# Replicate token у env
os.environ["REPLICATE_API_TOKEN"] = settings.replicate_api_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    Path(settings.media_dir).mkdir(exist_ok=True)
    Path(settings.media_dir, "originals").mkdir(exist_ok=True)
    Path(settings.media_dir, "generated").mkdir(exist_ok=True)
    Path(settings.media_dir, "models").mkdir(exist_ok=True)
    yield


app = FastAPI(title="SAHARA", lifespan=lifespan)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct = secrets.compare_digest(credentials.password, settings.admin_password)
    if not correct or credentials.username != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ==================== ПУБЛІЧНА ЧАСТИНА ====================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Product)
        .where(Product.status == ProductStatus.LIVE)
        .order_by(desc(Product.updated_at))
    )
    products = result.scalars().all()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "products": products, "site_name": settings.site_name},
    )


@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(
    product_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    product = await session.get(Product, product_id)
    if not product or product.status != ProductStatus.LIVE:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "product.html",
        {"request": request, "product": product, "site_name": settings.site_name},
    )


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(
        "about.html", {"request": request, "site_name": settings.site_name}
    )


@app.get("/contacts", response_class=HTMLResponse)
async def contacts_page(request: Request):
    return templates.TemplateResponse(
        "contacts.html", {"request": request, "site_name": settings.site_name}
    )


@app.get("/support", response_class=HTMLResponse)
async def support_page(request: Request):
    return templates.TemplateResponse(
        "support.html",
        {"request": request, "site_name": settings.site_name, "sent": False},
    )


@app.post("/support", response_class=HTMLResponse)
async def support_submit(request: Request):
    # TODO: відправка email або збереження в БД
    return templates.TemplateResponse(
        "support.html",
        {"request": request, "site_name": settings.site_name, "sent": True},
    )


@app.get("/catalog", response_class=HTMLResponse)
async def catalog_page(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Product)
        .where(Product.status == ProductStatus.LIVE)
        .order_by(desc(Product.updated_at))
    )
    products = result.scalars().all()
    return templates.TemplateResponse(
        "catalog.html",
        {"request": request, "products": products, "site_name": settings.site_name,
         "category_name": "Усі товари"},
    )


@app.get("/cart", response_class=HTMLResponse)
async def cart_page(request: Request):
    return templates.TemplateResponse(
        "cart.html", {"request": request, "site_name": settings.site_name}
    )


@app.get("/wishlist", response_class=HTMLResponse)
async def wishlist_page(request: Request):
    return templates.TemplateResponse(
        "wishlist.html", {"request": request, "site_name": settings.site_name}
    )


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return templates.TemplateResponse(
        "profile.html", {"request": request, "site_name": settings.site_name}
    )


# ==================== АДМІНКА ====================

@app.get("/admin", response_class=HTMLResponse)
async def admin(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Product).order_by(desc(Product.created_at)))
    products = result.scalars().all()

    grouped = {s.value: [] for s in ProductStatus}
    for p in products:
        grouped[p.status.value].append(p)

    return templates.TemplateResponse(
        "admin.html", {"request": request, "grouped": grouped}
    )


async def _generate_task(product_id: int):
    """Background task: запустити try-on і оновити статус."""
    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            return

        product.status = ProductStatus.GENERATING
        await session.commit()

        try:
            category = detect_category(product.title, product.description)
            garment_path = f"{settings.media_dir}/{product.original_photo}"
            output_path = f"{settings.media_dir}/generated/{product.id}.jpg"

            await run_tryon(garment_path, output_path, category=category, product_id=product.id)

            product.generated_photo = f"generated/{product.id}.jpg"
            product.status = ProductStatus.READY
            product.error_message = None
        except Exception as e:
            product.status = ProductStatus.FAILED
            product.error_message = str(e)
        await session.commit()


@app.post("/admin/generate/{product_id}")
async def admin_generate(
    product_id: int,
    background: BackgroundTasks,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    product.status = ProductStatus.APPROVED
    await session.commit()
    background.add_task(_generate_task, product_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/publish/{product_id}")
async def admin_publish(
    product_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product or product.status != ProductStatus.READY:
        raise HTTPException(400, "Product not ready")
    product.status = ProductStatus.LIVE
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/publish-direct/{product_id}")
async def admin_publish_direct(
    product_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Публікує одразу з оригінальним фото, без AI генерації."""
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    product.status = ProductStatus.LIVE
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reject/{product_id}")
async def admin_reject(
    product_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    product.status = ProductStatus.REJECTED
    await session.commit()
    return RedirectResponse("/admin", status_code=303)
