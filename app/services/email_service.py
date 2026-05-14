import logging
import resend

from app.config import settings

logger = logging.getLogger("sahara.email")

SITE = "https://sahara-store.net"
LOGO_IMG = f"{SITE}/static/img/logo-email.png"


def _html_otp(code: str, purpose: str) -> str:
    action = "реєстрації" if purpose == "verify" else "входу"
    subject_line = "Підтвердження акаунту" if purpose == "verify" else "Код для входу"

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{subject_line}</title>
</head>
<body style="margin:0;padding:0;background:#f4f1ec;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f1ec;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff;max-width:560px;width:100%;border:1px solid #e0d9ce;">

        <!-- Logo header -->
        <tr>
          <td style="padding:0;line-height:0;">
            <a href="{SITE}" style="display:block;">
              <img src="{LOGO_IMG}" alt="SAHARA"
                   width="560" style="width:100%;max-width:560px;display:block;">
            </a>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:44px 48px 36px;">
            <p style="font-size:13px;text-transform:uppercase;letter-spacing:0.12em;
                      color:#999;margin:0 0 20px;">
              {subject_line}
            </p>
            <h1 style="font-family:Georgia,serif;font-size:24px;font-weight:400;
                       color:#111;letter-spacing:0.03em;margin:0 0 16px;line-height:1.3;">
              Ваш код для {action}
            </h1>
            <p style="font-size:14px;color:#666;margin:0 0 32px;line-height:1.7;">
              Використайте цей код для підтвердження вашого акаунту SAHARA.
              Він дійсний протягом <strong style="color:#111;">10 хвилин</strong>.
            </p>

            <!-- OTP code box -->
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding:0 0 32px;">
                  <div style="display:inline-block;background:#f4f1ec;border:1px solid #e0d9ce;
                              padding:20px 48px;">
                    <span style="font-family:'Courier New',monospace;font-size:42px;
                                 font-weight:700;letter-spacing:0.2em;color:#111111;">
                      {code}
                    </span>
                  </div>
                </td>
              </tr>
            </table>

            <p style="font-size:13px;color:#999;line-height:1.7;margin:0;">
              Якщо ви не запитували цей код — просто проігноруйте цей лист.<br>
              Ваш акаунт залишиться в безпеці.
            </p>
          </td>
        </tr>

        <!-- Divider -->
        <tr><td style="padding:0 48px;">
          <div style="height:1px;background:#e0d9ce;"></div>
        </td></tr>

        <!-- Footer -->
        <tr>
          <td style="padding:24px 48px;text-align:center;">
            <p style="font-size:12px;color:#bbb;margin:0 0 8px;letter-spacing:0.05em;">
              <a href="{SITE}" style="color:#c9a96e;text-decoration:none;">sahara-store.net</a>
              &nbsp;·&nbsp;
              <a href="{SITE}/support" style="color:#bbb;text-decoration:none;">Підтримка</a>
              &nbsp;·&nbsp;
              <a href="{SITE}/legal" style="color:#bbb;text-decoration:none;">Правова інформація</a>
            </p>
            <p style="font-size:11px;color:#ccc;margin:0;">
              © 2026 SAHARA — Цей лист надіслано автоматично, не відповідайте на нього.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


async def send_otp(to_email: str, code: str, purpose: str) -> None:
    if not settings.resend_api_key:
        logger.warning(f"[DEV] Resend not configured. OTP for {to_email} ({purpose}): {code}")
        print(f"\n{'='*50}\n[OTP DEV] {to_email} | purpose={purpose} | code={code}\n{'='*50}\n")
        return

    subject = "Код підтвердження SAHARA" if purpose == "verify" else "Код входу — SAHARA"
    resend.api_key = settings.resend_api_key

    try:
        resend.Emails.send({
            "from": f"SAHARA <{settings.smtp_from}>",
            "to": [to_email],
            "subject": subject,
            "html": _html_otp(code, purpose),
        })
        logger.info(f"OTP sent to {to_email} via Resend")
    except Exception as exc:
        logger.error(f"Failed to send OTP email to {to_email}: {exc}")
        raise


