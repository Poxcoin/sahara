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
import time
import threading
import urllib.parse as _urlparse
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import hmac as _hmac
import httpx

import re as _re
from fastapi import FastAPI, Request, Depends, HTTPException, status, BackgroundTasks, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import init_db, get_session, async_session
from app.models import Product, ProductStatus, User, Order, OrderItem, OrderStatus, Admin, AdminAuditLog
from app.services.tryon import detect_category
from app.services import auth as auth_svc
from app.services.ai_generator import img2img, txt2img, PRESETS, PROMPT_TEMPLATE
from app.services import fashn as fashn_svc
from app.services.notify import send_order_telegram
from app.services.email_service import send_order_confirmation
from fastapi import UploadFile, File, Form
from pydantic import BaseModel
from collections import defaultdict
from datetime import datetime, timedelta


def koton_category(title: str) -> str:
    """Визначає категорію за турецькою назвою товару."""
    t = title.lower()
    if "elbise" in t or "abiye" in t:
        return "dress"
    if any(w in t for w in ["etek", "skirt"]):
        return "skirt"
    if any(w in t for w in ["şort", "short"]):
        return "shorts"
    if any(w in t for w in ["tayt", "eşofman alt", "spor tayt", "biker"]):
        return "sport-pants"
    if any(w in t for w in ["eşofman", "sweatshirt", "hoodie", "kapüşon"]):
        return "sweatshirt"
    if any(w in t for w in ["pantolon", "denim panto", "culotte"]):
        return "pants"
    if any(w in t for w in ["mont", "kaban", "ceket", "blazer", "yelek"]):
        return "outerwear"
    if any(w in t for w in ["triko", "kazak", "hırka", "örgü"]):
        return "knitwear"
    if any(w in t for w in ["tişört", "polo", "tisort"]):
        return "tshirt"
    if any(w in t for w in ["spor", "sporcu", "sütyeni", "atlet"]):
        return "sport"
    if any(w in t for w in ["bluz", "gömlek", "fırfır", "crop"]):
        return "blouse"
    return "top"


CATEGORY_LABELS = {
    "uk": {
        "all":        "Усі товари",
        "dress":      "Сукні та плаття",
        "blouse":     "Блузи та топи",
        "top":        "Топи",
        "tshirt":     "Футболки та поло",
        "pants":      "Штани та джинси",
        "skirt":      "Спідниці",
        "shorts":     "Шорти",
        "sweatshirt": "Світшоти та худі",
        "knitwear":   "Трикотаж та кардигани",
        "outerwear":  "Верхній одяг",
        "sport":      "Спортивний одяг",
        "sport-pants":"Спортивні легінси",
    },
    "en": {
        "all":        "All Items",
        "dress":      "Dresses",
        "blouse":     "Blouses & Tops",
        "top":        "Tops",
        "tshirt":     "T-Shirts & Polo",
        "pants":      "Trousers & Jeans",
        "skirt":      "Skirts",
        "shorts":     "Shorts",
        "sweatshirt": "Sweatshirts & Hoodies",
        "knitwear":   "Knitwear & Cardigans",
        "outerwear":  "Outerwear",
        "sport":      "Sportswear",
        "sport-pants":"Sports Leggings",
    },
}


# Replicate token у env
os.environ["REPLICATE_API_TOKEN"] = settings.replicate_api_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.secret_key == "change_me_secret_key_32_chars_min":
        import sys
        print("[SECURITY] ERROR: SECRET_KEY not configured. Set SAHARA_SECRET_KEY in .env", file=sys.stderr)
        sys.exit(1)
    await init_db()
    Path(settings.media_dir).mkdir(exist_ok=True)
    Path(settings.media_dir, "originals").mkdir(exist_ok=True)
    Path(settings.media_dir, "generated").mkdir(exist_ok=True)
    Path(settings.media_dir, "models").mkdir(exist_ok=True)
    yield


app = FastAPI(title="SAHARA", lifespan=lifespan)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            client_ip = request.client.host if request.client else "unknown"
            now = datetime.utcnow()
            cutoff = now - timedelta(minutes=1)
            self.requests[client_ip] = [t for t in self.requests[client_ip] if t > cutoff]

            if len(self.requests[client_ip]) >= self.requests_per_minute:
                return HTMLResponse("Rate limit exceeded", status_code=429)
            self.requests[client_ip].append(now)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response


app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/1c", StaticFiles(directory="1c"), name="1c")

import json as _json
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["koton_category"] = koton_category
templates.env.globals["CATEGORY_LABELS"] = CATEGORY_LABELS
templates.env.filters["fromjson"] = lambda s: _json.loads(s) if s else []
templates.env.globals["csrf_token"] = lambda req: auth_svc.get_csrf_token(req)


def get_product_title(product, lang: str) -> str:
    """Return the localized product title, falling back to the Turkish original."""
    if lang == "en" and getattr(product, "title_en", None):
        return product.title_en
    if lang == "uk" and getattr(product, "title_ua", None):
        return product.title_ua
    return product.title


templates.env.globals["get_product_title"] = get_product_title


def get_lang(request: Request) -> str:
    lang = request.cookies.get("lang", "uk")
    return lang if lang in ("uk", "en") else "uk"


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    user_id = auth_svc.get_user_id_from_cookie(request)
    if not user_id:
        return None
    return await session.get(User, user_id)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        "404.html",
        {"request": request, "site_name": settings.site_name},
        status_code=404,
    )


security = HTTPBasic(auto_error=False)
# ── Admin Session & Rate Limiting ──
_admin_login_failures: dict[str, list[float]] = defaultdict(list)
_admin_lock = threading.Lock()
_MAX_ADMIN_FAILURES = 5
_ADMIN_WINDOW = 600  # 10 minutes
_ADMIN_LOCKOUT = 900  # 15 minutes


async def get_current_admin(request: Request, session: AsyncSession = Depends(get_session)) -> Admin:
    """Verify admin session and return Admin object."""
    admin_id = auth_svc.get_admin_id_from_cookie(request)
    if not admin_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})

    admin = await session.get(Admin, admin_id)
    if not admin:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})

    return admin


def _check_admin_rate_limit(ip: str) -> None:
    """Check if IP is rate-limited for admin login."""
    now = time.time()
    with _admin_lock:
        timestamps = _admin_login_failures[ip]
        timestamps[:] = [t for t in timestamps if now - t < _ADMIN_WINDOW]
        if len(timestamps) >= _MAX_ADMIN_FAILURES:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")


