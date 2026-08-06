"""Отправка писем через SMTP-настройки из админки.

Провайдер не зашит: подойдёт любой SMTP — свой сервер, Яндекс 360, Mailgun,
Resend и так далее. Достаточно заполнить smtp_* в настройках панели.

smtplib блокирующий, поэтому наружу торчат корутины: они уводят отправку в
поток, чтобы не вешать event loop веб-аппа на время рукопожатия с сервером.
"""

import asyncio
import logging
import re
import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage

from shop_bot.data_manager.remnawave_repository import get_setting

logger = logging.getLogger(__name__)

# Одно и то же правило и для регистрации, и для рассылки: строго проще, чем
# RFC 5322, но отсекает всё, что почтовые серверы всё равно отвергнут.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

SMTP_TIMEOUT_SECONDS = 20


class MailError(RuntimeError):
    """Письмо не ушло. Текст пригоден для показа пользователю."""


def is_valid_email(email: str) -> bool:
    email = (email or "").strip()
    return bool(email) and len(email) <= 254 and bool(EMAIL_RE.match(email))


def _setting(key: str, default: str = "") -> str:
    try:
        return (get_setting(key) or default).strip()
    except Exception:
        return default


def is_configured() -> bool:
    """Готова ли отправка. Пароль необязателен: бывают релеи по IP."""
    if _setting("smtp_enabled", "false").lower() not in ("1", "true", "on", "yes"):
        return False
    return bool(_setting("smtp_host")) and bool(_setting("smtp_from_email"))


def sender_address() -> str:
    return _setting("smtp_from_email")


def _build_message(to_email: str, subject: str, text: str, html: str | None) -> EmailMessage:
    from_email = _setting("smtp_from_email")
    from_name = _setting("smtp_from_name") or _setting("panel_brand_title") or "VPN"
    local, _, domain = from_email.partition("@")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = Address(from_name, local, domain)
    message["To"] = to_email
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _send_blocking(message: EmailMessage) -> None:
    host = _setting("smtp_host")
    security = (_setting("smtp_security", "starttls") or "starttls").lower()
    default_port = {"ssl": 465, "none": 25}.get(security, 587)
    try:
        port = int(_setting("smtp_port") or default_port)
    except ValueError:
        port = default_port

    user = _setting("smtp_user")
    password = _setting("smtp_password")

    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            if user:
                server.login(user, password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("SMTP отклонил логин или пароль") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError("Почтовый сервер не принял адрес получателя") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Не удалось отправить письмо: {exc}") from exc


def send_mail_sync(to_email: str, subject: str, text: str, html: str | None = None) -> None:
    """Синхронная отправка — для Flask-панели, где event loop не при чём."""
    if not is_configured():
        raise MailError("Отправка почты не настроена")
    if not is_valid_email(to_email):
        raise MailError("Некорректный адрес получателя")

    _send_blocking(_build_message(to_email, subject, text, html))
    logger.info("Почта: письмо «%s» отправлено на %s", subject, to_email)


async def send_mail(to_email: str, subject: str, text: str, html: str | None = None) -> None:
    """Отправляет письмо, не занимая event loop. Бросает MailError, если не вышло."""
    await asyncio.to_thread(send_mail_sync, to_email, subject, text, html)


# ===== Готовые письма =====

def _brand() -> str:
    return _setting("smtp_from_name") or _setting("panel_brand_title") or "VPN"


def _code_html(title: str, lead: str, code: str, note: str) -> str:
    brand = _brand()
    return f"""\
<!doctype html>
<html lang="ru"><body style="margin:0;padding:24px;background:#101013;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#e9e9ee">
  <div style="max-width:460px;margin:0 auto;background:#191a1f;border:1px solid rgba(236,238,242,.08);border-radius:18px;padding:28px">
    <p style="margin:0 0 4px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#7b7d8a">{brand}</p>
    <h1 style="margin:0 0 14px;font-size:20px;font-weight:700">{title}</h1>
    <p style="margin:0 0 20px;font-size:14px;line-height:1.5;color:#9c9daa">{lead}</p>
    <div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:30px;font-weight:700;letter-spacing:.28em;
                text-align:center;padding:16px;border-radius:14px;background:rgba(215,171,255,.12);color:#d7abff">{code}</div>
    <p style="margin:20px 0 0;font-size:12px;line-height:1.5;color:#7b7d8a">{note}</p>
  </div>
</body></html>"""


async def send_verification_code(to_email: str, code: str, minutes: int) -> None:
    brand = _brand()
    note = (
        f"Код действует {minutes} мин. "
        "Если вы не создавали аккаунт, просто удалите это письмо."
    )
    text = (
        f"{brand}\n\nПодтверждение почты\n\n"
        f"Код: {code}\n\n{note}\n"
    )
    html = _code_html(
        "Подтверждение почты",
        "Введите этот код в личном кабинете, чтобы подтвердить адрес.",
        code,
        note,
    )
    await send_mail(to_email, f"{brand}: код подтверждения {code}", text, html)


async def send_password_reset_code(to_email: str, code: str, minutes: int) -> None:
    brand = _brand()
    note = (
        f"Код действует {minutes} мин. "
        "Если вы не запрашивали смену пароля, просто удалите это письмо — "
        "пароль останется прежним."
    )
    text = (
        f"{brand}\n\nВосстановление пароля\n\n"
        f"Код: {code}\n\n{note}\n"
    )
    html = _code_html(
        "Восстановление пароля",
        "Введите этот код в личном кабинете, чтобы задать новый пароль.",
        code,
        note,
    )
    await send_mail(to_email, f"{brand}: код для смены пароля {code}", text, html)


def send_test_mail_sync(to_email: str) -> None:
    brand = _brand()
    text = (
        f"{brand}\n\nПроверка отправки\n\n"
        "Если вы читаете это письмо, SMTP настроен верно.\n"
    )
    html = _code_html(
        "Проверка отправки",
        "Если вы читаете это письмо, SMTP настроен верно.",
        "OK",
        f"Письмо отправлено из панели {brand}.",
    )
    send_mail_sync(to_email, f"{brand}: проверка отправки почты", text, html)
