import asyncio
import html
import os
import smtplib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path


email_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email-worker")


def load_env_file() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def money(value: float) -> str:
    return f"${value:,.2f}"


def build_ticket_html(ticket: dict) -> str:
    items_html = ""
    for item in ticket["items"]:
        items_html += f"""
        <tr>
          <td style="padding:12px;border-bottom:1px solid #e5e7eb;">
            <strong>{html.escape(item["name"])}</strong><br>
            <span style="color:#6b7280;font-size:13px;">SKU {html.escape(item["sku"] or "N/A")} · {html.escape(item["color"] or "N/A")} · {html.escape(item["size"] or "N/A")}</span>
          </td>
          <td style="padding:12px;border-bottom:1px solid #e5e7eb;text-align:center;">{item["quantity"]}</td>
          <td style="padding:12px;border-bottom:1px solid #e5e7eb;text-align:right;">{money(item["unit_price"])}</td>
          <td style="padding:12px;border-bottom:1px solid #e5e7eb;text-align:right;font-weight:700;">{money(item["line_total"])}</td>
        </tr>
        """

    return f"""
    <!doctype html>
    <html lang="es">
      <body style="margin:0;background:#f3f5f7;font-family:Arial,Helvetica,sans-serif;color:#20242a;">
        <div style="max-width:760px;margin:0 auto;padding:28px;">
          <div style="background:#0f766e;color:white;border-radius:14px 14px 0 0;padding:26px 30px;">
            <h1 style="margin:0;font-size:28px;">Ticket de compra</h1>
            <p style="margin:8px 0 0;color:#d1faf4;">Gorras POS · Compra aceptada</p>
          </div>

          <div style="background:white;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 14px 14px;padding:28px 30px;">
            <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:22px;">
              <div style="flex:1;min-width:220px;background:#f8fafc;border-radius:10px;padding:16px;">
                <div style="color:#6b7280;font-size:13px;">Cliente</div>
                <div style="font-weight:700;font-size:18px;">{html.escape(ticket["customer_name"])}</div>
                <div style="color:#6b7280;margin-top:4px;">{html.escape(ticket["customer_email"])}</div>
              </div>
              <div style="flex:1;min-width:220px;background:#f8fafc;border-radius:10px;padding:16px;">
                <div style="color:#6b7280;font-size:13px;">Compra</div>
                <div style="font-weight:700;font-size:18px;">#{ticket["purchase_id"]}</div>
                <div style="color:#6b7280;margin-top:4px;">{html.escape(ticket["created_at"])}</div>
              </div>
            </div>

            <table style="width:100%;border-collapse:collapse;background:white;">
              <thead>
                <tr style="background:#eef2f7;color:#374151;">
                  <th style="padding:12px;text-align:left;">Producto</th>
                  <th style="padding:12px;text-align:center;">Cant.</th>
                  <th style="padding:12px;text-align:right;">Precio</th>
                  <th style="padding:12px;text-align:right;">Importe</th>
                </tr>
              </thead>
              <tbody>{items_html}</tbody>
            </table>

            <div style="margin-top:22px;margin-left:auto;max-width:320px;">
              <div style="display:flex;justify-content:space-between;padding:8px 0;color:#374151;">
                <span>Subtotal</span><strong>{money(ticket["subtotal"])}</strong>
              </div>
              <div style="display:flex;justify-content:space-between;padding:8px 0;color:#374151;">
                <span>IVA 16%</span><strong>{money(ticket["iva"])}</strong>
              </div>
              <div style="display:flex;justify-content:space-between;padding:12px 0;border-top:2px solid #e5e7eb;font-size:22px;">
                <span>Total</span><strong>{money(ticket["total"])}</strong>
              </div>
            </div>

            <div style="margin-top:24px;background:#ecfdf5;border-left:5px solid #0f766e;border-radius:8px;padding:14px 16px;color:#065f46;">
              Tu pedido fue registrado correctamente. Gracias por comprar en Gorras POS.
            </div>
          </div>
        </div>
      </body>
    </html>
    """


def send_ticket_email_sync(ticket: dict) -> None:
    load_env_file()
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    store_email = os.getenv("STORE_EMAIL", smtp_user or "")

    if not smtp_user or not smtp_password:
        raise RuntimeError("Faltan SMTP_USER o SMTP_PASSWORD")

    message = EmailMessage()
    message["Subject"] = f"Ticket de compra #{ticket['purchase_id']} - Gorras POS"
    message["From"] = f"Gorras POS <{smtp_user}>"
    message["To"] = ticket["customer_email"]
    if store_email:
        message["Bcc"] = store_email

    plain_items = "\n".join(
        f"- {item['name']} x{item['quantity']} = {money(item['line_total'])}"
        for item in ticket["items"]
    )
    message.set_content(
        f"Ticket de compra #{ticket['purchase_id']}\n\n"
        f"Cliente: {ticket['customer_name']}\n"
        f"Correo: {ticket['customer_email']}\n\n"
        f"{plain_items}\n\n"
        f"Subtotal: {money(ticket['subtotal'])}\n"
        f"IVA 16%: {money(ticket['iva'])}\n"
        f"Total: {money(ticket['total'])}\n"
    )
    message.add_alternative(build_ticket_html(ticket), subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)


async def send_ticket_email(ticket: dict) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(email_pool, send_ticket_email_sync, ticket)


def ticket_timestamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")