def _record_admin_failure(ip: str) -> None:
    """Record failed admin login attempt."""
    with _admin_lock:
        _admin_login_failures[ip].append(time.time())


def _clear_admin_failures(ip: str) -> None:
    """Clear failed login attempts for IP."""
    with _admin_lock:
        _admin_login_failures.pop(ip, None)


async def _log_admin_action(
    session: AsyncSession, admin_id: int | None, action: str, ip: str,
    user_agent: str | None = None, success: bool = False, error_msg: str | None = None
) -> None:
    """Log admin action to AuditLog."""
    log = AdminAuditLog(
        admin_id=admin_id,
        action=action,
        ip_address=ip,
        user_agent=user_agent,
        success=success,
        error_message=error_msg
    )
    session.add(log)
    await session.commit()


# ==================== ADMIN LOGIN ====================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: str = ""):
    if _verify_admin_cookie(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": error, "site_name": settings.site_name})


@app.post("/admin/login")
async def admin_login_post(request: Request, response: Response):
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    u_ok = secrets.compare_digest(username.encode(), b"admin")
    p_ok = secrets.compare_digest(password.encode(), settings.admin_password.encode())
    if u_ok and p_ok:
        _clear_failures(client_ip)
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie(_ADMIN_COOKIE, _make_admin_token(), httponly=True, samesite="lax", max_age=60*60, secure=True)
        return resp

    _record_failure(client_ip)
    return RedirectResponse("/admin/login?error=1", status_code=303)


@app.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(_ADMIN_COOKIE)
    return resp


# ==================== ПУБЛІЧНА ЧАСТИНА ====================

@app.get("/set-lang")
async def set_lang(lang: str, ref: str = "/"):
    if not ref.startswith("/") or ref.startswith("//"):
        ref = "/"
    resp = RedirectResponse(ref, status_code=303)
    if lang in ("uk", "en"):
        resp.set_cookie("lang", lang, max_age=60*60*24*365, secure=True, httponly=True, samesite="lax")
    return resp


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_session)):
    lang = get_lang(request)
    result = await session.execute(
        select(Product).where(Product.status == ProductStatus.LIVE).order_by(desc(Product.updated_at))
    )
    products = result.scalars().all()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "products": products, "site_name": settings.site_name, "lang": lang},
    )


@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(
    product_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lang = get_lang(request)
    product = await session.get(Product, product_id)
    if not product or product.status != ProductStatus.LIVE:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "product.html",
        {"request": request, "product": product, "site_name": settings.site_name, "lang": lang},
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


@app.get("/legal", response_class=HTMLResponse)
async def legal_page(request: Request):
    return templates.TemplateResponse(
        "legal.html", {"request": request, "site_name": settings.site_name}
    )


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt():
    base = settings.base_url.rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /tryon/generate\n"
        "Disallow: /media/tryon_uploads/\n"
        "Disallow: /media/tryon_results/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    from fastapi.responses import Response as _Resp
    base = settings.base_url.rstrip("/")

    static_pages = [
        ("", "1.0", "weekly"),
        ("/catalog", "0.9", "daily"),
        ("/tryon", "0.8", "weekly"),
        ("/legal", "0.3", "monthly"),
    ]

    async with async_session() as session:
        result = await session.execute(
            select(Product.id, Product.updated_at)
            .where(Product.status.in_([ProductStatus.READY, ProductStatus.LIVE]))
            .order_by(desc(Product.updated_at))
        )
        products = result.all()

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    for path, priority, freq in static_pages:
        lines.append(
            f"  <url><loc>{base}{path}</loc>"
            f"<changefreq>{freq}</changefreq>"
            f"<priority>{priority}</priority></url>"
        )

    for prod_id, updated_at in products:
        lastmod = updated_at.strftime("%Y-%m-%d") if updated_at else ""
        lines.append(
            f"  <url><loc>{base}/product/{prod_id}</loc>"
            + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "")
            + "<changefreq>weekly</changefreq><priority>0.7</priority></url>"
        )

    lines.append("</urlset>")
    return _Resp("\n".join(lines), media_type="application/xml")


@app.get("/support", response_class=HTMLResponse)
async def support_page(request: Request):
    return templates.TemplateResponse(
        "support.html",
        {"request": request, "site_name": settings.site_name, "sent": False},
    )