def _html_order(order, items: list) -> str:
    delivery = (
        f"Нова пошта, {order.city}, відд. {order.np_branch}"
        if order.delivery_type == "nova_poshta"
        else "Самовивіз — вул. Театральна, 6, Ковель"
    )
    rows = "".join(
        "<tr>"
        f"<td style='padding:8px 0;border-bottom:1px solid #f0ebe3;font-size:14px;color:#333;'>{it.product_title}</td>"
        f"<td style='padding:8px 0;border-bottom:1px solid #f0ebe3;font-size:14px;color:#333;text-align:center;'>{it.qty}</td>"
        f"<td style='padding:8px 0;border-bottom:1px solid #f0ebe3;font-size:14px;color:#333;text-align:right;'>{int(it.price_uah * it.qty)} &#8372;</td>"
        "</tr>"
        for it in items
    )
    return f"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="UTF-8"><title>Замовлення #{order.id}</title></head>
<body style="margin:0;padding:0;background:#f4f1ec;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f1ec;padding:40px 0;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0"
       style="background:#fff;max-width:560px;width:100%;border:1px solid #e0d9ce;">
  <tr><td style="padding:32px 40px 0;text-align:center;">
    <p style="font-family:Georgia,serif;font-size:28px;letter-spacing:.15em;margin:0;">SAHARA</p>
  </td></tr>
  <tr><td style="padding:32px 40px;">
    <p style="font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#999;margin:0 0 12px;">
      Замовлення #{order.id}</p>
    <h1 style="font-family:Georgia,serif;font-size:22px;font-weight:400;color:#111;margin:0 0 16px;">
      Дякуємо за замовлення!</h1>
    <p style="font-size:14px;color:#666;margin:0 0 32px;line-height:1.7;">
      Ми отримали ваше замовлення і зв'яжемося з вами найближчим часом для підтвердження.</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
      <tr>
        <th style="text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#999;
                   padding-bottom:8px;border-bottom:2px solid #111;">Товар</th>
        <th style="text-align:center;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#999;
                   padding-bottom:8px;border-bottom:2px solid #111;">К-сть</th>
        <th style="text-align:right;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#999;
                   padding-bottom:8px;border-bottom:2px solid #111;">Сума</th>
      </tr>
      {rows}
      <tr>
        <td colspan="2" style="padding:12px 0 0;font-size:13px;text-transform:uppercase;
                                letter-spacing:.1em;font-weight:600;">Всього</td>
        <td style="padding:12px 0 0;text-align:right;font-size:15px;font-weight:600;">
          {int(order.total_uah)} &#8372;</td>
      </tr>
    </table>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#faf8f4;border:1px solid #e0d9ce;padding:20px;margin-bottom:24px;">
      <tr><td>
        <p style="font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:#999;margin:0 0 8px;">
          Доставка</p>
        <p style="font-size:14px;color:#333;margin:0;">{delivery}</p>
      </td></tr>
    </table>
    <p style="font-size:13px;color:#666;line-height:1.7;margin:0;">
      З питаннями: <a href="mailto:info@sahara.ua" style="color:#111;">info@sahara.ua</a>
      або <a href="tel:+380441234567" style="color:#111;">+380 (44) 123-45-67</a></p>
  </td></tr>
  <tr><td style="padding:16px 40px;border-top:1px solid #f0ebe3;text-align:center;">
    <p style="font-size:11px;color:#aaa;margin:0;">&copy; 2026 SAHARA &middot; вул. Театральна, 6, Ковель</p>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>"""


async def send_order_confirmation(to_email: str, order, items: list) -> None:
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set — order confirmation email skipped")
        return
    resend.api_key = settings.resend_api_key
    html = _html_order(order, items)
    try:
        resend.Emails.send({
            "from": f"SAHARA <{settings.smtp_from}>",
            "to": [to_email],
            "subject": f"Замовлення #{order.id} прийнято — SAHARA",
            "html": html,
        })
        logger.info("Order confirmation sent to %s", to_email)
    except Exception as e:  # fire-and-forget — don't fail the order
        logger.error("Order confirmation email failed: %s", e)
