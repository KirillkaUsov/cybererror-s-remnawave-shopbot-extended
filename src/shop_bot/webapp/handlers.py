from typing import Any
from fastapi import FastAPI, Request

# Загрузка файлов требует python-multipart. Если пакета нет, приложение
# должно продолжать работать без вложений, а не падать целиком на импорте.
try:
    import python_multipart  # noqa: F401
    from fastapi import UploadFile, File, Form
    MULTIPART_AVAILABLE = True
except Exception:
    try:
        import multipart  # noqa: F401  (старое имя пакета)
        from fastapi import UploadFile, File, Form
        MULTIPART_AVAILABLE = True
    except Exception:
        MULTIPART_AVAILABLE = False
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import aiohttp
from shop_bot.data_manager.remnawave_repository import get_setting, get_user_keys, get_msk_time, get_webapp_settings, get_user, get_referral_count, get_all_hosts, list_squads, get_plans_for_host
import os
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import uuid
import asyncio
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, FSInputFile, LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder
import json
import traceback
from shop_bot.bot.keyboards import (
    create_payment_keyboard, 
    create_yoomoney_payment_keyboard, 
    create_cryptobot_payment_keyboard
)
from shop_bot.data_manager.remnawave_repository import (
    create_payload_pending, get_plan_by_id,
    deduct_from_balance, check_transaction_exists, add_to_balance, log_transaction,
    add_to_referral_balance_all, get_balance, get_all_users, is_admin, update_user_stats,
    redeem_promo_code, update_promo_code_status, record_key_from_payload, get_key_by_id,
    update_key, get_key_by_email
)
import shop_bot.data_manager.remnawave_repository as rw_repo
from shop_bot.data_manager.database import get_seller_user, get_device_tiers, get_host
from shop_bot.modules import remnawave_api
from shop_bot.config import get_purchase_success_text
import re
from decimal import Decimal
import logging
from urllib.parse import urlencode


logger = logging.getLogger(__name__)

# In-memory storage for temporary auth tokens: {token: user_id}
TEMP_AUTH_TOKENS = {}

# Привязка Telegram к веб-аккаунту: {token: {"user_id": int, "expires": float,
# "linked_to": int | None}}. Токен одноразовый и живёт 15 минут — по нему
# нельзя войти, он только разрешает боту приклеить свой чат к аккаунту.
TG_LINK_TOKENS = {}
TG_LINK_TTL_SECONDS = 900


def _purge_tg_link_tokens():
    import time as _time
    now = _time.time()
    for key in [k for k, v in TG_LINK_TOKENS.items() if v.get("expires", 0) < now]:
        TG_LINK_TOKENS.pop(key, None)

# Простая защита от спама в чат поддержки: {user_id: last_call_monotonic_ts}.
# Не переживает рестарт/несколько воркеров, но это и не нужно — цель просто
# не дать боту-скрипту засыпать админов сообщениями через мини-апп.
SUPPORT_COOLDOWN = {}
SUPPORT_COOLDOWN_SECONDS = 2.0
SUPPORT_MESSAGE_MAX_LEN = 4000


def _support_cooldown_hit(user_id: int) -> bool:
    import time
    now = time.monotonic()
    last = SUPPORT_COOLDOWN.get(user_id, 0.0)
    if now - last < SUPPORT_COOLDOWN_SECONDS:
        return True
    SUPPORT_COOLDOWN[user_id] = now
    return False


# ===== Utility Functions =====
def get_transaction_comment(user_data: dict, action_type: str, value: any, host_name: str = None) -> str:
    from shop_bot.bot.handlers import get_transaction_comment as bot_get_comment
    from aiogram.types import User
    
    # Adapt dictionary to types.User if needed by bot function
    tg_user = User(
        id=user_data.get('id', 0),
        is_bot=False,
        first_name=user_data.get('first_name', 'User'),
        username=user_data.get('username')
    )
    return bot_get_comment(tg_user, action_type, value, host_name)

def calculate_webapp_price(price: float, user_id: int) -> float:
    try:
        if not user_id or int(user_id) == 0:
            return round(price, 2)

        user = get_user(user_id)
        if not user:
            return price
        
        if user.get('seller_active'):
            seller = get_seller_user(user_id)
            if seller and seller.get('seller_sale'):
                discount_percent = float(seller['seller_sale'])
                price -= price * (discount_percent / 100)
                logger.info(f"[WEBAPP] - Применена скидка продавца {discount_percent}% для {user_id}")
        
        if user.get('referred_by') and user.get('total_spent', 0) == 0 and not get_user_keys(user_id):
            ref_discount = get_setting("referral_discount")
            if ref_discount:
                try:
                    d_val = float(ref_discount)
                    if d_val > 0:
                        price -= price * (d_val / 100)
                        logger.info(f"[WEBAPP] - Применена реферальная скидка {d_val}% для {user_id}")
                except: pass
                
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка расчета цены для {user_id}: {e}")
        
    return round(price, 2)

# ===== HELPER FUNCTIONS FOR PAYMENT PROCESS =====
async def notify_admin_of_purchase(bot: Bot, metadata: dict):
    from shop_bot.bot.handlers import notify_admin_of_purchase as bot_notify
    await bot_notify(bot, metadata)

async def process_successful_payment(bot: Bot, metadata: dict):
    from shop_bot.bot.handlers import process_successful_payment as bot_process
    await bot_process(bot, metadata)

async def _send_telegram_message(user_id: int, text: str, reply_markup=None, photo=None):
    token = get_setting("telegram_bot_token")
    if not token:
        logger.error("[WEBAPP] - Токен бота не найден в настройках")
        return False
    bot = Bot(token=token)
    try:
        if photo:
            await bot.send_photo(chat_id=user_id, photo=photo, caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="HTML")
        logger.info(f"[WEBAPP] - Сообщение успешно отправлено пользователю {user_id}")
        return True
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка отправки сообщения {user_id}: {e}")
        return False
    finally:
        await bot.session.close()

async def _send_invoice_stars(user_id: int, title: str, description: str, payload: str, amount: int):
    token = get_setting("telegram_bot_token")
    if not token:
        logger.error("[WEBAPP] - Токен бота не найден для Stars")
        return False
    bot = Bot(token=token)
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="", 
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=amount)]
        )
        logger.info(f"[WEBAPP] - Счет Stars отправлен пользователю {user_id} на сумму {amount}")
        return True
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка отправки счета Stars {user_id}: {e}")
        return False
    finally:
        await bot.session.close()


from shop_bot.modules.platega_api import PlategaAPI
from shop_bot.modules.heleket_api import create_heleket_payment_request
from shop_bot.bot.keyboards import (
    create_payment_keyboard, create_cryptobot_payment_keyboard,
    create_yoomoney_payment_keyboard
)
from shop_bot.bot.handlers import create_cryptobot_api_invoice, process_successful_payment
from yookassa import Configuration as YookassaConfiguration, Payment as YookassaPayment
from aiogram.types import BufferedInputFile
import io
import qrcode
from urllib.parse import urlencode

def _build_yoomoney_link(receiver: str, amount_rub: Decimal, label: str, description: str) -> str:
    base = "https://yoomoney.ru/quickpay/confirm.xml"
    params = {
        "receiver": (receiver or "").strip(),
        "quickpay-form": "donate",
        "targets": description[:50],
        "formcomment": description,
        "short-dest": description,
        "sum": f"{amount_rub:.2f}",
        "label": label,
        "successURL": f"https://t.me/{get_setting('telegram_bot_username')}",
    }
    return base + "?" + urlencode(params)

app = FastAPI()

ico_dir = os.path.join(os.path.dirname(__file__), "module", "ico")
if os.path.exists(ico_dir):
    app.mount("/module/ico", StaticFiles(directory=ico_dir), name="ico")

# шрифты и прочая статика раздаются с этого же домена: внешний блокирующий
# <link> на fonts.googleapis.com не давал странице отрендериться там, откуда
# до Google не дозвониться
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