@app.post("/support", response_class=HTMLResponse)
async def support_submit(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    name    = str(form.get("name", "")).strip()
    email   = str(form.get("email", "")).strip()
    topic   = str(form.get("topic", "")).strip()
    order   = str(form.get("order", "")).strip()
    message = str(form.get("message", "")).strip()

    async def _notify():
        if not settings.tg_bot_token or not settings.tg_admin_chat_id:
            return
        order_line = f"\n📦 Замовлення: <code>{order}</code>" if order else ""
        text = (
            f"📩 <b>Нове звернення</b>\n\n"
            f"👤 {name}\n"
            f"📧 {email}\n"
            f"🏷 {topic}{order_line}\n\n"
            f"{message}"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as cl:
                await cl.post(
                    f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage",
                    json={"chat_id": settings.tg_admin_chat_id, "text": text, "parse_mode": "HTML"},
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Support notify failed: %s", exc)

    background_tasks.add_task(_notify)
    return templates.TemplateResponse(
        "support.html",
        {"request": request, "site_name": settings.site_name, "sent": True},
    )


@app.get("/api/search")
async def api_search(q: str = "", session: AsyncSession = Depends(get_session)):
    from sqlalchemy import or_, func
    q = q.strip()
    if not q or len(q) < 2:
        return {"results": []}
    pattern = f"%{q}%"
    result = await session.execute(
        select(Product)
        .where(Product.status == ProductStatus.LIVE)
        .where(or_(
            Product.title.ilike(pattern),
            Product.title_ua.ilike(pattern),
            Product.description.ilike(pattern),
        ))
        .order_by(desc(Product.updated_at))
        .limit(8)
    )
    products = result.scalars().all()
    return {"results": [
        {
            "id": p.id,
            "title": p.title_ua or p.title,
            "price": p.price_uah,
            "photo": p.generated_photo or p.original_photo,
        }
        for p in products
    ]}


@app.get("/catalog", response_class=HTMLResponse)
async def catalog_page(request: Request, session: AsyncSession = Depends(get_session), cat: str = "", gender: str = ""):
    lang = get_lang(request)
    q = select(Product).where(Product.status == ProductStatus.LIVE)
    if gender in ("men", "women"):
        q = q.where(Product.gender == gender)
    q = q.order_by(desc(Product.updated_at))
    result = await session.execute(q)
    products = result.scalars().all()
    labels = CATEGORY_LABELS.get(lang, CATEGORY_LABELS["uk"])
    return templates.TemplateResponse(
        "catalog.html",
        {"request": request, "products": products, "site_name": settings.site_name,
         "category_name": labels.get(cat, labels["all"]), "active_cat": cat,
         "active_gender": gender, "lang": lang, "cat_labels": labels},
    )


@app.get("/api/np/cities")
async def np_cities(q: str = ""):
    if not settings.np_api_key or len(q) < 2:
        return {"data": []}
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post("https://api.novaposhta.ua/v2.0/json/", json={
            "apiKey": settings.np_api_key,
            "modelName": "Address",
            "calledMethod": "searchSettlements",
            "methodProperties": {"CityName": q, "Limit": "10"},
        })
        data = r.json()
    addresses = data.get("data", [{}])[0].get("Addresses", []) if data.get("success") else []
    return {"data": [{"name": a["Present"], "ref": a["DeliveryCity"]} for a in addresses]}


@app.get("/api/np/warehouses")
async def np_warehouses(city_ref: str = "", q: str = ""):
    if not settings.np_api_key or not city_ref:
        return {"data": []}
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post("https://api.novaposhta.ua/v2.0/json/", json={
            "apiKey": settings.np_api_key,
            "modelName": "AddressGeneral",
            "calledMethod": "getWarehouses",
            "methodProperties": {"CityRef": city_ref, "FindByString": q, "Limit": "30"},
        })
        data = r.json()
    warehouses = data.get("data", []) if data.get("success") else []
    return {"data": [{"name": w["Description"], "number": w["Number"]} for w in warehouses]}


@app.get("/checkout", response_class=HTMLResponse)
async def checkout_page(request: Request):
    return templates.TemplateResponse(
        "checkout.html", {"request": request, "site_name": settings.site_name}
    )


class _OrderItemIn(BaseModel):
    product_id: int | None = None
    title: str
    size: str | None = None
    price: float
    qty: int = 1


class _OrderIn(BaseModel):
    name: str
    phone: str
    email: str
    delivery_type: str
    city: str | None = None
    np_branch: str | None = None
    items: list[_OrderItemIn]


@app.post("/api/orders/create")
async def create_order(
    data: _OrderIn,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    if not data.items:
        raise HTTPException(400, "Кошик порожній")
    if data.delivery_type not in ("nova_poshta", "pickup"):
        raise HTTPException(400, "Невірний тип доставки")
    if data.delivery_type == "nova_poshta" and (not data.city or not data.np_branch):
        raise HTTPException(400, "Вкажіть місто і відділення")

    total = sum(it.price * it.qty for it in data.items)
    order = Order(
        name=data.name, phone=data.phone, email=data.email,
        delivery_type=data.delivery_type, city=data.city, np_branch=data.np_branch,
        total_uah=total,
    )
    session.add(order)
    await session.flush()

    db_items = []
    for it in data.items:
        oi = OrderItem(
            order_id=order.id,
            product_id=it.product_id,
            product_title=it.title,
            size=it.size,
            price_uah=it.price,
            qty=it.qty,
        )
        session.add(oi)
        db_items.append(oi)

    await session.commit()

    async def _notify():
        import asyncio
        await asyncio.gather(
            send_order_telegram(order, db_items),
            send_order_confirmation(data.email, order, db_items),
            return_exceptions=True,
        )

    background_tasks.add_task(_notify)

    return {"order_id": order.id}


@app.get("/order/done/{order_id}", response_class=HTMLResponse)
async def order_done_page(
    order_id: int, request: Request, user: User | None = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    if not user or order.email != user.email:
        raise HTTPException(403, "Unauthorized to view this order")
    return templates.TemplateResponse(
        "order_done.html",
        {"request": request, "order": order, "site_name": settings.site_name},
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
async def profile_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not user:
        return RedirectResponse("/login", status_code=303)

    orders_result = await session.execute(
        select(Order).where(Order.email == user.email).order_by(desc(Order.created_at))
    )
    orders = orders_result.scalars().all()

    if orders:
        order_ids = [o.id for o in orders]
        items_result = await session.execute(
            select(OrderItem).where(OrderItem.order_id.in_(order_ids))
        )
        items_by_order: dict[int, list] = {}
        for it in items_result.scalars().all():
            items_by_order.setdefault(it.order_id, []).append(it)
        for o in orders:
            o.items = items_by_order.get(o.id, [])

    resp = templates.TemplateResponse(
        "profile.html", {
            "request": request,
            "site_name": settings.site_name,
            "user": user,
            "orders": orders,
        }
    )
    auth_svc.ensure_csrf_cookie(resp, request)
    return resp


from app.services import otp as otp_svc
from app.services import email_service as email_svc


# ==================== AUTH ====================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/profile", status_code=303)
    resp = templates.TemplateResponse(
        "login.html", {"request": request, "site_name": settings.site_name, "error": None}
    )
    auth_svc.ensure_csrf_cookie(resp, request)
    return resp


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, session: AsyncSession = Depends(get_session)):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not auth_svc.verify_password(password, user.password_hash):
        _record_failure(client_ip)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "site_name": settings.site_name, "error": "Невірний email або пароль"},
        )

    _clear_failures(client_ip)
    code = await otp_svc.create_otp(session, email, "login")
    try:
        await email_svc.send_otp(email, code, "login")
    except Exception:
        pass  # fallback to console already handled in send_otp

    response = RedirectResponse("/verify", status_code=303)
    auth_svc.set_pending_cookie(response, email, "login")
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/profile", status_code=303)
    resp = templates.TemplateResponse(
        "register.html", {"request": request, "site_name": settings.site_name, "error": None}
    )
    auth_svc.ensure_csrf_cookie(resp, request)
    return resp


@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request, session: AsyncSession = Depends(get_session)):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    name = str(form.get("name", "")).strip()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))

    if not name or not email or not password:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "site_name": settings.site_name, "error": "Заповніть всі поля"},
        )
    if len(password) < 6:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "site_name": settings.site_name, "error": "Пароль — мінімум 6 символів"},
        )

    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "site_name": settings.site_name, "error": "Цей email вже зареєстровано"},
        )

    user = User(name=name, email=email, password_hash=auth_svc.hash_password(password), is_verified=False)
    session.add(user)
    await session.commit()

    code = await otp_svc.create_otp(session, email, "verify")
    try:
        await email_svc.send_otp(email, code, "verify")
    except Exception:
        pass

    response = RedirectResponse("/verify", status_code=303)
    auth_svc.set_pending_cookie(response, email, "verify")
    return response


