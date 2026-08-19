from datetime import datetime, timedelta, timezone
import os
import time

# --- TIME CONFIGURATION ---
# Force MSK (UTC+3)
os.environ['TZ'] = 'Etc/GMT-3'
if hasattr(time, 'tzset'):
    time.tzset()

def get_msk_time():
    """Returns current time in MSK (UTC+3)"""
    return datetime.now(timezone(timedelta(hours=3), name='MSK'))
# --------------------------

from aiogram import html

CHOOSE_PLAN_MESSAGE = "Выберите срок подписки."
CHOOSE_PAYMENT_METHOD_MESSAGE = "Выберите способ оплаты."
VPN_INACTIVE_TEXT = "🔴 <b>Подписка истекла.</b>"
VPN_NO_DATA_TEXT = "⚪️ <b>Активных подписок нет.</b>"

# Статусы подписки. Строки видит пользователь, поэтому лежат рядом с иконками —
# иначе они разъезжаются, как это уже было: галочка «✅» стояла в строке статуса
# всегда, даже когда подписки не было вовсе.
STATUS_ACTIVE = "активна"
STATUS_EXPIRED = "истекла"
STATUS_NONE = "нет подписок"
STATUS_ICONS = {STATUS_ACTIVE: "🟢", STATUS_EXPIRED: "🔴", STATUS_NONE: "⚪️"}


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """«1 день», «2 дня», «5 дней»."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def get_profile_text(username, user_id, total_spent, total_months, vpn_status, vpn_remaining, main_balance, referral_count, total_ref_earned, seller_info=None):
    icon = STATUS_ICONS.get(vpn_status, "⚪️")

    text = (
        f"👤 <b>{username}</b>\n"
        f"<code>{user_id}</code>\n\n"
        f"{icon} <b>Подписка:</b> {vpn_status}\n"
    )
    if vpn_status == STATUS_ACTIVE:
        text += f"<b>Осталось:</b> {vpn_remaining}\n"
    if total_months:
        text += f"<b>Оплачено:</b> {total_months} {plural(total_months, ('месяц', 'месяца', 'месяцев'))}\n"

    text += (
        f"\n<b>Баланс:</b> {main_balance:.0f} ₽\n"
        f"<b>Приглашено:</b> {referral_count} "
        f"{plural(referral_count, ('человек', 'человека', 'человек'))}\n"
        f"<b>Заработано:</b> {total_ref_earned:.2f} ₽"
    )

    if seller_info:
        s_sale = seller_info.get('sale', 0)
        s_ref = seller_info.get('ref', 0)
        s_squad = seller_info.get('squad_uuid')

        text += "\n\n👑 <b>Партнёрские условия</b>\n"
        if s_ref and float(s_ref) > 0:
            text += f"<b>Бонус за приглашённых:</b> +{s_ref}%\n"
        if s_sale and float(s_sale) > 0:
            text += f"<b>Личная скидка:</b> {s_sale}%\n"
        if s_squad and str(s_squad) != '0' and str(s_squad).strip():
            text += "<b>Отдельные серверы:</b> подключены"

    return text.rstrip()

def get_vpn_active_text(days_left, hours_left):
    if days_left <= 0:
        return f"{hours_left} {plural(hours_left, ('час', 'часа', 'часов'))}"
    return (f"{days_left} {plural(days_left, ('день', 'дня', 'дней'))} "
            f"{hours_left} {plural(hours_left, ('час', 'часа', 'часов'))}")

def _format_remaining_details(remaining: timedelta) -> str:
    total_seconds = int(remaining.total_seconds())
    if total_seconds <= 0:
        return "истекла"

    minutes = (total_seconds // 60) % 60
    hours = (total_seconds // 3600) % 24
    days = remaining.days % 365
    years = remaining.days // 365

    parts = []
    if years > 0:
        parts.append(f"{years} {plural(years, ('год', 'года', 'лет'))}")
    if days > 0:
        parts.append(f"{days} {plural(days, ('день', 'дня', 'дней'))}")
    # Часы и минуты рядом с годами не нужны — это шум, а не точность.
    if hours > 0 and years == 0:
        parts.append(f"{hours} {plural(hours, ('час', 'часа', 'часов'))}")
    if minutes > 0 and not parts:
        parts.append(f"{minutes} {plural(minutes, ('минута', 'минуты', 'минут'))}")

    return " ".join(parts) if parts else "меньше минуты"

def get_key_info_text(key_number, expiry_date, created_date, connection_string, email=None, hwid_limit=None, hwid_usage=None, traffic_limit=None, traffic_used=None, comment=None):
    now = get_msk_time().replace(tzinfo=None)
    
    # Ensure expiry_date is comparable (naive vs naive)
    if expiry_date.tzinfo:
        expiry_date = expiry_date.astimezone(get_msk_time().tzinfo).replace(tzinfo=None)
        
    remaining = expiry_date - now
    days_left = remaining.days
    
    # Цветной кружок понятен не всем и не везде: рядом ставим слово.
    status_icon, status_word = "🟢", "активна"
    remaining_str = _format_remaining_details(remaining)

    if days_left <= 10:
        status_icon, status_word = "🟡", "скоро закончится"

    if days_left < 0:
        status_icon, status_word = "🔴", "истекла"
        remaining_str = "истекла"

    hwid_block = ""
    if hwid_limit is not None:
        limit_str = str(hwid_limit)
        limit_display = "∞" if limit_str == "0" or (limit_str.isdigit() and int(limit_str) > 98) else limit_str
        hwid_block = f"{hwid_usage} / {limit_display}"

    if email and str(email).endswith("@bot.local"):
        email = str(email).replace("@bot.local", "@bot")

    comment_block = ""
    if comment:
        comment_block = f"\n📝 <b>Заметка:</b> <blockquote>{html.quote(comment)}</blockquote>"

    devices_block = f"<b>Устройства:</b> {hwid_block}\n" if hwid_block else ""

    return (
        f"{status_icon} <b>Подписка #{key_number}</b> — {status_word}\n\n"
        f"<b>Оформлена:</b> {created_date.strftime('%d.%m.%Y')}\n"
        f"<b>Действует до:</b> {expiry_date.strftime('%d.%m.%Y, %H:%M')}\n"
        f"<b>Осталось:</b> {remaining_str}\n"
        f"{devices_block}"
        f"\n<b>Ссылка подписки</b>\n"
        f"<tg-spoiler>{connection_string}</tg-spoiler>\n"
        f"<i>Нажмите, чтобы показать. Скопируйте долгим нажатием и вставьте в приложение — дальше оно подключится само.</i>"
        f"{comment_block}"
    )


def get_purchase_success_text(action: str, key_number: int, expiry_date, connection_string: str, email: str = None):
    # Заголовок раньше всегда говорил «новая подписка» — даже когда человек
    # только что продлил старую.
    title = "Подписка продлена" if action == "extend" else "Подписка готова"

    return (
        f"✅ <b>{title}</b>\n\n"
        f"<b>Действует до:</b> {expiry_date.strftime('%d.%m.%Y, %H:%M')}\n\n"
        f"<b>Ссылка подписки</b>\n"
        f"<tg-spoiler>{connection_string}</tg-spoiler>\n"
        f"<i>Нажмите, чтобы показать. Скопируйте долгим нажатием и вставьте в приложение — дальше оно подключится само.</i>"
    )