def _format_remaining_details(remaining: timedelta) -> str:
    total_seconds = int(remaining.total_seconds())
    if total_seconds <= 0:
        return "0мин"

    minutes = (total_seconds // 60) % 60
    hours = (total_seconds // 3600) % 24
    days = remaining.days % 365
    years = remaining.days // 365

    parts = []
    if years > 0:
        parts.append(f"{years}г.")
    if days > 0:
        parts.append(f"{days}д.")
    if hours > 0:
        parts.append(f"{hours}ч.")
    if minutes > 0:
        parts.append(f"{minutes}мин")

    # Берем только первые две значимые части для краткости
    result_parts = parts[:2]
    return " ".join(result_parts) if result_parts else "меньше минуты"

def _format_bytes(size: Any) -> str:
    if size is None: return "0 B"
    if isinstance(size, str):
        if any(x in size for x in ['B', 'KB', 'MB', 'GB', 'TB', 'iB']):
            return size
        try: size = float(size)
        except: return "0 B"
    
    if size <= 0: return "0 B"
    power = 1024
    n = 0
    power_labels = {0 : 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < 4:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"

def _process_template_placeholders(html: str, user_id: int, webapp_settings: dict, context_data: dict) -> str:
    """
    app.html — чистый SPA-шаблон: он подставляет только эти 6 плейсхолдеров,
    остальное (профиль, ключи, каталог) клиент забирает через /api/*.
    """
    title = webapp_settings.get("webapp_title") or get_setting("panel_brand_title") or "CABINET VPN"
    support_username = get_setting("support_bot_username") or ""

    replacements = {
        "{{ panel_brand_title }}": title,
        "{{ support_bot_username }}": support_username,
        "{{ webapp_logo }}": context_data.get("webapp_logo", ""),
        "{{ webapp_icon }}": context_data.get("webapp_icon", ""),
        "{{ user_id }}": str(user_id),
        # В полноэкранном режиме Telegram рисует свои контролы поверх страницы —
        # резервируем место сверху через ту же переменную, что использует вся вёрстка.
        "{{ tg_fullscreen_css }}": """
    <style>:root{ --safe-t: max(env(safe-area-inset-top), 70px) !important; }</style>
        """ if webapp_settings.get("tg_fullscreen") else "",
    }

    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    return html

# Подписки с технической датой окончания далеко в будущем (2094, 4764 и т.п.)
# показывали «24933 дней». Всё, что дальше этого порога, считаем бессрочным.
UNLIMITED_DAYS_THRESHOLD = 1825  # 5 лет


def _process_key_data(key: dict, number: int | None = None) -> dict:
    # 1. Calculate expiry
    try:
        expire_dt = datetime.strptime(key['expiry_date'], "%Y-%m-%d %H:%M:%S")
        created_dt = datetime.strptime(key.get('created_at', key['expiry_date']), "%Y-%m-%d %H:%M:%S")
        expire_date_str = expire_dt.strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        expire_dt = datetime.now()
        created_dt = datetime.now()
        expire_date_str = "Unknown"
    
    now = get_msk_time().replace(tzinfo=None)
    
    # 2. Days left & Detailed remaining
    delta = expire_dt - now
    days_left = delta.days
    if days_left < 0:
        days_left = 0

    is_unlimited = days_left > UNLIMITED_DAYS_THRESHOLD

    remaining_str = "Бессрочно" if is_unlimited else (
        _format_remaining_details(delta) if delta.total_seconds() > 0 else "Истекла"
    )

    # 3. Progress
    total_duration = (expire_dt - created_dt).total_seconds()
    elapsed_delta = now - created_dt
    elapsed = elapsed_delta.total_seconds()
    elapsed_str = _format_remaining_details(elapsed_delta) if elapsed > 0 else "0мин"
    
    if total_duration > 0:
        percent = (elapsed / total_duration) * 100
    else:
        percent = 100
        
    percent = max(0, min(100, percent))
    percent_str = f"{percent:.1f}%"
    
    # 4. Display Name
    key_name = key.get('name')
    if not key_name:
        # Везде в интерфейсе — «подписка», а не «ключ»
        email = key.get('email') or key.get('key_email') or ""
        if email.endswith("@bot.local"):
            email = email[:-10]
        
        if number:
            key_name = f"Подписка №{number}"
        elif email:
            key_name = f"Подписка #{email}"
        elif key.get('short_uuid'):
            key_name = f"Подписка #{key.get('short_uuid')}"
        else:
            key_name = f"Подписка #{key.get('key_id')}"

    # Подпись над названием подписки — локация. Протокол тут писать незачем:
    # отдельно он не продаётся, а название подписки и так стоит рядом.
    subtitle = key.get('host_name') or ""
        
    # 5. Subscription URL
    sub_url = key.get('subscription_url') or key.get('key') or ""

    # 6. Limits
    # limit_bytes приходит из Remnawave, но если панель недоступна —
    # берём лимит из базы: колонка traffic_limit_bytes заполняется при
    # выдаче ключа и для тарифов с ограничением там реальное значение.
    traffic_limit = key.get('limit_bytes')
    if traffic_limit in (None, ''):
        traffic_limit = key.get('traffic_limit_bytes')
    traffic_used = key.get('used_bytes', 0)
    
    formatted_used = _format_bytes(traffic_used)
    
    traffic_str = "∞"
    if traffic_limit:
        try:
            t_lim_float = float(traffic_limit)
            if t_lim_float > 0:
                traffic_str = _format_bytes(t_lim_float)
            else:
                traffic_str = "∞"
        except (ValueError, TypeError):
            traffic_str = "∞"
    
    hwid_limit = key.get('limit_ips')
    hwid_usage = key.get('used_ips', 0)
    
    limit_display = "∞"
    if hwid_limit is not None:
        try:
            limit_val = int(hwid_limit)
            if limit_val > 0 and limit_val < 99:
                 limit_display = str(limit_val)
            else:
                 limit_display = "∞"
        except (ValueError, TypeError):
            limit_display = "∞"

    hwid_str = f"{hwid_usage} / {limit_display}"

    # Для билета в мини-аппе «0 / ∞ уст.» и «0 B / ∞» читаются как ошибка.
    # Когда лимита нет, честнее написать словами, а когда есть — показать
    # использование в виде «3 / 6».
    traffic_unlimited = traffic_str == "∞"
    hwid_unlimited = limit_display == "∞"

    traffic_display = "Без лимита" if traffic_unlimited else f"{formatted_used} / {traffic_str}"
    hwid_display = "Без лимита" if hwid_unlimited else f"{hwid_usage} / {limit_display}"
    
    # Safety: Created Date String
    created_date_str = created_dt.strftime("%d.%m.%Y")

    if days_left > 5:
        # статус относится к подписке — женский род
        status_text = "Бессрочная" if is_unlimited else "Активна"
        status_color = "text-emerald-500"
        status_bg = "bg-emerald-500/10"
    elif days_left > 0:
        status_text = "Истекает"
        status_color = "text-yellow-500"
        status_bg = "bg-yellow-500/10"
    else:
        status_text = "Истекла"
        status_color = "text-red-500"
        status_bg = "bg-red-500/10"

    return {
        "key_id": key.get('key_id'),
        "name": key_name,
        "number": number or 0,
        "subtitle": subtitle,
        "expire_date_str": "Бессрочно" if is_unlimited else expire_date_str,
        "days_left": days_left,
        "is_unlimited": is_unlimited,
        "traffic_display": traffic_display,
        "hwid_display": hwid_display,
        "traffic_unlimited": traffic_unlimited,
        "hwid_unlimited": hwid_unlimited,
        "percent_str": percent_str,
        "sub_url": sub_url,
        "expiry_dt": expire_dt,
        "remaining_str": remaining_str,
        "created_date_str": created_date_str,
        "elapsed_str": elapsed_str,
        "traffic_info": f"{formatted_used} / {traffic_str}", 
        "hwid_info": f"{hwid_str} уст.",
        "status_text": status_text,
        "status_color": status_color,
        "status_bg": status_bg,
        "comment_key": key.get('comment_key') or "",
        "host_name": key.get('host_name') or "",
    }


def _render_banned_page(webapp_settings: dict):
    title = webapp_settings.get("webapp_title") or get_setting("panel_brand_title") or "VPN"
    logo = webapp_settings.get("webapp_logo") or ""
    icon = webapp_settings.get("webapp_icon") or ""
    
    html = f"""<!DOCTYPE html>
<html lang="ru" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>{title}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Round" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            darkMode: 'class',
            theme: {{
                extend: {{
                    colors: {{
                        primary: '#10b981',
                        surface: {{
                            dark: '#121212',
                            card: '#1e1e1e',
                            highlight: '#2a2a2a'
                        }}
                    }}
                }}
            }}
        }}
    </script>
    <style>
        body {{ font-family: 'Inter', sans-serif; -webkit-tap-highlight-color: transparent; }}
        .glass {{ background: rgba(30, 30, 30, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.05); }}
    </style>
</head>
<body class="bg-surface-dark text-white h-screen flex flex-col items-center justify-center p-6 select-none overflow-hidden">
    <div class="fixed inset-0 pointer-events-none">
        <div class="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-primary/10 rounded-full blur-[120px]"></div>
        <div class="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-primary/5 rounded-full blur-[120px]"></div>
    </div>

    <div class="relative z-10 flex flex-col items-center text-center max-w-sm w-full">
        {f'<img src="{logo}" class="h-20 mb-8 drop-shadow-[0_0_20px_rgba(16,185,129,0.3)]">' if logo else f'<div class="w-20 h-20 bg-primary/20 rounded-3xl flex items-center justify-center mb-8 border border-primary/30 shadow-[0_0_30px_rgba(16,185,129,0.2)]"><span class="material-icons-round text-primary text-4xl">block</span></div>'}
        
        <h1 class="text-3xl font-black mb-3 tracking-tight">Доступ ограничен</h1>
        <p class="text-gray-400 font-medium leading-relaxed mb-8">
            Ваш аккаунт был заблокирован за нарушение правил сервиса. Использование функций WebApp временно недоступно.
        </p>

        <div class="glass rounded-[2rem] p-6 w-full border border-red-500/20 shadow-2xl">
            <div class="flex items-center gap-4 text-left">
                <div class="w-12 h-12 bg-red-500/10 rounded-2xl flex items-center justify-center shrink-0 border border-red-500/20">
                    <span class="material-icons-round text-red-500">lock_person</span>
                </div>
                <div>
                    <div class="text-[10px] text-gray-500 uppercase font-black tracking-widest mb-1">Статус аккаунта</div>
                    <div class="text-lg font-black text-red-500 leading-none">ЗАБЛОКИРОВАН</div>
                </div>
            </div>
            
            <div class="mt-6 pt-6 border-t border-white/5">
                <p class="text-[11px] text-gray-500 font-semibold mb-4 text-center">Если вы считаете, что это ошибка, обратитесь в нашу поддержку</p>
                <a href="https://t.me/{get_setting('support_bot_username')}" target="_blank"
                   class="flex items-center justify-center gap-2 w-full bg-white text-black py-4 rounded-2xl font-black text-sm uppercase tracking-wider hover:opacity-90 active:scale-[0.98] transition-all shadow-xl">
                    <span class="material-icons-round text-lg">headset_mic</span>
                    <span>Написать в поддержку</span>
                </a>
            </div>
        </div>

        <div class="mt-8 opacity-40 text-[10px] font-black uppercase tracking-widest flex items-center gap-2">
            <span>{title}</span>
            <span class="w-1 h-1 bg-gray-600 rounded-full"></span>
            <span>Security Module</span>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=403)


async def enrich_keys_with_live_stats(active_keys: list, user_id: int) -> None:
    """
    Дотягивает из Remnawave лимиты и расход: hwidDeviceLimit,
    trafficLimitBytes, использованный трафик и число устройств.

    Раньше этот код жил внутри _render_main_page, поэтому мини-апп,
    который берёт данные через /api/user-status, не получал лимитов
    вовсе: в таблице vpn_keys колонок limit_ips и limit_bytes нет, и
    у всех подписок бесконечный лимит показывался ошибочно.
    """
    if not active_keys:
        return

    try:
        # --- 1. Fetch Key Details (User info from Host) ---
        details_tasks = []
        for k in active_keys:
            details_tasks.append(remnawave_api.get_key_details_from_host(k))

        details_results = await asyncio.gather(*details_tasks, return_exceptions=True)

        # --- 2. Fetch Subscription Info (Traffic Stats) using UUID from Details ---
        sub_tasks = []
        # Map results to keys to keep order
        key_details_map = {}

        for k, res in zip(active_keys, details_results):
            if isinstance(res, Exception) or not res or not res.get('user'):
                sub_tasks.append(asyncio.sleep(0, None)) # Skip
                continue

            u = res['user']
            key_details_map[k['key_id']] = u

            # Update limits from user object immediately
            if u.get('trafficLimitBytes') is not None:
                k['limit_bytes'] = u.get('trafficLimitBytes')
            if u.get('hwidDeviceLimit') is not None:
                k['limit_ips'] = u.get('hwidDeviceLimit')

            if not k.get('email') and not k.get('key_email'):
                api_email = u.get('username') or u.get('email') or ''
                if api_email:
                    k['email'] = api_email
                    k['key_email'] = api_email

            # Determine UUID for subscription check
            # BOT PRIORITY: Use DB UUID first, then API response
            target_uuid = k.get('remnawave_user_uuid') or u.get('uuid')
            host = k.get('host_name')

            if target_uuid:
                sub_tasks.append(remnawave_api.get_subscription_info(str(target_uuid), host_name=host))
            else:
                sub_tasks.append(asyncio.sleep(0, None))

        sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)

        # --- 3. Process Subscription Results ---
        for k, sub_res in zip(active_keys, sub_results):
            # Try to find traffic in subscription response
            found_traffic = None
            if not isinstance(sub_res, Exception) and sub_res and isinstance(sub_res, dict):
                # check common keys
                for key_name in ['trafficUsed', 'traffic', 'used_traffic']:
                    val = sub_res.get(key_name)
                    if val is not None:
                        found_traffic = val
                        break

            if found_traffic is not None:
                k['used_bytes'] = found_traffic

            # Fallback: check User Details (u)
            if 'used_bytes' not in k:
                u = key_details_map.get(k['key_id'])
                if u:
                     # Check keys in user object
                     for key_name in ['traffic', 'trafficUsed', 'used_traffic']:
                         if u.get(key_name) is not None:
                             try: k['used_bytes'] = int(u.get(key_name)); break
                             except: pass

                     # Final fallback: sum upload + download
                     if 'used_bytes' not in k:
                         uploaded = int(u.get('upload') or 0)
                         downloaded = int(u.get('download') or 0)
                         k['used_bytes'] = uploaded + downloaded

            # HWID Usage
            u = key_details_map.get(k['key_id'])
            target_uuid = None
            if u:
                 target_uuid = u.get('uuid')
            if not target_uuid:
                 target_uuid = k.get('remnawave_user_uuid')

            host = k.get('host_name')

            if target_uuid and host:
                 try:
                      devs = await remnawave_api.get_connected_devices_count(target_uuid, host_name=host)
                      if devs and 'total' in devs:
                           k['used_ips'] = int(devs['total'])
                 except: pass
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка получения живой статистики для {user_id}: {e}")



async def _render_main_page(user_id: int):
    """
    Отдаёт SPA-оболочку app.html. Все данные (профиль, ключи, каталог)
    клиент запрашивает сам через /api/* — здесь только шапка/иконки/бренд.
    """
    webapp_settings = get_webapp_settings()

    if not webapp_settings.get("webapp_enable"):
        return HTMLResponse(content="<h1>Webapp is disabled</h1>", status_code=403)

    user = get_user(user_id)
    if user and user.get('is_banned'):
        return _render_banned_page(webapp_settings)

    p = os.path.join(os.path.dirname(__file__), "app.html")
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()

    context = {
        "webapp_logo": webapp_settings.get("webapp_logo") or "",
        "webapp_icon": webapp_settings.get("webapp_icon") or "",
    }

    content = _process_template_placeholders(content, user_id, webapp_settings, context)
    return HTMLResponse(content=content)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user_id: int | None = None, token: str | None = None):
    try:
        # 1. Authorize by Token (query param)
        if token:
            from shop_bot.data_manager import database
            user = database.get_user_by_auth_token(token)
            if user:
                user_id = user['telegram_id']
        
        # 2. If no user_id (and no valid token), serve login.html
        if user_id is None:
            p = os.path.join(os.path.dirname(__file__), "login.html")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Process placeholders for login page too
                webapp_settings = get_webapp_settings()
                context = {
                    "webapp_logo": webapp_settings.get("webapp_logo") or "",
                    "webapp_icon": webapp_settings.get("webapp_icon") or ""
                }
                content = _process_template_placeholders(content, 0, webapp_settings, context)
                return HTMLResponse(content=content)
            else:
                return HTMLResponse(content="<h1>Login page not found</h1>", status_code=404)

        webapp_settings = get_webapp_settings()
        user = get_user(user_id)
        if user and user.get('is_banned'):
            return _render_banned_page(webapp_settings)

        return await _render_main_page(user_id)

    except Exception as e:
        error_details = traceback.format_exc()
        return HTMLResponse(content=f"<h1>500 Internal Server Error</h1><pre>{error_details}</pre>", status_code=500)

# ===== API Models =====

class SupportStatusRequest(BaseModel):
    user_id: int

class SupportTicketCreateRequest(BaseModel):
    user_id: int
    subject: str

class SupportMessageSendRequest(BaseModel):
    user_id: int
    ticket_id: int
    message: str

class PaymentMethodsRequest(BaseModel):
    user_id: int

class TokenRequest(BaseModel):
    init_data: str

class TelegramDirectAuthRequest(BaseModel):
    user_id: int

class EmailAuthRequest(BaseModel):
    email: str
    password: str

class PasswordResetRequest(BaseModel):
    email: str

class PasswordResetCheckRequest(BaseModel):
    email: str
    code: str

class PasswordResetVerifyRequest(BaseModel):
    email: str
    code: str
    new_password: str

# Stores dict: { "email@bot.local": {"code": "123456", "expires": float_timestamp} }
PASSWORD_RESET_TOKENS = {}

class SyncTgRequest(BaseModel):
    token: str
    init_data: str


class DeviceTiersRequest(BaseModel):
    host_name: str

class CreatePaymentRequest(BaseModel):
    user_id: int
    payment_method: str
    plan_id: int
    host_name: str | None = None
    action: str
    key_id: int | None = None
    promo_code: str | None = None
    tier_device_count: int | None = None
    tier_price: float = 0
    # частичная оплата с баланса: остаток уходит на выбранный способ оплаты
    use_balance: bool = False

class TopUpRequest(BaseModel):
    user_id: int
    amount: float
    payment_method: str

class ApplyPromoRequest(BaseModel):
    user_id: int
    promo_code: str
    plan_id: int | None = None
    price: float | None = None

# ===== API Endpoints =====


def validate_telegram_data(init_data: str, bot_token: str) -> dict | None:
    from urllib.parse import parse_qsl, unquote
    import hmac
    import hashlib
    import json

    try:
        if not init_data or len(init_data) < 10:
            logger.warning("Telegram auth: init_data is empty or too short")
            return None

        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            logger.warning("Telegram auth: hash not found in init_data")
            return None
        
        received_hash = parsed_data.pop("hash")
        
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash == received_hash:
            user_json = parsed_data.get("user")
            if user_json:
                return json.loads(user_json)
            logger.warning("Telegram auth: hash valid but no user field")
        else:
            logger.warning(f"Telegram auth: hash mismatch. Expected={calculated_hash[:16]}... Got={received_hash[:16]}...")
        return None
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка валидации данных Telegram: {e}")
        return None

@app.get("/api/auth/request-token")
async def api_request_auth_token():
    token = str(uuid.uuid4())[:36]
    TEMP_AUTH_TOKENS[token] = None
    bot_username = (get_setting("telegram_bot_username") or "").lstrip("@")
    # универсальная ссылка, а не tg://resolve: кастомную схему iOS во встроенных
    # браузерах и в SFSafariViewController не открывает вовсе — тап не делал
    # ничего, и человек до бота не доходил
    auth_url = f"https://t.me/{bot_username}?start=auth_{token}"
    return {"ok": True, "token": token, "auth_url": auth_url}

@app.get("/api/auth/check-token/{token}")
async def api_check_auth_token(token: str):
    from shop_bot.data_manager import database
    # 1. Check in memory (waiting for bot confirmation)
    if token in TEMP_AUTH_TOKENS and TEMP_AUTH_TOKENS[token] is not None:
        user_id = TEMP_AUTH_TOKENS.pop(token)
        
        # Check existing token first
        existing_token = database.get_auth_token_by_user_id(user_id)
        if existing_token:
            return {"ok": True, "authorized": True, "user_id": user_id, "token": existing_token}
            
        # Generate persistent token
        persistent_token = str(uuid.uuid4())
        database.update_user_auth_token(user_id, persistent_token)
        return {"ok": True, "authorized": True, "user_id": user_id, "token": persistent_token}
    
    # 2. Check in DB (already authorized)
    user = database.get_user_by_auth_token(token)
    if user:
        if user.get('is_banned'):
            return {"ok": True, "authorized": False, "error": "Banned"}
        return {"ok": True, "authorized": True, "user_id": user['telegram_id'], "token": token}
    
    # 2.1 Check if user has persistent token (deep link flow edge case)
    # If the token passed is not found, it might be expired or invalid, return False
        
    return {"ok": True, "authorized": False}

@app.post("/api/auth/token")
async def api_create_token(req: TokenRequest):
    """Generate or retrieve a persistent login token using verified Telegram data."""
    token_str = get_setting("telegram_bot_token")
    if not token_str:
        return {"ok": False, "error": "Server configuration error"}

    user_data = validate_telegram_data(req.init_data, token_str)
    
    if not user_data:
        return {"ok": False, "error": "Invalid auth data"}

    user_id = user_data.get("id")
    from shop_bot.data_manager import database
    
    # Check ban status
    user = get_user(user_id)
    if user and user.get('is_banned'):
        return {"ok": False, "error": "Access denied"}
    
    # Check if user already has a persistent token
    existing_token = database.get_auth_token_by_user_id(user_id)
    if existing_token:
         return {"ok": True, "token": existing_token}
    
    # Generate new persistent token
    token = str(uuid.uuid4())
    # Ensure it's unique (highly likely with UUID4)
    database.update_user_auth_token(user_id, token)

    return {"ok": True, "token": token}


@app.post("/api/auth/telegram-direct")
async def api_telegram_direct_auth(req: TelegramDirectAuthRequest):
    from shop_bot.data_manager import database
    try:
        user = get_user(req.user_id)
        if not user:
            return {"ok": False, "error": "User not registered"}
            
        if user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        existing_token = database.get_auth_token_by_user_id(req.user_id)
        if existing_token:
            return {"ok": True, "token": existing_token}

        token = str(uuid.uuid4())
        database.update_user_auth_token(req.user_id, token)
        return {"ok": True, "token": token}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка прямой авторизации Telegram для {req.user_id}: {e}")
        return {"ok": False, "error": "Auth error"}

class SubscriptionLoginRequest(BaseModel):
    subscription_url: str


def _extract_short_uuid(raw: str) -> str | None:
    """
    Достаёт короткий идентификатор подписки из того, что вставил пользователь.
    Принимает полную ссылку (https://host/sub/XXXX), ссылку с параметрами
    и сам идентификатор, введённый вручную.
    """
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None

    # отбрасываем query и hash
    value = value.split("#", 1)[0].split("?", 1)[0].rstrip("/")

    if "/" in value:
        candidate = value.rsplit("/", 1)[-1]
    else:
        candidate = value

    candidate = candidate.strip()
    # короткий uuid Remnawave — набор латиницы и цифр
    if candidate and re.fullmatch(r"[A-Za-z0-9_-]{6,64}", candidate):
        return candidate
    return None


@app.post("/api/auth/subscription-link")
async def api_subscription_link_auth(req: SubscriptionLoginRequest):
    """Вход в кабинет по ссылке подписки."""
    from shop_bot.data_manager import database
    try:
        raw = (req.subscription_url or "").strip()
        if not raw:
            return {"ok": False, "error": "Вставьте ссылку подписки"}

        # 1) точное совпадение по полной ссылке
        key = database.get_key_by_subscription_url(raw)

        # 2) совпадение по короткому идентификатору из ссылки
        if not key:
            short_uuid = _extract_short_uuid(raw)
            if short_uuid:
                key = database.get_key_by_short_uuid(short_uuid)

        if not key:
            return {"ok": False, "error": "Подписка не найдена. Проверьте ссылку и попробуйте снова."}

        user_id = key.get("user_id")
        if not user_id:
            return {"ok": False, "error": "Подписка не привязана к аккаунту"}

        user = get_user(user_id)
        if not user:
            return {"ok": False, "error": "Аккаунт не найден"}
        if user.get("is_banned"):
            return {"ok": False, "error": "Доступ закрыт"}

        existing_token = database.get_auth_token_by_user_id(user_id)
        if existing_token:
            logger.info(f"[WEBAPP] - Вход по ссылке подписки: пользователь {user_id}")
            return {"ok": True, "token": existing_token, "user_id": user_id}

        token = str(uuid.uuid4())
        database.update_user_auth_token(user_id, token)
        logger.info(f"[WEBAPP] - Вход по ссылке подписки: пользователь {user_id} (новый токен)")
        return {"ok": True, "token": token, "user_id": user_id}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка входа по ссылке подписки: {e}")
        return {"ok": False, "error": "Внутренняя ошибка сервера"}


def _validate_password(password: str) -> str | None:
    if len(password) < 5:
        return "Пароль должен содержать минимум 5 символов"
    if password.isdigit():
        return "Пароль не должен состоять только из цифр"
    if len(set(password)) < 2:
        return "Пароль слишком простой — используйте разные символы"
    return None

@app.post("/api/auth/email/register")
async def api_email_register(req: EmailAuthRequest):
    from shop_bot.data_manager import database
    existing = database.get_user_by_email(req.email)
    if existing:
        return {"ok": False, "error": "Email уже зарегистрирован"}
        
    pw_err = _validate_password(req.password)
    if pw_err:
        return {"ok": False, "error": pw_err}
    user = database.create_user_by_email(req.email, req.password)
    if not user:
        return {"ok": False, "error": "Ошибка при регистрации"}
        
    token = str(uuid.uuid4())
    database.update_user_auth_token(user['telegram_id'], token)
    return {"ok": True, "token": token}

@app.post("/api/auth/email/login")
async def api_email_login(req: EmailAuthRequest):
    from shop_bot.data_manager import database
    user = database.get_user_by_email(req.email)
    if not user or user.get('auth_pass') != req.password:
        return {"ok": False, "error": "Неверный email или пароль"}
        
    if user.get('is_banned'):
        return {"ok": False, "error": "Аккаунт заблокирован"}

    token = str(uuid.uuid4())
    database.update_user_auth_token(user['telegram_id'], token)
    return {"ok": True, "token": token}

@app.post("/api/auth/email/reset/request")
async def api_email_reset_request(req: PasswordResetRequest):
    from shop_bot.data_manager import database
    user = database.get_user_by_email(req.email)
    if not user:
        return {"ok": False, "error": "Email не найден"}
        
    if str(user['telegram_id']).startswith("999"):
        return {"ok": False, "error": "Аккаунт не синхронизирован с Telegram.\nОтправить сообщение невозможно!"}

    import random
    import time
    code = str(random.randint(100000, 999999))
    PASSWORD_RESET_TOKENS[req.email.lower().strip()] = {
        "code": code,
        "expires": time.time() + 600
    }
    
    try:
        success = await _send_telegram_message(
            user['telegram_id'], 
            f"🔐 <b>Восстановление пароля</b>\n\nВаш код для сброса безопасности:\n<code>{code}</code>\n\n<i>Код действителен 10 минут. Если вы не запрашивали сброс пароля, проигнорируйте это сообщение.</i>"
        )
        if not success:
            return {"ok": False, "error": "Ошибка при отправке в Telegram. Возможно, вы заблокировали бота."}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка вызова _send_telegram_message для {req.email}: {e}")
        return {"ok": False, "error": "Ошибка при отправке в Telegram. Возможно, вы заблокировали бота."}

    return {"ok": True}

@app.post("/api/auth/email/reset/check")
async def api_email_reset_check(req: PasswordResetCheckRequest):
    import time
    email_lower = req.email.lower().strip()
    if email_lower not in PASSWORD_RESET_TOKENS:
        return {"ok": False, "error": "Код не запрашивался или истёк"}
        
    token_data = PASSWORD_RESET_TOKENS[email_lower]
    if time.time() > token_data["expires"]:
        return {"ok": False, "error": "Код устарел"}
        
    if token_data["code"] != req.code:
        return {"ok": False, "error": "Неверный код"}
        
    return {"ok": True}

@app.post("/api/auth/email/reset/verify")
async def api_email_reset_verify(req: PasswordResetVerifyRequest):
    import time
    email_lower = req.email.lower().strip()
    if email_lower not in PASSWORD_RESET_TOKENS:
        return {"ok": False, "error": "Код не запрашивался или истёк"}
        
    token_data = PASSWORD_RESET_TOKENS[email_lower]
    if time.time() > token_data["expires"]:
        del PASSWORD_RESET_TOKENS[email_lower]
        return {"ok": False, "error": "Код устарел"}
        
    if token_data["code"] != req.code:
        return {"ok": False, "error": "Неверный код"}
        
    from shop_bot.data_manager import database
    pw_err = _validate_password(req.new_password)
    if pw_err:
        return {"ok": False, "error": pw_err}
    if not database.update_user_password(req.email, req.new_password):
        return {"ok": False, "error": "Ошибка базы данных"}
        
    del PASSWORD_RESET_TOKENS[email_lower]
    return {"ok": True}

@app.post("/api/auth/sync-tg")
async def api_sync_tg(req: SyncTgRequest):
    from shop_bot.data_manager import database
    user = database.get_user_by_auth_token(req.token)
    if not user:
        return {"ok": False, "error": "Не авторизован"}
        
    token_str = get_setting("telegram_bot_token")
    if not token_str:
         return {"ok": False, "error": "Server configuration error"}
         
    tg_data = validate_telegram_data(req.init_data, token_str)
    if not tg_data or not tg_data.get('id'):
         return {"ok": False, "error": "Invalid Telegram data"}
         
    tg_id = tg_data.get('id')
    tg_username = tg_data.get('username') or ''
    
    from shop_bot.data_manager.database import is_telegram_account
    if is_telegram_account(user):
         return {"ok": False, "error": "Telegram уже привязан"}
         
    res = database.link_telegram_to_email_user(user['telegram_id'], tg_id, tg_username)
    if res is True:
         return {"ok": True}
    else:
         return {"ok": False, "error": str(res)}


class TgLinkStartRequest(BaseModel):
    user_id: int


@app.post("/api/tg-link/start")
async def api_tg_link_start(req: TgLinkStartRequest):
    """
    Готовит ссылку «привязать Telegram» для аккаунта, заведённого по email
    или по ссылке подписки.

    В браузере initData от Telegram взять неоткуда, поэтому привязку
    подтверждает сам бот: пользователь открывает диплинк, бот видит его
    telegram_id и склеивает аккаунты. Токен здесь одноразовый и не является
    токеном входа — по нему нельзя авторизоваться, только привязаться.
    """
    import time as _time
    from shop_bot.data_manager.database import is_telegram_account
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}
        if is_telegram_account(user):
            return {"ok": False, "error": "Telegram уже привязан"}

        bot_username = (get_setting("telegram_bot_username") or "").lstrip("@")
        if not bot_username:
            return {"ok": False, "error": "Бот не настроен"}

        _purge_tg_link_tokens()
        token = str(uuid.uuid4())
        TG_LINK_TOKENS[token] = {
            "user_id": int(req.user_id),
            "expires": _time.time() + TG_LINK_TTL_SECONDS,
            "linked_to": None,
        }
        payload = f"link_{token}"
        return {
            "ok": True,
            "token": token,
            "url": f"https://t.me/{bot_username}?start={payload}",
            "deep_link": f"tg://resolve?domain={bot_username}&start={payload}",
        }
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка подготовки привязки Telegram для {req.user_id}: {e}")
        return {"ok": False, "error": "Не удалось начать привязку"}


@app.get("/api/tg-link/check/{token}")
async def api_tg_link_check(token: str):
    """Опрос из мини-аппа: подтвердил ли бот привязку."""
    _purge_tg_link_tokens()
    data = TG_LINK_TOKENS.get(token)
    if not data:
        return {"ok": True, "linked": False, "expired": True}
    if data.get("linked_to"):
        TG_LINK_TOKENS.pop(token, None)
        return {"ok": True, "linked": True, "user_id": data["linked_to"]}
    return {"ok": True, "linked": False, "expired": False}


@app.post("/api/device-tiers")
async def api_device_tiers(req: DeviceTiersRequest):
    try:
        host_data = get_host(req.host_name)
        if not host_data:
            return {"ok": True, "device_mode": "plan", "tiers": [], "tier_lock_extend": 0}
        mode = host_data.get('device_mode', 'plan')
        lock = int(host_data.get('tier_lock_extend', 0) or 0)
        from shop_bot.data_manager import database
        base_devices = int(database.get_setting(f"base_device_{req.host_name}", "1"))
        tiers = []
        if mode == 'tiers':
            raw = get_device_tiers(req.host_name)
            tiers = [{"tier_id": t["tier_id"], "device_count": t["device_count"], "price": float(t["price"])} for t in raw]
        return {"ok": True, "device_mode": mode, "tiers": tiers, "tier_lock_extend": lock, "base_device_count": base_devices}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка API device-tiers для {req.host_name}: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/payment-methods")
async def api_get_payment_methods(req: PaymentMethodsRequest):
    user_id = req.user_id
    user = get_user(user_id)
    
    methods = []
    
    # 1. YooKassa
    if (get_setting("yookassa_shop_id") or "") and (get_setting("yookassa_secret_key") or ""):
        label = "Банковская карта"
        if (get_setting("sbp_enabled") or "false").strip().lower() == "true":
            label = "СБП / Банковская карта"
        methods.append({"id": "pay_yookassa", "name": label, "icon": "credit_card"})

    # 2. Platega
    if (get_setting("platega_enabled") or "false").strip().lower() == "true":
        methods.append({"id": "pay_platega", "name": "СБП / Platega", "icon": "payments"})
    if (get_setting("platega_crypto_enabled") or "false").strip().lower() == "true":
        methods.append({"id": "pay_platega_crypto", "name": "Крипта / Platega", "icon": "payments"})

    # 3. CryptoBot
    if get_setting("cryptobot_token"):
        methods.append({"id": "pay_cryptobot", "name": "Криптовалюта", "icon": "currency_bitcoin"})
    # 3.1 Heleket (alternative crypto)
    elif (get_setting("heleket_merchant_id") or "") and (get_setting("heleket_api_key") or ""):
        methods.append({"id": "pay_heleket", "name": "Криптовалюта", "icon": "currency_bitcoin"})

    # 4. TON Connect
    if (get_setting("ton_wallet_address") or "") and (get_setting("tonapi_key") or ""):
        methods.append({"id": "pay_tonconnect", "name": "TON Connect", "icon": "wallet"})

    # 5. Telegram Stars
    if (get_setting("stars_enabled") or "false").strip().lower() == "true":
        methods.append({"id": "pay_stars", "name": "Telegram Stars", "icon": "star"})

    # 6. YooMoney
    if (get_setting("yoomoney_enabled") or "false").strip().lower() == "true":
        methods.append({"id": "pay_yoomoney", "name": "ЮMoney (кошелёк)", "icon": "account_balance_wallet"})

    # 7. Balance
    balance = float(user.get('balance', 0)) if user else 0
    methods.append({"id": "pay_balance", "name": "Баланс", "icon": "account_balance", "balance": balance})

    return {"ok": True, "methods": methods, "balance": balance}


@app.post("/api/create-payment")
async def api_create_payment(req: CreatePaymentRequest):
    try:
        user_id = req.user_id
        plan_id = req.plan_id
        method_id = req.payment_method
        
        plan = get_plan_by_id(plan_id)
        if not plan:
            logger.warning(f"[WEBAPP] - Тариф {plan_id} не найден для пользователя {user_id}")
            return {"ok": False, "error": "Тариф не найден"}

        logger.info(f"[WEBAPP] - Начало создания платежа: User={user_id}, Plan={plan_id}, Method={method_id}")

        user = get_user(user_id)
        if not user:
            logger.warning(f"[WEBAPP] - Пользователь {user_id} не найден при создании платежа")
            return {"ok": False, "error": "Пользователь не найден (ID: " + str(user_id) + ")"}
        
        final_price = calculate_webapp_price(float(plan['price']), user_id) 
        
        months = int(plan.get('months') or 1)
        
        tier_device_count = req.tier_device_count
        tier_price_per_month = req.tier_price
        
        if tier_price_per_month == 0:
            tier_device_count = None
        
        if req.action == 'extend' and req.key_id:
            host_data = get_host(req.host_name) if req.host_name else None
            if host_data and host_data.get('device_mode') == 'tiers' and int(host_data.get('tier_lock_extend', 0) or 0):
                key = get_key_by_id(req.key_id)
                if key and key.get('remnawave_user_uuid'):
                    try:
                        user_info = await remnawave_api.get_user_by_uuid(key['remnawave_user_uuid'], host_name=req.host_name)
                        if user_info:
                            old_hwid = int(user_info.get('hwidDeviceLimit') or 1)
                            if not tier_price_per_month:
                                if old_hwid > 1:
                                    from shop_bot.data_manager import database
                                    base_devices = int(database.get_setting(f"base_device_{req.host_name}", "1"))
                                    tiers = get_device_tiers(req.host_name)
                                    for t in tiers:
                                        if t['device_count'] == old_hwid:
                                            tier_device_count = old_hwid
                                            diff = old_hwid - base_devices
                                            if diff < 0: diff = 0
                                            tier_price_per_month = float(diff * t['price'])
                                            break
                            elif tier_device_count and int(tier_device_count) > old_hwid:
                                from shop_bot.data_manager import database
                                base_devices = int(database.get_setting(f"base_device_{req.host_name}", "1"))
                                tiers = get_device_tiers(req.host_name)
                                old_tier_price = 0.0
                                new_tier_price = 0.0
                                for t in tiers:
                                    if t['device_count'] == old_hwid:
                                        old_tier_price = float(t['price'])
                                    if t['device_count'] == int(tier_device_count):
                                        new_tier_price = float(t['price'])
                                old_diff = max(0, old_hwid - base_devices)
                                new_diff = max(0, int(tier_device_count) - base_devices)
                                old_total_tier_price = old_diff * old_tier_price
                                new_total_tier_price = new_diff * new_tier_price
                                monthly_diff_price = max(0.0, new_total_tier_price - old_total_tier_price)
                                if key.get('expiry_date') and monthly_diff_price > 0:
                                    expire_dt = datetime.strptime(key['expiry_date'], "%Y-%m-%d %H:%M:%S")
                                    now = get_msk_time().replace(tzinfo=None)
                                    days_left = (expire_dt - now).days
                                    if days_left > 0:
                                        remaining_months = float(days_left) / 30.0
                                        device_surcharge = monthly_diff_price * remaining_months
                                        final_price += device_surcharge
                    except Exception as e:
                        logger.error(f"[WEBAPP] - Ошибка HWID: {e}")
        
        if tier_price_per_month > 0:
            final_price += tier_price_per_month * months
            
        # --- APPLY PROMO DISCOUNT ---
        if req.promo_code:
            promo, error = rw_repo.check_promo_code_available(req.promo_code, user_id)
            if promo and promo.get('promo_type') == 'discount':
                if promo.get('discount_percent'):
                    final_price -= final_price * (float(promo['discount_percent']) / 100)
                elif promo.get('discount_amount'):
                    final_price -= float(promo['discount_amount'])
                final_price = max(0, round(final_price, 2))

        # --- ЧАСТИЧНАЯ ОПЛАТА С БАЛАНСА ---
        # Баланс списывается не сейчас, а когда платёж подтвердится
        # (process_successful_payment), иначе брошенный счёт съедал бы деньги.
        balance_spend = 0.0
        if req.use_balance and method_id != "pay_balance":
            available = float(get_balance(user_id) or 0)
            balance_spend = round(min(available, float(final_price)), 2)
            if balance_spend > 0:
                remainder = round(float(final_price) - balance_spend, 2)
                if remainder <= 0:
                    # баланса хватает на весь заказ — обычная оплата с баланса
                    method_id = "pay_balance"
                    balance_spend = 0.0
                else:
                    if remainder < 1:
                        # у платёжек есть минимальная сумма счёта
                        balance_spend = round(max(0.0, float(final_price) - 1), 2)
                        remainder = round(float(final_price) - balance_spend, 2)
                    final_price = remainder
                    logger.info(f"[WEBAPP] - Частичная оплата балансом: User={user_id}, с баланса={balance_spend}, к оплате={final_price}")

        def _pending(pid: str, meta: dict) -> dict:
            if balance_spend > 0:
                meta["balance_spend"] = balance_spend
            _pending(pid, meta)
            return meta

        action_name = req.action

        # --- YooKassa ---
        if method_id == "pay_yookassa":
            shop_id, secret = get_setting("yookassa_shop_id"), get_setting("yookassa_secret_key")
            if not shop_id or not secret: return {"ok": False, "error": "YooKassa не настроена"}
            YookassaConfiguration.account_id = shop_id
            YookassaConfiguration.secret_key = secret
            pid = str(uuid.uuid4())
            meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "YooKassa", "payment_id": pid,
                "tier_device_count": tier_device_count
            }
            _pending(pid, meta)
            comment = get_transaction_comment({"id": user_id, "username": user.get("username")}, action_name, months, req.host_name)
            payload = {
                "amount": {"value": f"{final_price:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/{get_setting('telegram_bot_username')}"},
                "capture": True, "description": comment, "metadata": meta
            }
            try:
                pay_obj = YookassaPayment.create(payload, pid)
                pay_url = pay_obj.confirmation.confirmation_url
                
                kb = create_payment_keyboard(pay_url)
                await _send_telegram_message(user_id, f"<b>Оплата через ЮKassa</b>\n\nСумма: <b>{final_price:.2f} RUB</b>\n\n<i>Вы можете оплатить счет здесь или в WebApp.</i>", kb)
                
                logger.info(f"[WEBAPP] - Успешно создан счет YooKassa для {user_id}: {pid}")
                return {"ok": True, "payment_url": pay_url, "payment_id": pid, "message": "Счёт создан"}
            except Exception as e:
                logger.error(f"[WEBAPP] - Ошибка YooKassa для {user_id}: {e}")
                return {"ok": False, "error": f"Ошибка YooKassa: {e}"}

        # --- Platega ---
        elif method_id == "pay_platega":
            mid, key = get_setting("platega_merchant_id"), get_setting("platega_api_key")
            if not mid or not key: return {"ok": False, "error": "Platega не настроена"}
            pid = str(uuid.uuid4())
            meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "Platega", "payment_id": pid,
                "tier_device_count": tier_device_count
            }
            _pending(pid, meta)
            desc = f"Order {pid}"
            try:
                platega = PlategaAPI(mid, key)
                _, url = await platega.create_payment(float(final_price), desc, pid, f"https://t.me/{get_setting('telegram_bot_username')}", f"https://t.me/{get_setting('telegram_bot_username')}", 2)
                if url:
                    kb = create_payment_keyboard(url)
                    await _send_telegram_message(user_id, f"<b>Оплата через Platega</b>\n\nСумма: <b>{final_price:.2f} RUB</b>\n\n<i>Счет также доступен в WebApp.</i>", kb)
                    return {"ok": True, "payment_url": url, "payment_id": pid, "message": "Счёт создан"}
                return {"ok": False, "error": "Ошибка получения ссылки Platega"}
            except Exception as e:
                return {"ok": False, "error": f"Ошибка Platega: {e}"}

        # --- Platega Crypto ---
        elif method_id == "pay_platega_crypto":
            mid, key = get_setting("platega_merchant_id"), get_setting("platega_api_key")
            if not mid or not key: return {"ok": False, "error": "Platega не настроена"}
            pid = str(uuid.uuid4())
            meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "Platega Crypto", "payment_id": pid,
                "tier_device_count": tier_device_count
            }
            _pending(pid, meta)
            desc = f"Order {pid}"
            try:
                platega = PlategaAPI(mid, key)
                _, url = await platega.create_payment(float(final_price), desc, pid, f"https://t.me/{get_setting('telegram_bot_username')}", f"https://t.me/{get_setting('telegram_bot_username')}", 13)
                if url:
                    kb = create_payment_keyboard(url)
                    await _send_telegram_message(user_id, f"<b>Оплата через Platega (Crypto)</b>\n\nСумма: <b>{final_price:.2f} RUB</b>\n\n<i>Счет также доступен в WebApp.</i>", kb)
                    return {"ok": True, "payment_url": url, "payment_id": pid, "message": "Счёт создан"}
                return {"ok": False, "error": "Ошибка получения ссылки Platega Crypto"}
            except Exception as e:
                 return {"ok": False, "error": f"Ошибка Platega Crypto: {e}"}

         # --- CryptoBot ---
        elif method_id == "pay_cryptobot":
             pid = str(uuid.uuid4())
             meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "CryptoBot", "payment_id": pid,
                "tier_device_count": tier_device_count
            }
             _pending(pid, meta)
             # payload_str format MUST match what bot expects. Using a generic format for now or just ID
             # safe encoded payload
             payload_str = f"{pid}" 
             
             try:
                 # Note: create_cryptobot_api_invoice IS imported now
                 res = await create_cryptobot_api_invoice(amount=float(final_price), payload_str=payload_str)
                 if res:
                     # res[0] is url, res[1] is invoice_id
                     kb = create_cryptobot_payment_keyboard(res[0], res[1])
                     await _send_telegram_message(user_id, f"<b>Оплата через CryptoBot</b>\n\nСумма: <b>{final_price:.2f} RUB</b>\n\n<i>Счет также доступен в WebApp.</i>", kb)
                     logger.info(f"[WEBAPP] - Успешно создан счет CryptoBot для {user_id}: {pid}")
                     return {"ok": True, "payment_url": res[0], "payment_id": pid, "message": "Счёт создан"}
                 logger.error(f"[WEBAPP] - Ошибка API CryptoBot для {user_id}")
                 return {"ok": False, "error": "Ошибка API CryptoBot"}
             except Exception as e:
                 return {"ok": False, "error": f"Ошибка CryptoBot: {e}"}
             
        # --- Heleket ---
        elif method_id == "pay_heleket":
            pid = str(uuid.uuid4())
            meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "Heleket", "payment_id": pid,
                "tier_device_count": tier_device_count
            }
            _pending(pid, meta)
            
            try:
                result = await create_heleket_payment_request(
                    amount=float(final_price), 
                    currency="RUB", 
                    description=f"Payment for {req.host_name}",
                    return_url=f"https://t.me/{get_setting('telegram_bot_username')}",
                    user_id=user_id,
                    email=user.get('email', 'no-email')
                )
                
                if result and result.get('payment_url'):
                    pay_url = result['payment_url']
                    kb = create_payment_keyboard(pay_url)
                    await _send_telegram_message(user_id, f"<b>Оплата через Crypto (Heleket)</b>\n\nСумма: <b>{final_price:.2f} RUB</b>", kb)
                    return {"ok": True, "payment_url": pay_url, "payment_id": pid}
                else:
                     return {"ok": False, "error": "Ошибка создания платежа Heleket"}

            except Exception as e:
                logger.error(f"[WEBAPP] - Ошибка Heleket для {user_id}: {e}")
                return {"ok": False, "error": f"Ошибка Heleket: {e}"}
                
        # --- YooMoney ---
        elif method_id == "pay_yoomoney":
             receiver = get_setting("yoomoney_receiver")
             if not receiver: return {"ok": False, "error": "YooMoney не настроен"}
             pid = str(uuid.uuid4())
             meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "YooMoney", "payment_id": pid,
                "tier_device_count": tier_device_count
            }
             _pending(pid, meta)
             label = pid
             desc = get_transaction_comment({"id": user_id, "username": user.get("username")}, action_name, months, req.host_name)
             link = _build_yoomoney_link(receiver, Decimal(str(final_price)), label, desc)
             
             kb = create_yoomoney_payment_keyboard(link, pid)
             await _send_telegram_message(user_id, f"<b>Оплата через ЮMoney (кошелёк)</b>\n\nСумма: <b>{final_price:.2f} RUB</b>\n\n<i>Счет также доступен в WebApp.</i>", kb)
             
             return {"ok": True, "payment_url": link, "payment_id": pid, "message": "Счёт создан"}

        # --- TON Connect ---
        elif method_id == "pay_tonconnect":
             return {"ok": False, "error": "TON Connect пока недоступен через WebApp"}

        # --- Stars ---
        elif method_id == "pay_stars":
             try:
                stars_ratio = float(get_setting("stars_per_rub") or 0)
             except: stars_ratio = 0
             if stars_ratio <= 0: return {"ok": False, "error": "Stars отключены"}
             stars_amount = max(1, int((final_price * stars_ratio)))
             pid = str(uuid.uuid4())
             meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "Telegram Stars", "payment_id": pid,
                "tier_device_count": tier_device_count
            }
             _pending(pid, meta)
             title = f"{'Подписка' if action_name == 'new' else 'Продление'} на {months} мес."
             desc = get_transaction_comment({"id": user_id, "username": user.get("username")}, action_name, months, req.host_name)
             await _send_invoice_stars(user_id, title, desc, pid, stars_amount)
             bot_username = get_setting('telegram_bot_username')
             logger.info(f"[WEBAPP] - Успешно отправлен счет Stars для {user_id} на {stars_amount} звезд")
             return {"ok": True, "message": "Счёт Stars отправлен в бот", "payment_url": f"tg://resolve?domain={bot_username}"}

        # --- Balance ---
        elif method_id == "pay_balance":
            if not deduct_from_balance(user_id, float(final_price)):
                return {"ok": False, "error": "Недостаточно средств"}
                
            p_log_id = str(uuid.uuid4())
            meta = {
                "user_id": user_id, "months": months, "price": float(final_price),
                "action": action_name, "key_id": req.key_id, "host_name": req.host_name,
                "plan_id": plan_id, "payment_method": "Balance", "promo_code": "", "promo_discount": 0,
                "tier_device_count": tier_device_count,
                "payment_id": p_log_id
            }
            token = get_setting("telegram_bot_token")
            bot = Bot(token=token) if token else None
            
            success = False
            if bot:
                try:
                    res = await asyncio.wait_for(process_successful_payment(bot, meta), timeout=15.0)
                    if res is True or check_transaction_exists(p_log_id):
                        success = True
                except asyncio.TimeoutError:
                    logger.warning("Способ 1: Таймаут бота")
                    if check_transaction_exists(p_log_id):
                        success = True
                except Exception as e:
                    logger.error(f"Способ 1 ошибка: {e}")
                    if check_transaction_exists(p_log_id):
                        success = True
            
            if not success and not check_transaction_exists(p_log_id):
                logger.info("Способ 2: Создаем ключ независимо от бота")
                try:
                    res = await process_successful_payment(None, meta)
                    if res is True or check_transaction_exists(p_log_id):
                        success = True
                except Exception as e:
                    logger.error(f"Способ 2 ошибка: {e}")
                    
            if bot:
                await bot.session.close()
                
            if not success and not check_transaction_exists(p_log_id):
                logger.error(f"[WEBAPP] - Критическая ошибка списания с баланса для {user_id}")
                return {"ok": False, "error": "Ошибка обработки платежа"}
                
            logger.info(f"[WEBAPP] - Успешная оплата с баланса: User={user_id}, Sum={final_price}")
            return {"ok": True, "message": "Оплачено с баланса!", "paid": True}

        return {"ok": False, "error": "Метод не поддерживается"}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка API создания платежа: {e}")
        return {"ok": False, "error": str(e), "details": traceback.format_exc()}

TOPUP_MIN = 10.0
TOPUP_MAX = 100000.0


@app.post("/api/topup/create")
async def api_topup_create(req: TopUpRequest):
    """Счёт на пополнение баланса. Метаданные те же, что у бота (action=top_up),
    поэтому вебхуки зачисляют деньги существующим кодом."""
    try:
        user_id = req.user_id
        user = get_user(user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        try:
            amount = round(float(req.amount), 2)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Некорректная сумма"}
        if amount < TOPUP_MIN:
            return {"ok": False, "error": f"Минимальная сумма пополнения — {TOPUP_MIN:.0f} ₽"}
        if amount > TOPUP_MAX:
            return {"ok": False, "error": f"Максимальная сумма пополнения — {TOPUP_MAX:.0f} ₽"}

        method_id = req.payment_method
        pid = str(uuid.uuid4())
        meta = {
            "user_id": user_id, "months": 0, "price": amount,
            "action": "top_up", "key_id": None, "host_name": None,
            "plan_id": None, "payment_method": "", "payment_id": pid,
        }
        comment = get_transaction_comment({"id": user_id, "username": user.get("username")}, 'topup', f"{amount:.2f}")
        note = f"<b>Пополнение баланса</b>\n\nСумма: <b>{amount:.2f} RUB</b>"

        if method_id == "pay_yookassa":
            shop_id, secret = get_setting("yookassa_shop_id"), get_setting("yookassa_secret_key")
            if not shop_id or not secret:
                return {"ok": False, "error": "YooKassa не настроена"}
            YookassaConfiguration.account_id = shop_id
            YookassaConfiguration.secret_key = secret
            meta["payment_method"] = "YooKassa"
            create_payload_pending(pid, user_id, amount, meta)
            payload = {
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/{get_setting('telegram_bot_username')}"},
                "capture": True, "description": comment, "metadata": meta,
            }
            pay_obj = YookassaPayment.create(payload, pid)
            url = pay_obj.confirmation.confirmation_url

        elif method_id in ("pay_platega", "pay_platega_crypto"):
            mid, key = get_setting("platega_merchant_id"), get_setting("platega_api_key")
            if not mid or not key:
                return {"ok": False, "error": "Platega не настроена"}
            crypto = method_id.endswith("crypto")
            meta["payment_method"] = "Platega Crypto" if crypto else "Platega"
            create_payload_pending(pid, user_id, amount, meta)
            back = f"https://t.me/{get_setting('telegram_bot_username')}"
            _, url = await PlategaAPI(mid, key).create_payment(amount, f"Topup {pid}", pid, back, back, 13 if crypto else 2)
            if not url:
                return {"ok": False, "error": "Не удалось получить ссылку Platega"}

        elif method_id == "pay_cryptobot":
            if not get_setting("cryptobot_token"):
                return {"ok": False, "error": "CryptoBot не настроен"}
            meta["payment_method"] = "CryptoBot"
            create_payload_pending(pid, user_id, amount, meta)
            res = await create_cryptobot_api_invoice(amount=amount, payload_str=pid)
            if not res:
                return {"ok": False, "error": "Ошибка API CryptoBot"}
            url = res[0]

        elif method_id == "pay_heleket":
            meta["payment_method"] = "Heleket"
            create_payload_pending(pid, user_id, amount, meta)
            res = await create_heleket_payment_request(
                amount=amount, currency="RUB", description="Balance top up",
                return_url=f"https://t.me/{get_setting('telegram_bot_username')}",
                user_id=user_id, email=user.get('email', 'no-email'),
            )
            url = (res or {}).get('payment_url')
            if not url:
                return {"ok": False, "error": "Ошибка создания платежа Heleket"}

        elif method_id == "pay_yoomoney":
            receiver = get_setting("yoomoney_receiver")
            if not receiver:
                return {"ok": False, "error": "YooMoney не настроен"}
            meta["payment_method"] = "YooMoney"
            create_payload_pending(pid, user_id, amount, meta)
            url = _build_yoomoney_link(receiver, Decimal(str(amount)), pid, comment)

        elif method_id == "pay_stars":
            try:
                stars_ratio = float(get_setting("stars_per_rub") or 0)
            except (TypeError, ValueError):
                stars_ratio = 0
            if stars_ratio <= 0:
                return {"ok": False, "error": "Stars отключены"}
            meta["payment_method"] = "Telegram Stars"
            create_payload_pending(pid, user_id, amount, meta)
            await _send_invoice_stars(user_id, "Пополнение баланса", comment, pid, max(1, int(amount * stars_ratio)))
            return {"ok": True, "payment_id": pid, "message": "Счёт Stars отправлен в бот",
                    "payment_url": f"tg://resolve?domain={get_setting('telegram_bot_username')}"}

        else:
            return {"ok": False, "error": "Этот способ не подходит для пополнения"}

        await _send_telegram_message(user_id, note, create_payment_keyboard(url))
        logger.info(f"[WEBAPP] - Создан счёт на пополнение: User={user_id}, Sum={amount}, Method={method_id}")
        return {"ok": True, "payment_url": url, "payment_id": pid, "message": "Счёт создан"}

    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка создания пополнения для {req.user_id}: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/api/apply-promo")
async def api_apply_promo(req: ApplyPromoRequest):
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}
        user_id = req.user_id
        code = req.promo_code.strip().upper()
        
        promo, error = rw_repo.check_promo_code_available(code, user_id)
        if not promo:
            errors = {
                "not_found": "Промокод не найден",
                "inactive": "Промокод не активен",
                "not_started": "Акция еще не началась",
                "expired": "Срок действия промокода истек",
                "total_limit_reached": "Промокод закончился",
                "user_limit_reached": "Вы уже использовали этот промокод",
                "empty_code": "Введите промокод"
            }
            return {"ok": False, "error": errors.get(error, "Ошибка проверки промокода")}

        promo_type = promo.get('promo_type')
        
        # 1. DISCOUNT (For Payment Modal)
        if promo_type == 'discount':
            if req.price is None:
                return {"ok": False, "error": "Промокод действителен только при покупке"}
            
            new_price = float(req.price)
            if promo.get('discount_percent'):
                new_price -= new_price * (float(promo['discount_percent']) / 100)
            elif promo.get('discount_amount'):
                new_price -= float(promo['discount_amount'])
            
            return {
                "ok": True, 
                "promo_type": "discount", 
                "new_price": max(0, round(new_price, 2))
            }

        # 2. BALANCE or UNIVERSAL (For Profile)
        elif promo_type == 'balance':
            reward = float(promo.get('reward_value', 0))
            if rw_repo.adjust_user_balance(user_id, reward):
                rw_repo.redeem_universal_promo(code, user_id)
                return {"ok": True, "promo_type": "balance", "message": f"Зачислено {reward} ₽"}
            return {"ok": False, "error": "Ошибка начисления баланса"}

        elif promo_type == 'universal':
            days_to_add = int(promo.get('reward_value') or 0)
            keys = rw_repo.get_user_keys(user_id)
            if not keys:
                 return {"ok": False, "error": "У вас нет активных подписок для продления"}
             
            keys.sort(key=lambda x: x.get('expiry_date', ''))
            key = keys[0]
            key_id = key['key_id']
            
            host = key.get('host_name')
            c_email = key.get('key_email')
             
            res = await remnawave_api.create_or_update_key_on_host(
                host_name=host,
                email=c_email,
                days_to_add=days_to_add,
                telegram_id=user_id
            )
            if res:
                rw_repo.update_key(key_id, remnawave_user_uuid=res['client_uuid'], expire_at_ms=res['expiry_timestamp_ms'])
                rw_repo.redeem_universal_promo(code, user_id)
                return {"ok": True, "promo_type": "universal", "message": f"Добавлено {days_to_add} дн."}
            else:
                return {"ok": False, "error": "Ошибка активации на стороне сервера"}

    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка API apply-promo для {user_id}: {e}")
        return {"ok": False, "error": str(e)}

class CheckPaymentRequest(BaseModel):
    payment_id: str

@app.post("/api/check-payment")
async def api_check_payment(req: CheckPaymentRequest):
    try:
        if not req.payment_id or req.payment_id == "undefined" or req.payment_id == "null":
            return {"ok": False, "error": "Invalid payment_id"}
            
        exists = check_transaction_exists(req.payment_id)
        if not exists:
            return {"ok": True, "paid": False}
        
        return {
            "ok": True, 
            "paid": True,
            "message": "Оплата успешно подтверждена"
        }
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка проверки платежа {req.payment_id}: {e}")
        return {"ok": False, "error": str(e)}

class KeyActionRequest(BaseModel):
    user_id: int
    key_id: int
    host_name: str | None = None

class DeleteDeviceRequest(BaseModel):
    user_id: int
    key_id: int
    device_id: str
    host_name: str | None = None

class CommentRequest(BaseModel):
    user_id: int
    key_id: int
    comment: str

@app.post("/api/key/devices")
async def api_key_devices(req: KeyActionRequest):
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}
            
        from shop_bot.data_manager.remnawave_repository import get_key_by_id
        from shop_bot.modules import remnawave_api
        key = get_key_by_id(req.key_id)
        if not key or key.get("user_id") != req.user_id:
            return {"ok": False, "error": "Ключ не найден"}
            
        uuid_val = key.get("remnawave_user_uuid")
        if not uuid_val:
            return {"ok": False, "error": "Ключ не имеет привязки к серверу"}
            
        host = req.host_name or key.get("host_name")
        devices_data = await remnawave_api.get_connected_devices_count(uuid_val, host_name=host)
        if devices_data and "devices" in devices_data:
            return {"ok": True, "devices": devices_data["devices"]}
            
        return {"ok": True, "devices": []}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка получения устройств для ключа {req.key_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/key/device/delete")
async def api_key_device_delete(req: DeleteDeviceRequest):
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}
            
        from shop_bot.data_manager.remnawave_repository import get_key_by_id
        from shop_bot.modules import remnawave_api
        key = get_key_by_id(req.key_id)
        if not key or key.get("user_id") != req.user_id:
            return {"ok": False, "error": "Ключ не найден"}
            
        uuid_val = key.get("remnawave_user_uuid")
        if not uuid_val:
            return {"ok": False, "error": "Ключ не имеет привязки"}
            
        host = req.host_name or key.get("host_name")
        success = await remnawave_api.delete_user_device(uuid_val, req.device_id, host_name=host)
        if success:
            return {"ok": True}
        return {"ok": False, "error": "Не удалось удалить устройство"}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка удаления устройства для ключа {req.key_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/key/comment")
async def api_key_comment(req: CommentRequest):
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}
            
        from shop_bot.data_manager.remnawave_repository import get_key_by_id, update_key
        key = get_key_by_id(req.key_id)
        if not key or key.get("user_id") != req.user_id:
            return {"ok": False, "error": "Ключ не найден"}
            
        update_key(req.key_id, comment_key=req.comment)
        return {"ok": True}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка обновления комментария для ключа {req.key_id}: {e}")
        return {"ok": False, "error": str(e)}

class ResetSubscriptionRequest(BaseModel):
    user_id: int
    key_id: int


@app.post("/api/key/reset-subscription")
async def api_key_reset_subscription(req: ResetSubscriptionRequest):
    """
    Пересоздаёт ссылку подписки: отзывает текущую в Remnawave и выдаёт новую.
    Старая ссылка после этого перестаёт работать.

    Ограничение по частоте общее с ботом и админкой — оно хранится в БД.
    """
    from shop_bot.data_manager import database
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        key = get_key_by_id(req.key_id)
        if not key or key.get("user_id") != req.user_id:
            return {"ok": False, "error": "Подписка не найдена"}

        wait_seconds = database.get_subscription_reset_wait(req.key_id)
        if wait_seconds > 0:
            wait_min = max(1, int(wait_seconds / 60))
            return {"ok": False, "error": f"Пересоздавать можно раз в час. Подождите ещё {wait_min} мин."}

        client_uuid = key.get("remnawave_user_uuid")
        host_name = key.get("host_name")
        if not client_uuid:
            return {"ok": False, "error": "Подписка не привязана к серверу"}

        result = await remnawave_api.revoke_subscription_on_host(client_uuid, host_name=host_name)
        if not result:
            return {"ok": False, "error": "Не удалось пересоздать подписку. Попробуйте позже."}

        database.mark_subscription_reset(req.key_id)

        new_sub_url = remnawave_api.extract_subscription_url(result) or ""
        new_short_uuid = result.get("shortUuid")
        try:
            update_key(req.key_id, subscription_url=new_sub_url, short_uuid=new_short_uuid)
        except Exception as e:
            logger.warning(f"[WEBAPP] - Не удалось сохранить новую ссылку подписки {req.key_id}: {e}")

        logger.info(f"[WEBAPP] - Пользователь {req.user_id} пересоздал подписку {req.key_id}")

        # Дублируем результат в бот: пользователь мог начать в вебаппе,
        # а пользоваться ссылкой удобнее из чата.
        try:
            key_number = key.get("key_number") or req.key_id
            notify_text = (
                f"🔄 <b>Подписка #{key_number} пересоздана</b>\n\n"
                "Старая ссылка больше не работает. Импортируйте новую ссылку в приложение:\n\n"
                f"<code>{new_sub_url}</code>"
            ) if new_sub_url else (
                f"🔄 <b>Подписка #{key_number} пересоздана</b>\n\n"
                "Старая ссылка больше не работает. Откройте подписку в боте, чтобы получить новую ссылку."
            )
            await _send_telegram_message(req.user_id, notify_text)
        except Exception as e:
            logger.warning(f"[WEBAPP] - Не удалось отправить уведомление о сбросе {req.key_id}: {e}")

        return {"ok": True, "subscription_url": new_sub_url}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка пересоздания подписки {req.key_id}: {e}")
        return {"ok": False, "error": "Внутренняя ошибка сервера"}


def _format_media(message_id, user_id: int | None = None) -> list:
    """Вложения сообщения в виде, пригодном для показа в миниаппе."""
    if not message_id:
        return []
    try:
        from shop_bot.data_manager.database import get_media_for_messages
        grouped = get_media_for_messages([int(message_id)])
        return [
            {
                "id": a.get("media_id"),
                "kind": a.get("kind"),
                "name": a.get("file_name"),
                "url": f"/api/support/media/{a.get('media_id')}?user_id={user_id}" if user_id else None,
            }
            for a in grouped.get(int(message_id), [])
        ]
    except Exception:
        return []


class SupportHistoryRequest(BaseModel):
    user_id: int


@app.post("/api/support/history")
async def api_support_history(req: SupportHistoryRequest):
    """Список всех обращений пользователя — открытых и закрытых."""
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        from shop_bot.data_manager.remnawave_repository import get_user_tickets, get_ticket_messages
        tickets = get_user_tickets(req.user_id) or []

        items = []
        for t in sorted(tickets, key=lambda x: int(x['ticket_id']), reverse=True):
            msgs = [m for m in (get_ticket_messages(t['ticket_id']) or [])
                    if m.get('sender') != 'note']
            last = msgs[-1] if msgs else None
            items.append({
                "ticket_id": t['ticket_id'],
                "subject": t.get('subject') or 'Обращение без темы',
                "status": t.get('status'),
                "created_at": t.get('created_at'),
                "updated_at": t.get('updated_at'),
                "messages_count": len(msgs),
                "last_message": (last or {}).get('content', '')[:120],
                "last_sender": (last or {}).get('sender'),
            })

        return {"ok": True, "tickets": items}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка истории обращений для {req.user_id}: {e}")
        return {"ok": False, "error": "Внутренняя ошибка сервера"}


class SupportTicketViewRequest(BaseModel):
    user_id: int
    ticket_id: int


@app.post("/api/support/ticket")
async def api_support_ticket(req: SupportTicketViewRequest):
    """Переписка по конкретному обращению, в том числе закрытому."""
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        from shop_bot.data_manager.remnawave_repository import get_ticket, get_ticket_messages
        ticket = get_ticket(req.ticket_id)
        if not ticket or ticket.get('user_id') != req.user_id:
            return {"ok": False, "error": "Обращение не найдено"}

        messages = []
        for m in (get_ticket_messages(req.ticket_id) or []):
            if m.get('sender') == 'note':
                continue
            media = _format_media(m.get("message_id"), req.user_id)
            # Сообщение без текста и без вложений показывать нечем —
            # такие записи остались в базе от отправки пустой формы
            if not (m.get("content") or "").strip() and not media:
                continue
            messages.append({
                "sender": m.get("sender"),
                "content": m.get("content"),
                "created_at": m.get("created_at"),
                "media": media,
            })

        return {
            "ok": True,
            "ticket_id": ticket['ticket_id'],
            "subject": ticket.get('subject') or 'Обращение без темы',
            "status": ticket.get('status'),
            "messages": messages,
        }
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка просмотра обращения: {e}")
        return {"ok": False, "error": "Внутренняя ошибка сервера"}


@app.post("/api/support/status")
async def api_support_status(req: SupportStatusRequest):
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}
            
        from shop_bot.data_manager.remnawave_repository import get_user_tickets, get_ticket_messages
        tickets = get_user_tickets(req.user_id) or []
        open_tickets = [t for t in tickets if t.get('status') == 'open']
        if not open_tickets:
            return {"ok": True, "has_ticket": False}
        
        ticket = max(open_tickets, key=lambda t: int(t['ticket_id']))
        messages = get_ticket_messages(ticket['ticket_id']) or []
        
        formatted_messages = []
        for m in messages:
            if m.get('sender') == 'note':
                continue
            media = _format_media(m.get("message_id"), req.user_id)
            if not (m.get("content") or "").strip() and not media:
                continue
            formatted_messages.append({
                "sender": m.get("sender"),
                "content": m.get("content"),
                "created_at": m.get("created_at"),
                "media": media,
            })
            
        return {
            "ok": True, 
            "has_ticket": True, 
            "ticket_id": ticket['ticket_id'],
            "subject": ticket.get('subject', 'Обращение без темы'),
            "status": ticket.get('status'),
            "messages": formatted_messages
        }
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка статуса поддержки для {req.user_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.post("/api/support/create")
async def api_support_create(req: SupportTicketCreateRequest):
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        if _support_cooldown_hit(req.user_id):
            return {"ok": False, "error": "Слишком часто. Подождите пару секунд"}

        from shop_bot.data_manager.remnawave_repository import get_or_create_open_ticket, add_support_message, get_setting

        subject_text = req.subject.strip()[:64]
        if not subject_text:
            return {"ok": False, "error": "Тема обращения не может быть пустой"}
            
        ticket_id, created_new = get_or_create_open_ticket(req.user_id, subject_text)
        
        if not ticket_id:
            return {"ok": False, "error": "Не удалось создать тикет"}
            
        if not created_new:
            return {"ok": False, "error": "У вас уже есть открытый тикет"}
            
        # Уведомление админов — best-effort: тикет уже создан в БД, и
        # клиент должен увидеть успех даже если бот недоступен (невалидный
        # токен, сеть, бан бота) — раньше исключение из Bot(token=...)
        # (вне внутреннего try) улетало в общий except ниже и превращало
        # уже успешное создание тикета в ответ ok:false.
        try:
            from aiogram import Bot
            token = get_setting("support_bot_token")
            if token:
                bot = Bot(token=token)
                try:
                    try:
                        user = await bot.get_chat(req.user_id)
                        username_display = f"@{user.username}" if getattr(user, 'username', None) else f"ID {req.user_id}"
                    except Exception:
                        username_display = f"ID {req.user_id}"

                    import html
                    notification_text = (
                        f"🆕 <b>Новое обращение (WebApp)!</b>\n\n"
                        f"👤 <b>USER:</b> (<code>{req.user_id}</code> - {html.escape(username_display)})\n"
                        f"📝 <b>ID тикета:</b> <code>#{ticket_id}</code>\n"
                        f"💬 <b>Тема:</b> <i>{html.escape(subject_text)}</i>\n\n"
                        f"💌 Сообщения:\n"
                        f"<blockquote>Тикет открыт через веб-приложение.</blockquote>"
                    )

                    from shop_bot.data_manager.remnawave_repository import get_admin_ids
                    for aid in get_admin_ids():
                        try:
                            await bot.send_message(
                                chat_id=int(aid),
                                text=notification_text,
                                parse_mode="HTML",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="💬 Ответить", callback_data=f"admin_reply_dm_{ticket_id}")]
                                ])
                            )
                        except Exception:
                            pass
                finally:
                    await bot.session.close()
        except Exception as e:
            logger.warning(f"[WEBAPP] - Не удалось уведомить админов о новом тикете {ticket_id}: {e}")

        return {"ok": True, "ticket_id": ticket_id}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка создания тикета поддержки для {req.user_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/support/media/{media_id}")
async def api_support_media_file(request: Request, media_id: int, user_id: int | None = None):
    """
    Отдаёт вложение пользователю. Доступ только к файлам из собственных
    обращений — чужие id вернут 403 даже при прямом переборе.
    """
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    try:
        from shop_bot.data_manager.database import get_support_media
        from shop_bot.data_manager.remnawave_repository import get_ticket
        from shop_bot.data_manager import support_media as media_store

        row = get_support_media(media_id)
        if not row:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)

        ticket = get_ticket(row.get('ticket_id'))
        if not ticket:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
        if user_id is None or int(ticket.get('user_id') or 0) != int(user_id):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        path = media_store.abs_path(row.get('local_path'))
        if path is None:
            return JSONResponse({"ok": False, "error": "file_missing"}, status_code=404)

        media_type = row.get('mime_type') or "application/octet-stream"

        # Перемотка аудио и видео требует поддержки Range-запросов.
        # Не полагаемся на версию Starlette и обрабатываем диапазон сами.
        range_header = request.headers.get('range') if request else None
        file_size = path.stat().st_size

        if range_header:
            import re as _re
            m = _re.match(r'bytes=(\d*)-(\d*)', range_header.strip())
            if m:
                start = int(m.group(1)) if m.group(1) else 0
                end = int(m.group(2)) if m.group(2) else file_size - 1
                end = min(end, file_size - 1)
                if start <= end:
                    length = end - start + 1

                    def _chunk():
                        with open(path, 'rb') as f:
                            f.seek(start)
                            left = length
                            while left > 0:
                                data = f.read(min(64 * 1024, left))
                                if not data:
                                    break
                                left -= len(data)
                                yield data

                    return StreamingResponse(
                        _chunk(),
                        status_code=206,
                        media_type=media_type,
                        headers={
                            'Content-Range': f'bytes {start}-{end}/{file_size}',
                            'Content-Length': str(length),
                            'Accept-Ranges': 'bytes',
                        },
                    )

        return FileResponse(
            str(path),
            media_type=media_type,
            filename=row.get('file_name') or path.name,
            headers={'Accept-Ranges': 'bytes'},
        )
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка отдачи вложения {media_id}: {e}")
        return JSONResponse({"ok": False, "error": "internal"}, status_code=500)


@app.get("/api/support/media-config")
async def api_support_media_config():
    """Настройки вложений — миниапп подстраивает под них форму загрузки."""
    try:
        from shop_bot.data_manager.database import get_support_media_settings
        cfg = get_support_media_settings()
        # Без python-multipart приём файлов физически невозможен —
        # честно гасим кнопку в интерфейсе, а не даём ей падать.
        enabled = bool(cfg["enabled"]) and MULTIPART_AVAILABLE
        return {
            "ok": True,
            "enabled": enabled,
            "upload_supported": MULTIPART_AVAILABLE,
            "max_mb": cfg["max_mb"],
            "allowed": cfg["allowed"],
            "accept": ",".join("." + e for e in cfg["allowed"]),
        }
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка получения настроек вложений: {e}")
        return {"ok": False, "enabled": False, "allowed": [], "max_mb": 0}


if MULTIPART_AVAILABLE:
  @app.post("/api/support/upload")
  async def api_support_upload(
    user_id: int = Form(...),
    ticket_id: int = Form(...),
    caption: str = Form(""),
    file: UploadFile = File(...),
  ):
      """
      Приём вложения из миниаппа.

      Файл кладём на диск и сразу отправляем в Telegram: так у записи
      появляется и локальная копия, и file_id — как и для вложений,
      пришедших из чата.
      """
      try:
          user = get_user(user_id)
          if not user or user.get('is_banned'):
              return {"ok": False, "error": "Access denied"}

          from shop_bot.data_manager.remnawave_repository import get_ticket, add_support_message
          from shop_bot.data_manager.database import add_support_media
          from shop_bot.data_manager import support_media as media_store

          ticket = get_ticket(ticket_id)
          if not ticket or ticket.get('user_id') != user_id or ticket.get('status') != 'open':
              return {"ok": False, "error": "Тикет не найден или закрыт"}

          data = await file.read()
          ok, err, ext = media_store.validate(file.filename, file.content_type, len(data))
          if not ok:
              return {"ok": False, "error": err}

          local = media_store.save_bytes(ticket_id, data, ext)
          if not local:
              return {"ok": False, "error": "Не удалось сохранить файл"}

          kind = media_store.kind_for_ext(ext)
          text = (caption or "").strip()
          label = {"photo": "[Фото]", "video": "[Видео]"}.get(kind, f"[Документ: {file.filename}]")
          content = f"{label} {text}".strip()

          message_row_id = add_support_message(ticket_id, sender="user", content=content)

          # Отправляем в Telegram и забираем file_id (best-effort — вложение
          # уже сохранено на диск и в БД ниже, сбой бота не должен
          # превращать успешную загрузку в ok:false).
          file_id = None
          try:
              token = get_setting("support_bot_token")
              if token:
                  bot = Bot(token=token)
                  try:
                      path = media_store.abs_path(local)
                      sent = None
                      if path:
                          input_file = FSInputFile(str(path), filename=file.filename or path.name)
                          forum_chat_id = ticket.get('forum_chat_id')
                          thread_id = ticket.get('message_thread_id')
                          caption_text = f"📨 Вложение из WebApp (тикет #{ticket_id})"
                          if text:
                              caption_text += f"\n{text}"

                          targets = []
                          if forum_chat_id and thread_id:
                              targets.append(dict(chat_id=int(forum_chat_id),
                                                  message_thread_id=int(thread_id)))
                          else:
                              from shop_bot.data_manager.remnawave_repository import get_admin_ids
                              targets = [dict(chat_id=int(a)) for a in get_admin_ids()]

                          for t in targets:
                              try:
                                  if kind == "photo":
                                      sent = await bot.send_photo(photo=input_file, caption=caption_text, **t)
                                  elif kind == "video":
                                      sent = await bot.send_video(video=input_file, caption=caption_text, **t)
                                  else:
                                      sent = await bot.send_document(document=input_file, caption=caption_text, **t)
                              except Exception as e:
                                  logger.warning(f"[WEBAPP] - Не удалось отправить вложение: {e}")

                          if sent:
                              if getattr(sent, "photo", None):
                                  file_id = sent.photo[-1].file_id
                              elif getattr(sent, "video", None):
                                  file_id = sent.video.file_id
                              elif getattr(sent, "document", None):
                                  file_id = sent.document.file_id
                  finally:
                      await bot.session.close()
          except Exception as e:
              logger.warning(f"[WEBAPP] - Не удалось переслать вложение в Telegram (тикет {ticket_id}): {e}")

          add_support_media(
              ticket_id,
              message_id=message_row_id,
              sender="user",
              kind=kind,
              file_id=file_id,
              local_path=local,
              file_name=file.filename,
              mime_type=file.content_type,
              file_size=len(data),
          )

          logger.info(f"[WEBAPP] - Пользователь {user_id} приложил файл к тикету {ticket_id}")
          return {"ok": True, "kind": kind}
      except Exception as e:
          logger.error(f"[WEBAPP] - Ошибка загрузки вложения: {e}")
          return {"ok": False, "error": "Внутренняя ошибка сервера"}


@app.post("/api/support/send")
async def api_support_send(req: SupportMessageSendRequest):
    try:
        user = get_user(req.user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        if _support_cooldown_hit(req.user_id):
            return {"ok": False, "error": "Слишком часто. Подождите пару секунд"}

        from shop_bot.data_manager.remnawave_repository import get_ticket, add_support_message, get_setting
        ticket = get_ticket(req.ticket_id)
        if not ticket or ticket.get('user_id') != req.user_id or ticket.get('status') != 'open':
            return {"ok": False, "error": "Тикет не найден или закрыт"}

        # Пустые сообщения раньше сохранялись как есть и превращались в
        # ленте в пузыри с одним временем без текста (см. #783, #784).
        message_text = (req.message or "").strip()
        if not message_text:
            return {"ok": False, "error": "Введите текст сообщения"}
        if len(message_text) > SUPPORT_MESSAGE_MAX_LEN:
            return {"ok": False, "error": f"Сообщение слишком длинное (максимум {SUPPORT_MESSAGE_MAX_LEN} символов)"}

        add_support_message(req.ticket_id, sender="user", content=message_text)

        # Best-effort уведомление — сообщение уже сохранено, сбой бота не
        # должен превращать успешную отправку в ok:false (см. комментарий
        # в api_support_create).
        try:
            from aiogram import Bot
            token = get_setting("support_bot_token")
            if token:
                bot = Bot(token=token)
                try:
                    try:
                        user = await bot.get_chat(req.user_id)
                        username_display = f"@{user.username}" if getattr(user, 'username', None) else f"ID {req.user_id}"
                    except Exception:
                        username_display = f"ID {req.user_id}"

                    import html
                    notification_text = (
                        f"📨 <b>Новое сообщение (WebApp)!</b>\n\n"
                        f"👤 <b>USER:</b> (<code>{req.user_id}</code> - {html.escape(username_display)})\n"
                        f"📝 <b>ID тикета:</b> <code>#{req.ticket_id}</code>\n"
                        f"💬 <b>Тема:</b> <i>{html.escape(ticket.get('subject', 'Без темы'))}</i>\n\n"
                        f"💌 Сообщения:\n"
                        f"<blockquote>{html.escape(message_text)}</blockquote>"
                    )

                    forum_chat_id = ticket.get('forum_chat_id')
                    thread_id = ticket.get('message_thread_id')

                    if forum_chat_id and thread_id:
                        try:
                            await bot.send_message(
                                chat_id=int(forum_chat_id),
                                message_thread_id=int(thread_id),
                                text=notification_text,
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.warning(f"Error mirroring to forum: {e}")
                    else:
                        from shop_bot.data_manager.remnawave_repository import get_admin_ids
                        for aid in get_admin_ids():
                            try:
                                await bot.send_message(
                                    chat_id=int(aid),
                                    text=notification_text,
                                    parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"admin_reply_dm_{req.ticket_id}")]
                                    ])
                                )
                            except Exception:
                                pass
                finally:
                    await bot.session.close()
        except Exception as e:
            logger.warning(f"[WEBAPP] - Не удалось уведомить админов о сообщении в тикете {req.ticket_id}: {e}")

        return {"ok": True}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка отправки сообщения в поддержку для {req.user_id}: {e}")
        return {"ok": False, "error": str(e)}

class TrialRequest(BaseModel):
    user_id: int


def _trial_state(user_id: int) -> dict:
    """
    Доступен ли пользователю пробный период.

    Требований три: включён в настройках, ещё не использован и к
    аккаунту привязан Telegram — иначе выдать ключ в боте некуда.

    Раньше «телеграмность» проверялась как int(user_id) <= 0, но
    create_user_by_email выдаёт положительные синтетические id вида
    999XXXXXXX, поэтому условие не срабатывало никогда и пробный период
    предлагался всем подряд. Теперь решает флаг tg_linked.
    """
    try:
        if (get_setting("trial_enabled") or "").strip().lower() not in ("1", "true", "on", "yes"):
            return {"available": False, "reason": "disabled"}

        user = get_user(user_id)
        if not user:
            return {"available": False, "reason": "no_user"}

        if user.get("trial_used"):
            return {"available": False, "reason": "used"}

        try:
            days = int(get_setting("trial_duration_days") or 0)
        except Exception:
            days = 0
        if days <= 0:
            return {"available": False, "reason": "disabled"}

        host = (get_setting("trial_host_id") or "").strip()
        hosts = get_all_hosts(visible_only=True) or []
        if host and not any(h.get("host_name") == host for h in hosts):
            host = ""
        if not host:
            if not hosts:
                return {"available": False, "reason": "no_hosts"}
            host = hosts[0]["host_name"]

        # Проверку Telegram держим последней: мини-апп показывает «привяжите
        # Telegram и получите N дней», поэтому срок должен быть уже посчитан.
        from shop_bot.data_manager.database import is_telegram_account
        if not is_telegram_account(user):
            return {"available": False, "reason": "no_telegram", "days": days}

        return {"available": True, "days": days, "host": host, "reason": ""}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка проверки пробного периода {user_id}: {e}")
        return {"available": False, "reason": "error"}


@app.get("/api/catalog")
async def api_catalog(user_id: int):
    """
    Каталог для экрана покупки: локации, тарифы и наборы устройств —
    структурой, а не готовым HTML. Разметку собирает клиент, поэтому
    вид можно менять, не трогая сервер.
    """
    import re as _re
    try:
        user = get_user(user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        try:
            hosts = get_all_hosts(visible_only=True) or []
        except Exception:
            hosts = []

        items = []
        for host in hosts:
            host_name = host.get('host_name')
            if not host_name:
                continue

            desc = host.get('description') or ""
            desc = _re.sub(r'(\s*\n\s*){2,}', '\n', desc).strip()

            try:
                plans = get_plans_for_host(host_name) or []
            except Exception:
                plans = []

            plan_items = []
            base_per_month = None
            for plan in plans:
                if not plan.get('is_active'):
                    continue
                try:
                    price = int(calculate_webapp_price(float(plan.get('price', 0)), user_id))
                    months = int(plan.get('months') or 1)
                except (TypeError, ValueError):
                    continue
                if months <= 0:
                    continue

                per_month = price / months
                if months == 1:
                    base_per_month = per_month

                try:
                    plan_devices = int(plan.get('hwid_limit') or 0)
                except (TypeError, ValueError):
                    plan_devices = 0

                plan_items.append({
                    "plan_id": plan.get('plan_id'),
                    "plan_name": plan.get('plan_name') or "",
                    "months": months,
                    "price": price,
                    "per_month": round(per_month),
                    # 0 — лимит устройств не задан (безлимит)
                    "devices": plan_devices,
                })

            # Выгода считается относительно месячного тарифа — так человек
            # видит, зачем брать длиннее
            for it in plan_items:
                save = 0
                if base_per_month and it["months"] > 1 and base_per_month > 0:
                    save = round((1 - it["per_month"] / base_per_month) * 100)
                it["save"] = save if save > 0 else 0

            plan_items.sort(key=lambda x: x["months"])

            # Наборы устройств продаются только при device_mode == 'tiers'.
            # В режиме 'plan' лимит устройств зашит в сам тариф (hwid_limit),
            # выбирать нечего — и тогда base_device_* обычно не задан вовсе.
            device_mode = (host.get('device_mode') or 'plan').strip()

            tiers = []
            if device_mode == 'tiers':
                try:
                    from shop_bot.data_manager.database import get_device_tiers
                    tiers = get_device_tiers(host_name) or []
                except Exception:
                    tiers = []

            # Доплата считается как (лишние устройства) x цена за штуку —
            # так же, как в боте: float(diff * tier['price']). Отдаём
            # готовую сумму, чтобы в интерфейсе не было «+5 ₽/мес» у
            # всех тиров подряд.
            raw_base = get_setting(f"base_device_{host_name}")
            try:
                base_devices = int(raw_base) if raw_base else 0
            except (TypeError, ValueError):
                base_devices = 0
            if base_devices <= 0:
                # без настройки берём лимит из тарифов: он и есть «включено»
                plan_limits = {p["devices"] for p in plan_items if p["devices"] > 0}
                base_devices = min(plan_limits) if len(plan_limits) == 1 else 0
            if device_mode == 'tiers' and base_devices <= 0:
                base_devices = 1  # как в боте: без настройки считаем одно включённое

            tier_items = []
            for t in tiers:
                try:
                    devices = int(t.get('device_count') or 0)
                    unit = float(t.get('price') or 0)
                    extra = max(0, devices - base_devices)
                    tier_items.append({
                        "tier_id": t.get('tier_id'),
                        "devices": devices,
                        "price": unit,
                        "unit_price": unit,
                        "total_price": round(extra * unit, 2),
                    })
                except (TypeError, ValueError):
                    continue
            tier_items.sort(key=lambda x: x["devices"])

            items.append({
                "host_name": host_name,
                "description": desc,
                "plans": plan_items,
                "tiers": tier_items,
                "base_devices": base_devices,
                "device_mode": device_mode,
            })

        return {"ok": True, "hosts": items}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка каталога для {user_id}: {e}", exc_info=True)
        return {"ok": False, "error": "Внутренняя ошибка"}


@app.get("/api/profile-stats")
async def api_profile_stats(user_id: int):
    """Показатели кабинета: баланс, рефералы, оплаченные месяцы."""
    try:
        user = get_user(user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}

        try:
            referrals = get_referral_count(user_id) or 0
        except Exception:
            referrals = 0

        def _num(v, digits=0):
            try:
                f = float(v or 0)
            except (TypeError, ValueError):
                f = 0.0
            return f"{f:.{digits}f}".replace(".", ",") if digits else f"{f:.0f}"

        username = (user.get('username') or '').strip()

        # Кабинет собирается на клиенте, поэтому отдаём и реквизиты —
        # раньше они приходили готовым HTML отдельной карточкой, из-за
        # чего баланс и ID выводились на странице по нескольку раз.
        try:
            keys_count = len(get_user_keys(user_id) or [])
        except Exception:
            keys_count = 0

        from shop_bot.data_manager.database import is_telegram_account
        tg_linked = is_telegram_account(user)

        bot_username = (get_setting("telegram_bot_username")
                        or get_setting("support_bot_username") or "").lstrip("@")
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}" if bot_username else ""

        reg = str(user.get('registration_date') or "")[:10]
        if reg and "-" in reg:
            try:
                y, m, d = reg.split("-")
                reg = f"{d}.{m}.{y}"
            except ValueError:
                pass

        return {
            "ok": True,
            "user_id": user_id,
            "username": f"@{username}" if username else "",
            "balance": _num(user.get('balance'), 2),
            "referrals": referrals,
            "referral_earned": _num(user.get('referral_balance_all'), 2),
            "total_months": int(user.get('total_months') or 0),
            "total_spent": _num(user.get('total_spent')),
            "keys_count": keys_count,
            "tg_linked": tg_linked,
            "email": (user.get('auth_email') or "").strip(),
            "registration_date": reg,
            "referral_link": ref_link,
        }
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка показателей кабинета {user_id}: {e}")
        return {"ok": False, "error": "Внутренняя ошибка"}


@app.get("/api/trial/status")
async def api_trial_status(user_id: int):
    state = _trial_state(user_id)
    return {"ok": True, **state}


@app.post("/api/trial/activate")
async def api_trial_activate(req: TrialRequest):
    """Выдаёт пробную подписку — одной кнопкой, без выбора сервера."""
    from shop_bot.data_manager.database import set_trial_used
    from shop_bot.data_manager import remnawave_repository as rw_repo
    import re as _re

    try:
        user = get_user(req.user_id)
        if not user or user.get("is_banned"):
            return {"ok": False, "error": "Access denied"}

        state = _trial_state(req.user_id)
        if not state.get("available"):
            messages = {
                "used": "Пробный период уже был активирован",
                "no_telegram": "Привяжите Telegram, чтобы получить пробный период",
                "disabled": "Пробный период сейчас недоступен",
                "no_hosts": "Нет доступных серверов, попробуйте позже",
            }
            return {"ok": False, "error": messages.get(state.get("reason"), "Пробный период недоступен")}

        host_name = state["host"]
        days = state["days"]

        # email формируем так же, как бот, чтобы записи не расходились
        raw = (user.get("username") or f"user{req.user_id}").lower()
        slug = _re.sub(r"[^a-z0-9_-]", "", raw.replace(".", "_").replace(" ", "")).lstrip("_-")[:16]
        if not slug:
            slug = f"user{req.user_id}"

        attempt = 1
        while attempt <= 100:
            candidate = f"trial_{slug}{f'-{attempt}' if attempt > 1 else ''}@bot.local"
            if not rw_repo.get_key_by_email(candidate):
                break
            attempt += 1

        try:
            trial_traffic = int(get_setting("trial_traffic_limit_gb") or 0)
        except Exception:
            trial_traffic = 0
        try:
            trial_hwid = int(get_setting("trial_hwid_limit") or 0)
        except Exception:
            trial_hwid = 0

        result = await remnawave_api.create_or_update_key_on_host(
            host_name=host_name,
            email=candidate,
            days_to_add=days,
            telegram_id=req.user_id,
            traffic_limit_gb=trial_traffic if trial_traffic > 0 else None,
            hwid_limit=trial_hwid if trial_hwid > 0 else None,
        )
        if not result:
            return {"ok": False, "error": "Сервер не ответил. Попробуйте позже."}

        set_trial_used(req.user_id)
        rw_repo.record_key_from_payload(user_id=req.user_id, payload=result, host_name=host_name)

        logger.info(f"[WEBAPP] - Пользователь {req.user_id} активировал пробный период на {host_name}")

        # дублируем в бот, чтобы ссылка была и в переписке
        try:
            token = get_setting("telegram_bot_token")
            if token:
                text = (
                    f"🎁 <b>Пробный период активирован</b>\n\n"
                    f"Сервер: {host_name}\n"
                    f"Срок: {days} дн.\n\n"
                    f"🗽 <b>Ваша подписка:</b>\n\n"
                    f"<tg-spoiler>{result.get('connection_string', '')}</tg-spoiler>\n\n"
                    f"👆 Нажмите, чтобы подключиться"
                )
                await _send_telegram_message(req.user_id, text)
        except Exception as e:
            logger.warning(f"[WEBAPP] - Не удалось отправить пробную подписку в бот: {e}")

        return {
            "ok": True,
            "days": days,
            "host": host_name,
            "subscription_url": result.get("connection_string", ""),
        }
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка активации пробного периода: {e}", exc_info=True)
        return {"ok": False, "error": "Внутренняя ошибка сервера"}


@app.get("/api/user-status")
async def api_user_status(user_id: int):
    try:
        user = get_user(user_id)
        if not user or user.get('is_banned'):
            return {"ok": False, "error": "Access denied"}
            
        # get_user_keys уже отдаёт список от новых к старым — тем же
        # порядком бот нумерует подписки. Сохраняем нумерацию, чтобы
        # «Подписка №2» в мини-аппе и в чате означали одно и то же.
        keys = get_user_keys(user_id) or []

        # Лимиты и расход живут не в базе, а в Remnawave. Без этого шага
        # limit_ips/limit_bytes всегда None и любая подписка выглядела
        # безлимитной.
        now_naive = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
        active = []
        for k in keys:
            try:
                if datetime.fromisoformat(str(k.get('expire_at'))) > now_naive:
                    active.append(k)
            except (TypeError, ValueError):
                active.append(k)

        try:
            await enrich_keys_with_live_stats(active, user_id)
        except Exception as e:
            logger.warning(f"[WEBAPP] - Живая статистика недоступна для {user_id}: {e}")

        formatted_keys = [
            _process_key_data(k, number=i + 1) for i, k in enumerate(keys)
        ]

        return {"ok": True, "keys": formatted_keys}
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка статуса пользователя {user_id}: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/{path_param}")
async def dynamic_route(request: Request, path_param: str):
    try:
        if path_param.startswith("token="):
            token = path_param.split("=")[1]
            from shop_bot.data_manager import database
            user = database.get_user_by_auth_token(token)
            if user:
                webapp_settings = get_webapp_settings()
                if user.get('is_banned'):
                    return _render_banned_page(webapp_settings)
                return await _render_main_page(user['telegram_id'])
            else:
                 # Token not valid or expired -> Render Login Page
                 p = os.path.join(os.path.dirname(__file__), "login.html")
                 if os.path.exists(p):
                     with open(p, "r", encoding="utf-8") as f:
                         content = f.read()
                     
                     webapp_settings = get_webapp_settings()
                     context = {
                        "webapp_logo": webapp_settings.get("webapp_logo") or "",
                        "webapp_icon": webapp_settings.get("webapp_icon") or ""
                     }
                     content = _process_template_placeholders(content, 0, webapp_settings, context)
                     return HTMLResponse(content=content)
                 else:
                     return HTMLResponse(content="<h1>Login page not found</h1>", status_code=404)
        
        # Pass through to 404 naturally or handle other dynamic routes
        return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)
    except Exception as e:
        logger.error(f"[WEBAPP] - Ошибка динамического маршрута: {e}")
        return HTMLResponse(content="<h1>Error</h1>", status_code=500)