@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request):
    pending = auth_svc.get_pending(request)
    if not pending:
        return RedirectResponse("/login", status_code=303)
    purpose = pending.get("p", "verify")
    email = pending.get("e", "")
    masked = email[:2] + "***@" + email.split("@")[-1] if "@" in email else email
    resp = templates.TemplateResponse(
        "verify_otp.html",
        {"request": request, "site_name": settings.site_name,
         "purpose": purpose, "masked_email": masked, "error": None},
    )
    auth_svc.ensure_csrf_cookie(resp, request)
    return resp


@app.post("/verify", response_class=HTMLResponse)
async def verify_submit(request: Request, session: AsyncSession = Depends(get_session)):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    pending = auth_svc.get_pending(request)
    if not pending:
        return RedirectResponse("/login", status_code=303)

    email = pending.get("e", "")
    purpose = pending.get("p", "verify")
    masked = email[:2] + "***@" + email.split("@")[-1] if "@" in email else email

    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    code = str(form.get("code", "")).strip()

    valid = await otp_svc.verify_otp(session, email, code, purpose)
    if not valid:
        _record_failure(client_ip)
        return templates.TemplateResponse(
            "verify_otp.html",
            {"request": request, "site_name": settings.site_name,
             "purpose": purpose, "masked_email": masked,
             "error": "Невірний або застарілий код. Спробуйте ще раз."},
        )

    _clear_failures(client_ip)

    # Find user
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse("/register", status_code=303)

    if purpose == "verify":
        user.is_verified = True
        await session.commit()

    response = RedirectResponse("/profile", status_code=303)
    auth_svc.create_session_cookie(response, user.id)
    auth_svc.clear_pending_cookie(response)
    return response


@app.post("/verify/resend", response_class=HTMLResponse)
async def verify_resend(request: Request, session: AsyncSession = Depends(get_session)):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    pending = auth_svc.get_pending(request)
    if not pending:
        return RedirectResponse("/login", status_code=303)

    email = pending.get("e", "")
    purpose = pending.get("p", "verify")
    code = await otp_svc.create_otp(session, email, purpose)
    try:
        await email_svc.send_otp(email, code, purpose)
    except Exception:
        pass

    return RedirectResponse("/verify", status_code=303)


@app.post("/logout")
async def logout():
    response = RedirectResponse("/", status_code=303)
    auth_svc.clear_session(response)
    auth_svc.clear_pending_cookie(response)
    return response


@app.post("/profile/update", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    name = str(form.get("firstName", "")).strip()
    last_name = str(form.get("lastName", "")).strip()
    phone = str(form.get("phone", "")).strip()
    birthday = str(form.get("birthday", "")).strip()

    if name:
        user.name = name
    user.last_name = last_name or None
    user.phone = phone or None
    user.birthday = birthday or None
    await session.commit()

    return RedirectResponse("/profile?saved=1", status_code=303)


# ==================== АДМІНКА ====================

@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders(
    request: Request,
    status: str = "",
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import func
    q = select(Order).order_by(desc(Order.created_at))
    if status in ("new", "confirmed", "shipped", "done", "cancelled"):
        q = q.where(Order.status == OrderStatus(status))
    result = await session.execute(q)
    orders = result.scalars().all()

    items_result = await session.execute(select(OrderItem))
    all_items = items_result.scalars().all()
    items_by_order: dict[int, list] = {}
    for it in all_items:
        items_by_order.setdefault(it.order_id, []).append(it)
    for o in orders:
        o.items = items_by_order.get(o.id, [])

    product_ids = {it.product_id for o in orders for it in o.items if it.product_id}
    products_map: dict[int, Product] = {}
    if product_ids:
        pr = await session.execute(select(Product).where(Product.id.in_(product_ids)))
        for p in pr.scalars().all():
            products_map[p.id] = p

    counts_result = await session.execute(
        select(Order.status, func.count(Order.id)).group_by(Order.status)
    )
    counts = {row[0].value: row[1] for row in counts_result.all()}
    for s in ("new", "confirmed", "shipped", "done", "cancelled"):
        counts.setdefault(s, 0)

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "orders": orders,
        "status": status,
        "counts": counts,
        "total": sum(counts.values()),
        "products_map": products_map,
    })


