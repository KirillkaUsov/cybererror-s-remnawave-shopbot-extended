"""Колесо удачи: бесплатный прокрут раз в сутки.

Призом могут быть дни к подписке, рубли на баланс или ничего — состав
секторов и их веса задаются в панели, поэтому логика здесь ничего не знает
про конкретные призы.

Весь розыгрыш идёт на сервере: клиент присылает только «крути», а что
выпало — решает эта функция. Иначе выигрыш подделывался бы запросом.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from shop_bot.data_manager import database

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

DEFAULT_COOLDOWN_HOURS = 24

# Причины отказа. Текст видит человек, поэтому лежит рядом с кодом.
DECLINE_TEXT = {
    "disabled": "Колесо удачи сейчас выключено.",
    "no_prizes": "Призы ещё не настроены — загляните позже.",
    "cooldown": "Следующий бесплатный прокрут будет доступен позже.",
    "no_subscription": "Дни начисляются к действующей подписке — сначала оформите её.",
    "failed": "Не удалось начислить приз. Попытка не сгорела, попробуйте ещё раз.",
}


def _now() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


def is_enabled() -> bool:
    return (database.get_setting("wheel_enabled") or "0").strip() == "1"


def cooldown_hours() -> int:
    try:
        value = int(database.get_setting("wheel_cooldown_hours") or DEFAULT_COOLDOWN_HOURS)
    except (TypeError, ValueError):
        value = DEFAULT_COOLDOWN_HOURS
    return max(1, value)


def get_prizes() -> list[dict]:
    """Активные сектора с положительным весом — остальные в розыгрыше не участвуют."""
    prizes = []
    for row in database.get_wheel_prizes(active_only=True) or []:
        try:
            weight = int(row.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        if weight > 0:
            prizes.append({**row, "weight": weight})
    return prizes


def _parse(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        try:
            return datetime.fromisoformat(str(value)).replace(tzinfo=None)
        except ValueError:
            return None


def state(user_id: int) -> dict:
    """Можно ли крутить прямо сейчас и что вообще стоит на колесе."""
    prizes = get_prizes()
    result = {
        "enabled": is_enabled(),
        "can_spin": False,
        "reason": None,
        "wait_seconds": 0,
        "cooldown_hours": cooldown_hours(),
        "prizes": [
            {"label": p.get("label"), "prize_type": p.get("prize_type"),
             "amount": float(p.get("amount") or 0), "weight": p["weight"]}
            for p in prizes
        ],
    }
    if not result["enabled"]:
        result["reason"] = "disabled"
        return result
    if not prizes:
        result["reason"] = "no_prizes"
        return result

    last = _parse(database.get_last_wheel_spin(user_id))
    if last:
        ready_at = last + timedelta(hours=result["cooldown_hours"])
        left = (ready_at - _now()).total_seconds()
        if left > 0:
            result["reason"] = "cooldown"
            result["wait_seconds"] = int(left)
            return result

    result["can_spin"] = True
    return result


def pick(prizes: list[dict]) -> dict:
    """Случайный сектор с учётом весов."""
    return random.choices(prizes, weights=[p["weight"] for p in prizes], k=1)[0]


def format_wait(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, minutes = seconds // 3600, (seconds % 3600) // 60
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин"
    return "меньше минуты"


def _target_key(user_id: int) -> dict | None:
    """Подписка, к которой добавляем дни — та, что кончается раньше всех.

    Дни полезнее там, где срок ближе; заодно человеку не приходится
    выбирать, а нам — хранить его выбор.
    """
    keys = database.get_user_keys(user_id) or []
    dated = []
    for key in keys:
        expiry = _parse(key.get("expiry_date") or key.get("expire_at"))
        if expiry:
            dated.append((expiry, key))
    if not dated:
        return keys[0] if keys else None
    dated.sort(key=lambda pair: pair[0])
    return dated[0][1]


async def _award(user_id: int, prize: dict) -> tuple[bool, dict | None, str]:
    """Начисляет приз. Возвращает (успех, ключ, текст для человека)."""
    prize_type = (prize.get("prize_type") or "nothing").strip()
    amount = float(prize.get("amount") or 0)

    if prize_type == "nothing" or amount <= 0:
        return True, None, ""

    if prize_type == "balance":
        if database.add_to_balance(user_id, amount):
            logger.info("Колесо: пользователю %s начислено %.2f RUB", user_id, amount)
            return True, None, f"На баланс зачислено <b>{amount:.0f} ₽</b>."
        return False, None, ""

    if prize_type == "days":
        key = _target_key(user_id)
        if not key:
            return False, None, "no_subscription"

        from shop_bot.modules import remnawave_api

        result = await remnawave_api.create_or_update_key_on_host(
            host_name=key.get("host_name"),
            email=key.get("key_email"),
            days_to_add=int(amount),
            telegram_id=user_id,
        )
        if not result:
            logger.error("Колесо: не удалось продлить ключ %s пользователю %s", key.get("key_id"), user_id)
            return False, key, ""

        database.update_key_info(
            key_id=key["key_id"],
            new_remnawave_uuid=result.get("client_uuid"),
            new_expiry_ms=result.get("expiry_timestamp_ms"),
        )
        expiry = datetime.fromtimestamp(result["expiry_timestamp_ms"] / 1000, tz=MSK)
        logger.info("Колесо: пользователю %s добавлено %d дн. к ключу %s", user_id, int(amount), key.get("key_id"))
        return True, key, (f"К подписке «{key.get('host_name')}» добавлено <b>{int(amount)} дн.</b>\n"
                           f"Действует до {expiry.strftime('%d.%m.%Y %H:%M')}.")

    logger.warning("Колесо: неизвестный тип приза %r", prize_type)
    return True, None, ""


async def spin(user_id: int) -> dict:
    """Один прокрут: проверка, розыгрыш, начисление, запись в журнал."""
    current = state(user_id)
    if not current["can_spin"]:
        return {"ok": False, "reason": current["reason"] or "cooldown",
                "wait_seconds": current["wait_seconds"],
                "error": DECLINE_TEXT.get(current["reason"] or "cooldown", "Сейчас крутить нельзя.")}

    prizes = get_prizes()
    now = _now()
    previous = database.get_last_wheel_spin(user_id)
    allowed_before = (now - timedelta(hours=current["cooldown_hours"])).strftime(TIME_FORMAT)

    # Занимаем попытку до розыгрыша: иначе два быстрых нажатия успевали
    # прокрутить колесо дважды за один кулдаун.
    if not database.claim_wheel_spin(user_id, now.strftime(TIME_FORMAT), allowed_before):
        again = state(user_id)
        return {"ok": False, "reason": "cooldown", "wait_seconds": again["wait_seconds"],
                "error": DECLINE_TEXT["cooldown"]}

    prize = pick(prizes)
    ok, key, detail = await _award(user_id, prize)

    if not ok:
        # Приз не выдан — возвращаем попытку, человек не виноват
        database.release_wheel_spin(user_id, previous)
        reason = detail if detail == "no_subscription" else "failed"
        return {"ok": False, "reason": reason, "error": DECLINE_TEXT[reason]}

    database.log_wheel_spin(user_id, prize, key.get("key_id") if key else None)

    won = (prize.get("prize_type") or "nothing") != "nothing" and float(prize.get("amount") or 0) > 0
    return {
        "ok": True,
        "won": won,
        "label": prize.get("label"),
        "prize_type": prize.get("prize_type"),
        "amount": float(prize.get("amount") or 0),
        "detail": detail,
        "cooldown_hours": current["cooldown_hours"],
    }
