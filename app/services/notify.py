import logging
import httpx
from app.config import settings

logger = logging.getLogger("sahara.notify")


async def send_order_telegram(order, items: list) -> None:
    if not settings.tg_bot_token or not settings.tg_admin_chat_id:
        return

    delivery = (
        f"Нова пошта, {order.city}, №{order.np_branch}"
        if order.delivery_type == "nova_poshta"
        else "Самовивіз — вул. Театральна, 6, Ковель"
    )

    lines = [
        f"\U0001f6d2 <b>Нове замовлення #{order.id}</b>",
        f"\U0001f464 {order.name}",
        f"\U0001f4de {order.phone}",
        f"\U0001f4e7 {order.email}",
        "",
        f"\U0001f4e6 {delivery}",
        "",
        "Товари:",
    ]
    for it in items:
        lines.append(f"• {it.product_title} × {it.qty} — {int(it.price_uah * it.qty):,} ₴".replace(",", " "))
    lines.append("")
    lines.append(f"\U0001f4b0 <b>Всього: {int(order.total_uah):,} ₴</b>".replace(",", " "))

    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={
                "chat_id": settings.tg_admin_chat_id,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
            })
    except Exception as exc:
        logger.warning("Telegram notify failed: %s", exc)