@app.post("/admin/orders/{order_id}/status")
async def admin_order_status(
    order_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    new_status = str(form.get("s", ""))
    if new_status not in ("confirmed", "shipped", "done", "cancelled"):
        raise HTTPException(400)
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    order.status = OrderStatus(new_status)
    await session.commit()
    ref = request.headers.get("referer", "/admin/orders")
    allowed_paths = {"/admin/orders", "/admin", "/"}
    if not ref.startswith("/") or ref.startswith("//") or ref not in allowed_paths:
        ref = "/admin/orders"
    return RedirectResponse(ref, status_code=303)


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

    no_photo = [p for p in products if not p.original_photo]

    return templates.TemplateResponse(
        "admin.html", {"request": request, "grouped": grouped, "no_photo": no_photo}
    )


async def _generate_task(product_id: int):
    """Background task: generate via Fashn.ai and update status."""
    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            return

        product.status = ProductStatus.GENERATING
        await session.commit()

        try:
            category = detect_category(product.title, product.description or "")
            garment_path = f"{settings.media_dir}/{product.original_photo}"
            out_rel = f"generated/{product.id}.jpg"
            out_abs = f"{settings.media_dir}/{out_rel}"
            Path(out_abs).parent.mkdir(exist_ok=True)

            img_bytes = await fashn_svc.product_to_model(garment_path, settings.fashn_key, category)
            Path(out_abs).write_bytes(img_bytes)

            product.generated_photo = out_rel
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
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
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
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    product = await session.get(Product, product_id)
    if not product or product.status != ProductStatus.READY:
        raise HTTPException(400, "Product not ready")
    product.status = ProductStatus.LIVE
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/publish-direct/{product_id}")
async def admin_publish_direct(
    product_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Публікує одразу з оригінальним фото, без AI генерації."""
    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    product.status = ProductStatus.LIVE
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reject/{product_id}")
async def admin_reject(
    product_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    product.status = ProductStatus.REJECTED
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/api/admin/match-type/{product_id}")
async def admin_set_match_type(
    product_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    product.match_type = "approx" if product.match_type == "exact" else "exact"
    await session.commit()
    return {"id": product_id, "match_type": product.match_type}


# ==================== AI STUDIO ====================

import uuid as _uuid
from fastapi.responses import JSONResponse

_jobs: dict[str, dict] = {}


@app.get("/admin/studio", response_class=HTMLResponse)
async def admin_studio(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Product).order_by(desc(Product.created_at)))
    products = result.scalars().all()
    hero_dir = Path(settings.media_dir, "hero")
    hero_saved = sorted(hero_dir.glob("*.jpg"), reverse=True)[:12] if hero_dir.exists() else []
    return templates.TemplateResponse(
        "admin_studio.html",
        {"request": request, "products": products,
         "hero_saved": hero_saved, "presets": PRESETS},
    )


async def _gen_task(job_id: str, mode: str, image_path: str,
                    prompt: str, strength: float, image_size: str, product_id: int,
                    category: str = "tops"):
    _jobs[job_id] = {"status": "running"}
    try:
        if mode == "fashn":
            img_bytes = await fashn_svc.product_to_model(image_path, settings.fashn_key, category)
            out_rel = f"generated/{job_id}.jpg"
            out_abs = f"{settings.media_dir}/{out_rel}"
            Path(out_abs).parent.mkdir(exist_ok=True)
            Path(out_abs).write_bytes(img_bytes)
            if product_id:
                async with async_session() as sess:
                    p = await sess.get(Product, product_id)
                    if p:
                        p.generated_photo = out_rel
                        p.status = ProductStatus.READY
                        p.error_message = None
                        await sess.commit()
        elif mode == "img2img":
            img_bytes = await img2img(image_path, prompt, strength)
            out_rel = f"generated/{job_id}.jpg"
            out_abs = f"{settings.media_dir}/{out_rel}"
            Path(out_abs).parent.mkdir(exist_ok=True)
            Path(out_abs).write_bytes(img_bytes)
            if product_id:
                async with async_session() as sess:
                    p = await sess.get(Product, product_id)
                    if p:
                        p.generated_photo = out_rel
                        p.status = ProductStatus.READY
                        p.error_message = None
                        await sess.commit()
        else:
            img_bytes = await txt2img(prompt, image_size)
            hero_dir = Path(settings.media_dir, "hero")
            hero_dir.mkdir(exist_ok=True)
            out_rel = f"hero/{job_id}.jpg"
            Path(f"{settings.media_dir}/{out_rel}").write_bytes(img_bytes)

        _jobs[job_id] = {"status": "done", "result": out_rel, "product_id": product_id}
    except Exception as e:
        _jobs[job_id] = {"status": "error", "error": str(e)}


@app.post("/admin/studio/generate")
async def admin_studio_generate(
    request: Request,
    background: BackgroundTasks,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    auth_svc.verify_csrf(request, str(form.get("csrf_token", "")))
    mode = str(form.get("mode", "img2img"))
    product_id = int(form.get("product_id") or 0)
    prompt = str(form.get("prompt", "")).strip()
    strength = float(form.get("strength") or 0.80)
    image_size = str(form.get("image_size") or "landscape_16_9")
    assign = form.get("assign") == "1"
    category = str(form.get("category") or "auto")

    image_path = ""
    if mode in ("img2img", "fashn"):
        if not product_id:
            raise HTTPException(400, "Вибери продукт")
        product = await session.get(Product, product_id)
        if not product:
            raise HTTPException(404)
        image_path = f"{settings.media_dir}/{product.original_photo}"
        if category == "auto":
            category = detect_category(product.title, product.description or "")
    elif mode == "txt2img":
        if not prompt:
            raise HTTPException(400, "Промпт обов'язковий")

    if mode == "img2img" and not prompt:
        raise HTTPException(400, "Промпт обов'язковий")

    job_id = _uuid.uuid4().hex[:12]
    assign_id = product_id if (assign and mode in ("img2img", "fashn")) else 0
    background.add_task(_gen_task, job_id, mode, image_path, prompt, strength, image_size, assign_id, category)

    if mode == "txt2img":
        tab = "hero"
    elif mode == "fashn":
        tab = "fashn"
    else:
        tab = "edit"
    return RedirectResponse(f"/admin/studio?job={job_id}&tab={tab}", status_code=303)


@app.get("/admin/studio/status/{job_id}")
async def admin_studio_status(job_id: str, _: str = Depends(require_admin)):
    return JSONResponse(_jobs.get(job_id, {"status": "unknown"}))


# ==================== REORDER PHOTOS ====================

import json as _json_mod

@app.post("/admin/photos/reorder/{product_id}")
async def admin_reorder_photos(
    product_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    data = await request.json()
    photos: list[str] = data.get("photos", [])
    if not photos:
        raise HTTPException(400, "Empty photos list")
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    product.original_photo = photos[0]
    product.extra_photos = _json_mod.dumps(photos[1:]) if len(photos) > 1 else None
    await session.commit()
    return JSONResponse({"ok": True})


# ==================== TRANSLATE TITLE ====================

@app.post("/admin/translate/{product_id}")
async def admin_translate(
    product_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404)

    text = product.title
    encoded = _urlparse.quote(text)
    url = (
        f"https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=tr&tl=uk&dt=t&q={encoded}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()

    parts = data[0] if data and data[0] else []
    title_ua = "".join(p[0] for p in parts if p and p[0]).strip()
    if not title_ua:
        raise HTTPException(500, "Translation failed")

    product.title_ua = title_ua
    await session.commit()
    return JSONResponse({"title_ua": title_ua})


# ==================== PUBLIC TRY-ON ====================

@app.get("/tryon", response_class=HTMLResponse)
async def tryon_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Product)
        .where(Product.status == ProductStatus.LIVE)
        .order_by(desc(Product.created_at))
    )
    products = result.scalars().all()
    return templates.TemplateResponse(
        "tryon.html",
        {"request": request, "products": products, "active": "tryon"},
    )


@app.post("/tryon/generate")
async def tryon_generate(
    product_id: int = Form(...),
    user_photo: UploadFile = File(None),
    ref_model: str = Form(None),
    session: AsyncSession = Depends(get_session),
):
    # Validate product
    product = await session.get(Product, product_id)
    if not product:
        from fastapi.responses import JSONResponse as _JSONResp
        return _JSONResp({"error": "Товар не знайдено"}, status_code=404)

    if not product.original_photo:
        return JSONResponse({"error": "У товару немає фото"}, status_code=400)

    # Ensure output dirs exist
    uploads_dir = Path(settings.media_dir) / "tryon_uploads"
    results_dir = Path(settings.media_dir) / "tryon_results"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    # Determine model (user photo or reference)
    model_path: str | None = None
    tmp_upload: Path | None = None

    _MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB

    if user_photo and user_photo.filename:
        if not (user_photo.content_type or "").startswith("image/"):
            return JSONResponse({"error": "Будь ласка, завантажте файл зображення"}, status_code=400)
        upload_id = str(_uuid.uuid4())
        tmp_upload = uploads_dir / f"{upload_id}.jpg"
        content = await user_photo.read(_MAX_UPLOAD + 1)
        if len(content) > _MAX_UPLOAD:
            return JSONResponse({"error": "Файл занадто великий (макс. 10 MB)"}, status_code=413)
        tmp_upload.write_bytes(content)
        model_path = str(tmp_upload)
    elif ref_model:
        # Validate ref_model: only allow alphanumeric + hyphens to prevent path traversal
        if not _re.match(r'^[A-Za-z0-9\-]+$', ref_model):
            return JSONResponse({"error": "Невірна модель"}, status_code=400)
        ref_path = (Path(settings.media_dir) / "models" / f"{ref_model}.jpg").resolve()
        allowed_dir = (Path(settings.media_dir) / "models").resolve()
        if not str(ref_path).startswith(str(allowed_dir)):
            return JSONResponse({"error": "Невірна модель"}, status_code=400)
        if not ref_path.exists():
            return JSONResponse({"error": "Модель не знайдено"}, status_code=404)
        model_path = str(ref_path)
    else:
        return JSONResponse({"error": "Оберіть фото або референс-модель"}, status_code=400)

    garment_path = str(Path(settings.media_dir) / product.original_photo)
    category = detect_category(product.title, getattr(product, "description", None) or "")

    try:
        result_bytes = await fashn_svc.tryon(garment_path, model_path, settings.fashn_key, category)
    except Exception:
        return JSONResponse({"error": "Помилка AI-сервісу. Спробуйте пізніше."}, status_code=500)

    result_id = str(_uuid.uuid4())
    result_file = results_dir / f"{result_id}.jpg"
    result_file.write_bytes(result_bytes)
    return JSONResponse({"result": f"tryon_results/{result_id}.jpg"})


# ════════════════════════════════════════════
#  1С HTTP API
# ════════════════════════════════════════════
def _check_1c_key(request: Request) -> bool:
    key = request.headers.get("X-1C-Key", "")
    if not settings.api_1c_key:
        return False
    return _hmac.compare_digest(key, settings.api_1c_key)


@app.get("/api/1c/ping")
async def api_1c_ping(request: Request):
    """Перевірка з'єднання — відповідає pong якщо ключ вірний."""
    if not _check_1c_key(request):
        raise HTTPException(status_code=401, detail="Невірний API ключ")
    return {"status": "pong", "version": "1.0"}


@app.post("/api/1c/sync")
async def api_1c_sync(request: Request, background: BackgroundTasks):
    """
    Масова синхронізація товарів з 1С.

    Тіло запиту (JSON):
    {
        "source": "women",          // або "men"
        "products": [
            {"article": "ABC123", "price": 1299.00, "stock": 5},
            {"article": "XYZ456", "price": 899.00,  "stock": 0}
        ]
    }
    Заголовок: X-1C-Key: <ваш_ключ>
    """
    if not _check_1c_key(request):
        raise HTTPException(status_code=401, detail="Невірний API ключ")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Невалідний JSON")

    source = body.get("source", "women")
    if source not in ("women", "men"):
        raise HTTPException(status_code=400, detail="source має бути 'women' або 'men'")

    products_data = body.get("products", [])
    if not isinstance(products_data, list):
        raise HTTPException(status_code=400, detail="products має бути масивом")

    updated = created = skipped = 0

    async with async_session() as session:
        for item in products_data:
            article = str(item.get("article", "")).strip()
            name_1c = str(item.get("name", "")).strip()
            price = item.get("price")
            stock = int(item.get("stock", 0))

            if not article:
                skipped += 1
                continue

            # Чоловічий відділ: артикулі з M на 3-й позиції (WAM, SAM тощо)
            if source == "men" and len(article) >= 4 and article[3] != "M":
                skipped += 1
                continue

            # Шукаємо існуючий товар по повному артикулу
            result = await session.execute(
                select(Product).where(Product.article_1c == article)
            )
            existing = result.scalar_one_or_none()

            if existing:
                if price is not None:
                    existing.price_uah = float(price)
                existing.stock = stock
                existing.gender = source
                # Якщо title == article (нема нормальної назви) — оновлюємо з 1С
                if name_1c and (not existing.title or existing.title == article):
                    existing.title = name_1c
                existing.updated_at = __import__("datetime").datetime.utcnow()
                updated += 1
            else:
                new_p = Product(
                    title=name_1c or article,
                    article_1c=article,
                    gender=source,
                    price_uah=float(price) if price is not None else None,
                    stock=stock,
                    original_photo="",
                    status=ProductStatus.PENDING,
                )
                session.add(new_p)
                created += 1

        await session.commit()

    return {
        "ok": True,
        "source": source,
        "updated": updated,
        "created": created,
        "skipped": skipped,
        "total": len(products_data),
    }


@app.post("/api/1c/price")
async def api_1c_price(request: Request):
    """
    Оновлення ціни одного товару.

    {"article": "ABC123", "price": 1299.00, "source": "women"}
    Заголовок: X-1C-Key: <ваш_ключ>
    """
    if not _check_1c_key(request):
        raise HTTPException(status_code=401, detail="Невірний API ключ")

    body = await request.json()
    article = str(body.get("article", "")).strip()
    price = body.get("price")
    source = body.get("source", "women")

    if not article or price is None:
        raise HTTPException(status_code=400, detail="Потрібні поля: article, price")

    async with async_session() as session:
        result = await session.execute(
            select(Product).where(Product.article_1c == article)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail=f"Товар {article} не знайдено")
        product.price_uah = float(price)
        product.gender = source
        product.updated_at = __import__("datetime").datetime.utcnow()
        await session.commit()

    return {"ok": True, "article": article, "price": float(price)}


@app.post("/api/1c/stock")
async def api_1c_stock(request: Request):
    """
    Оновлення залишків одного або кількох товарів.

    {"items": [{"article": "ABC123", "stock": 3}, ...]}
    Заголовок: X-1C-Key: <ваш_ключ>
    """
    if not _check_1c_key(request):
        raise HTTPException(status_code=401, detail="Невірний API ключ")

    body = await request.json()
    items = body.get("items", [])
    updated = 0

    async with async_session() as session:
        for item in items:
            article = str(item.get("article", "")).strip()
            stock = int(item.get("stock", 0))
            if not article:
                continue
            result = await session.execute(
                select(Product).where(Product.article_1c == article)
            )
            product = result.scalar_one_or_none()
            if product:
                product.stock = stock
                updated += 1
        await session.commit()

    return {"ok": True, "updated": updated}


@app.post("/api/admin/enrich-koton")
async def admin_enrich_koton(
    background: BackgroundTasks,
    gender: str = "",
    _: str = Depends(require_admin),
):
    """Запускає збагачення PENDING товарів з Koton.com (фото, назва, розміри)."""
    from app.services.koton_scraper import enrich_pending_from_1c
    background.add_task(enrich_pending_from_1c, gender or None)
    return {"ok": True, "message": "Збагачення запущено у фоні"}


@app.post("/api/admin/translate-all")
async def admin_translate_all(
    background: BackgroundTasks,
    _: str = Depends(require_admin),
):
    """Масовий переклад всіх турецьких назв на українську."""
    from app.services.koton_scraper import bulk_translate_titles
    background.add_task(bulk_translate_titles)
    return {"ok": True, "message": "Переклад запущено у фоні"}


@app.post("/api/admin/re-enrich-koton")
async def admin_re_enrich_koton(
    background: BackgroundTasks,
    gender: str = "",
    force: bool = False,
    prefix: str = "",
    _: str = Depends(require_admin),
):
    """
    Повторно збагачує ВСІ товари з article_1c — оновлює ціну, всі фото,
    таблицю розмірів незалежно від статусу. force=true перезаписує навіть повні.
    prefix=6 — тільки артикули що починаються з 6.
    """
    from app.services.koton_scraper import re_enrich_all_koton_products
    background.add_task(re_enrich_all_koton_products, gender or None, force, prefix or None)
    return {"ok": True, "message": f"Повторне збагачення запущено (prefix={prefix or 'всі'}, force={force})"}


@app.post("/api/admin/enrich-wayback")
async def admin_enrich_wayback(
    background: BackgroundTasks,
    gender: str = "men",
    _: str = Depends(require_admin),
):
    """Шукає товари без фото в Wayback Machine за датою сезону артикула. Тільки точний збіг."""
    from app.services.koton_scraper import enrich_missing_via_wayback
    background.add_task(enrich_missing_via_wayback, gender)
    return {"ok": True, "message": f"Wayback збагачення запущено для gender={gender}"}


@app.post("/api/admin/assign-koton-categories")
async def admin_assign_koton_categories(
    background: BackgroundTasks,
    gender: str = "men",
    _: str = Depends(require_admin),
):
    """
    Визначає категорію та сезон товарів через архіви Koton.com (Wayback Machine).
    Використовує дати замовлень: лют/трав/вер/груд 2025, бер 2026.
    Оновлює поля category + season у БД для товарів без категорії.
    """
    from app.services.koton_scraper import assign_categories_from_order_dates
    background.add_task(assign_categories_from_order_dates, gender)
    return {"ok": True, "message": f"Категоризація запущена для gender={gender}"}


# ════════════════════════════════════════════
#  Синхронізація залишків з 1С (файловий режим)
# ════════════════════════════════════════════

@app.get("/api/admin/1c-sync-status")
async def admin_1c_sync_status(_: str = Depends(require_admin)):
    """Статус останньої синхронізації з 1С."""
    from app.services.sync_1c import load_state
    state = load_state()
    if not state:
        return {"last_sync": None, "message": "Синхронізацій ще не було"}
    return state


@app.post("/api/admin/1c-file-upload")
async def admin_1c_file_upload(
    file: UploadFile,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Приймає Excel (.xlsx) або CSV файл з 1С. Колонки: Артикул, Залишок, Ціна."""
    import io, csv as _csv
    from app.services.sync_1c import save_state as _save
    from datetime import datetime as _dt

    content = await file.read()
    fname_orig = file.filename or ""
    rows = []

    if fname_orig.endswith(".xlsx") or fname_orig.endswith(".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        headers = None
        for row in ws.iter_rows(values_only=True):
            if headers is None:
                headers = [str(c or "").strip().lower() for c in row]
                continue
            if all(c is None for c in row):
                continue
            item = dict(zip(headers, row))
            rows.append(item)
    elif fname_orig.endswith(".csv") or fname_orig.endswith(".txt"):
        text = content.decode("utf-8-sig", errors="replace")
        sample = text[:512]
        delim = ";" if sample.count(";") > sample.count(",") else ","
        reader = _csv.DictReader(io.StringIO(text), delimiter=delim)
        rows = list(reader)
    else:
        raise HTTPException(400, "Підтримуються лише .xlsx або .csv файли")

    ARTICLE_KEYS = ["артикул", "article", "код", "code"]
    STOCK_KEYS   = ["залишок", "stock", "кількість", "quantity", "qty"]
    PRICE_KEYS   = ["ціна", "price", "цена"]

    def _find(item: dict, keys: list):
        for k in keys:
            for ik in item:
                if str(ik).strip().lower() == k:
                    v = item[ik]
                    return str(v).strip() if v is not None else ""
        return ""

    def _num(s, as_int=False):
        if not s:
            return None
        try:
            s = str(s).replace(" ", "").replace(",", ".").replace("\xa0", "")
            return int(float(s)) if as_int else float(s)
        except Exception:
            return None

    updated = created = skipped = 0
    sync_dir = Path("sync")
    sync_dir.mkdir(exist_ok=True)

    async with async_session() as s:
        for item in rows:
            article = _find(item, ARTICLE_KEYS)
            if not article:
                skipped += 1
                continue
            stock = _num(_find(item, STOCK_KEYS), as_int=True) or 0
            price = _num(_find(item, PRICE_KEYS))

            res = await s.execute(select(Product).where(Product.article_1c == article))
            p = res.scalar_one_or_none()
            if p:
                p.stock = stock
                if price is not None:
                    p.price_uah = price
                updated += 1
            else:
                skipped += 1
        await s.commit()

    saved = sync_dir / f"upload_{_dt.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    _save(saved, len(rows), updated, created)
    return {"ok": True, "updated": updated, "skipped": skipped, "total": len(rows)}


@app.post("/api/admin/1c-upload")
async def admin_1c_upload(
    request: Request,
    background: BackgroundTasks,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Завантажує JSON-файл з 1С і одразу синхронізує."""
    from app.services.sync_1c import save_state as _save
    import json as _json

    body = await request.body()
    try:
        raw = _json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Невалідний JSON")

    rows = raw if isinstance(raw, list) else raw.get("products", [])
    if not rows:
        raise HTTPException(status_code=400, detail="Порожній список товарів")

    sync_dir = Path("sync")
    sync_dir.mkdir(exist_ok=True)
    from datetime import datetime as _dt
    fname = sync_dir / f"upload_{_dt.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    fname.write_text(_json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    updated = created = skipped = 0
    async with async_session() as s:
        for item in rows:
            article = str(item.get("article", "")).strip()
            if not article:
                skipped += 1
                continue
            res = await s.execute(select(Product).where(Product.article_1c == article))
            p = res.scalar_one_or_none()
            if p:
                p.stock = int(item.get("stock", 0))
                if item.get("price"):
                    p.price_uah = float(item["price"])
                updated += 1
            else:
                s.add(Product(
                    title=article, article_1c=article,
                    gender=str(item.get("source", "women")),
                    price_uah=float(item["price"]) if item.get("price") else None,
                    stock=int(item.get("stock", 0)),
                    original_photo="", status=ProductStatus.PENDING,
                ))
                created += 1
        await s.commit()

    _save(fname, len(rows), updated, created)
    return {"ok": True, "updated": updated, "created": created, "skipped": skipped, "total": len(rows)}


@app.post("/api/admin/1c-sync-now")
async def admin_1c_sync_now(
    background: BackgroundTasks,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Запускає синхронізацію з 1С зараз (читає файл із sync/)."""
    from app.services.sync_1c import load_newest_export, save_state as _save

    products, file_path = load_newest_export()
    if not products:
        return {"ok": False, "error": "Файл не знайдено в папці sync/. Спершу вивантажте дані з 1С."}

    async def _do_sync():
        from app.db import async_session as _sess
        from app.models import Product as _P
        updated = skipped = 0
        async with _sess() as s:
            for item in products:
                res = await s.execute(select(_P).where(_P.article_1c == item["article"]))
                p = res.scalar_one_or_none()
                if p:
                    p.stock = item["stock"]
                    if item["price"] is not None:
                        p.price_uah = item["price"]
                    updated += 1
                else:
                    skipped += 1
            await s.commit()
        _save(file_path, len(products), updated, 0)

    background.add_task(_do_sync)
    return {"ok": True, "message": f"Синхронізацію запущено ({len(products)} рядків з {file_path.name})"}


@app.post("/api/admin/scrape-women")
async def admin_scrape_women(
    background: BackgroundTasks,
    limit: int = 50,
    _: str = Depends(require_admin),
):
    """Скрейпить жіночі товари з категорій Koton.com."""
    from app.services.koton_scraper import scrape_koton_women_catalog
    background.add_task(scrape_koton_women_catalog, limit)
    return {"ok": True, "message": f"Запущено скрейпінг жіночих (limit={limit})"}


@app.post("/api/admin/publish-all-pending")
async def admin_publish_all_pending(
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Публікує всі PENDING товари що мають фото (без AI)."""
    from sqlalchemy import update
    result = await session.execute(
        select(Product).where(
            Product.status == ProductStatus.PENDING,
            Product.original_photo != "",
            Product.original_photo.isnot(None),
        )
    )
    products = result.scalars().all()
    count = 0
    for p in products:
        p.status = ProductStatus.LIVE
        count += 1
    await session.commit()
    return {"ok": True, "published": count}


@app.post("/api/admin/generate-hero")
async def api_generate_hero(
    request: Request,
    background: BackgroundTasks,
    _: str = Depends(require_admin),
):
    """Генерує hero изображення для головної сторінки на основі промпту."""
    from app.services.hero_prompt import generate_hero_prompt
    data = await request.json()
    theme = str(data.get("theme", "editorial"))
    user_desc = str(data.get("user_photo_desc", ""))

    prompt = generate_hero_prompt(theme, user_desc)
    hero_dir = Path(settings.media_dir, "hero")
    hero_dir.mkdir(exist_ok=True)

    job_id = _uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "processing", "type": "hero"}

    async def _gen_hero():
        try:
            img_bytes = await txt2img(prompt, "landscape_16_9")
            out_rel = f"hero/{job_id}.jpg"
            Path(f"{settings.media_dir}/{out_rel}").write_bytes(img_bytes)
            _jobs[job_id] = {"status": "done", "result": out_rel, "prompt": prompt}
        except Exception as e:
            _jobs[job_id] = {"status": "error", "error": str(e)}

    background.add_task(_gen_hero)
    return {"job_id": job_id, "prompt": prompt}


@app.get("/admin/1c", response_class=HTMLResponse)
async def admin_1c_page(request: Request, _: str = Depends(require_admin)):
    def _read(name: str) -> str:
        p = Path("1c") / name
        return p.read_text(encoding="utf-8") if p.exists() else f"— {name} не знайдено —"
    return templates.TemplateResponse(
        "admin_1c.html",
        {
            "request": request,
            "module_code": _read("SAHARA_ОбщийМодуль.bsl"),
            "regtask_code": _read("SAHARA_РегЗадание.bsl"),
            "api_key": settings.api_1c_key,
        },
    )
