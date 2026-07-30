"""Докупка слотов устройств к уже оплаченной подписке.

Слоты продаются помесячно вместе с тарифом, поэтому докупить их отдельно
можно только на остаток оплаченного срока: берём разницу в месячной цене
между текущим и желаемым набором и умножаем на то, сколько подписке ещё
осталось жить. Срок подписки при этом не меняется — только лимит устройств.

Модуль общий для бота и мини-аппа: цену считает только сервер, клиент
присылает лишь желаемое количество устройств.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from shop_bot.data_manager import database

logger = logging.getLogger(__name__)

# Значение metadata['action'] для такого заказа — по нему платёж
# маршрутизируется в process_successful_payment.
ACTION = "devices"

MSK = timezone(timedelta(hours=3))

# Платёжные шлюзы не принимают счета меньше рубля, поэтому копеечные
# доплаты (остался день-два) округляем вверх до минимальной суммы.
MIN_PRICE = 1.0

# У служебных подписок дата окончания уезжает в 2108 или 2300 год. Помесячная
# доплата за такой «остаток» превратилась бы в десятки тысяч рублей, поэтому
# считаем такие подписки бессрочными и докупку по ним не продаём.
# Порог тот же, что и в мини-аппе для надписи «Бессрочно».
UNLIMITED_DAYS_THRESHOLD = 1825

# Почему докупка недоступна. Текст видит человек, поэтому лежит рядом с
# кодом, а не собирается по месту в двух интерфейсах по-разному.
UNAVAILABLE_TEXT = {
    "no_tiers": "На этой локации число устройств входит в тариф — докупить слоты отдельно нельзя.",
    "unlimited": "У этой подписки нет лимита устройств — докупать нечего.",
    "expired": "Подписка истекла. Сначала продлите её, а потом докупайте устройства.",
    "endless": "У этой подписки бессрочный срок — доплату за остаток посчитать не от чего. Напишите в поддержку.",
    "max": "У вас уже максимальный набор устройств.",
    "unknown": "Не удалось получить текущий лимит устройств. Попробуйте позже.",
}


def _money(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def base_device_count(host_name: str) -> int:
    """Сколько устройств входит в тариф без доплаты."""
    try:
        return max(0, int(database.get_setting(f"base_device_{host_name}") or 1))
    except (TypeError, ValueError):
        return 1


def monthly_price(tiers: list[dict], base: int, device_count: int) -> float:
    """Месячная доплата за указанный набор устройств.

    Цена в таблице задана за одно устройство сверх базового набора. Набора,
    которого в таблице нет (в том числе базового), доплата не стоит.
    """
    for tier in tiers:
        if int(tier["device_count"]) == int(device_count):
            extra = max(0, int(device_count) - int(base))
            return _money(extra * float(tier["price"]))
    return 0.0


def key_expiry_ms(key: dict) -> int | None:
    """Срок действия ключа из локальной базы в миллисекундах.

    Даты в базе записаны по Москве, а контейнер живёт в UTC — поэтому
    временную зону проставляем явно, иначе срок уезжает на три часа.
    """
    raw = key.get("expiry_date") or key.get("expire_at")
    if not raw:
        return None
    dt = _parse_local(raw)
    if not dt:
        return None
    return int(dt.replace(tzinfo=MSK).timestamp() * 1000)


def _parse_local(raw) -> datetime | None:
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(str(raw)).replace(tzinfo=None)
    except ValueError:
        return None


def remaining_days(key: dict) -> int:
    """Сколько полных суток подписке осталось жить."""
    dt = _parse_local(key.get("expiry_date") or key.get("expire_at"))
    if not dt:
        return 0
    now = datetime.now(MSK).replace(tzinfo=None)
    return max(0, (dt - now).days)


def _remnawave_expiry_ms(info: dict | None) -> int | None:
    raw = (info or {}).get("expireAt")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


async def _fetch_remnawave_user(key: dict) -> dict | None:
    uuid = key.get("remnawave_user_uuid")
    host = key.get("host_name")
    if not uuid or not host:
        return None
    from shop_bot.modules import remnawave_api

    try:
        return await remnawave_api.get_user_by_uuid(uuid, host_name=host)
    except Exception as e:
        logger.error(
            "Докупка устройств: не удалось прочитать подписку %s на «%s»: %s",
            key.get("key_id"), host, e,
        )
        return None


async def current_expiry_ms(key: dict) -> int | None:
    """Дата окончания подписки такой, какой её видит панель.

    При докупке устройств её надо вернуть в панель без изменений, поэтому
    спрашиваем источник правды, а к локальной копии откатываемся только
    если панель не ответила.
    """
    info = await _fetch_remnawave_user(key)
    return _remnawave_expiry_ms(info) or key_expiry_ms(key)


async def build_offer(key: dict) -> dict:
    """Что именно можно докупить к этому ключу и за сколько.

    Возвращает `available=False` с причиной из UNAVAILABLE_TEXT, если
    докупать нечего или сейчас нельзя.
    """
    host = key.get("host_name") or ""
    offer = {
        "available": False,
        "reason": "no_tiers",
        "host_name": host,
        "base": 0,
        "current": None,
        "days_left": 0,
        "expiry_ms": None,
        "options": [],
    }

    host_data = database.get_host(host) if host else None
    if not host_data or (host_data.get("device_mode") or "plan") != "tiers":
        return offer

    tiers = sorted(database.get_device_tiers(host) or [], key=lambda t: int(t["device_count"]))
    if not tiers:
        return offer

    base = base_device_count(host)
    offer["base"] = base
    offer["days_left"] = remaining_days(key)

    info = await _fetch_remnawave_user(key)
    if not info:
        offer["reason"] = "unknown"
        return offer

    try:
        current = int(info.get("hwidDeviceLimit") or 0)
    except (TypeError, ValueError):
        current = 0
    offer["current"] = current
    offer["expiry_ms"] = _remnawave_expiry_ms(info) or key_expiry_ms(key)

    if current <= 0:
        offer["reason"] = "unlimited"
        return offer
    if offer["days_left"] <= 0:
        offer["reason"] = "expired"
        return offer
    if offer["days_left"] > UNLIMITED_DAYS_THRESHOLD:
        offer["reason"] = "endless"
        return offer

    current_monthly = monthly_price(tiers, base, current)
    months_left = offer["days_left"] / 30.0

    options = []
    for tier in tiers:
        count = int(tier["device_count"])
        if count <= current:
            continue
        delta = max(0.0, monthly_price(tiers, base, count) - current_monthly)
        options.append({
            "device_count": count,
            "monthly_price": _money(delta),
            "price": max(MIN_PRICE, _money(delta * months_left)),
        })

    if not options:
        offer["reason"] = "max"
        return offer

    offer["available"] = True
    offer["reason"] = None
    offer["options"] = options
    return offer


def find_option(offer: dict, device_count) -> dict | None:
    """Выбранный набор среди посчитанных сервером — цену с клиента не берём."""
    try:
        wanted = int(device_count)
    except (TypeError, ValueError):
        return None
    for option in offer.get("options") or []:
        if int(option["device_count"]) == wanted:
            return option
    return None
