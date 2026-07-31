"""Колесо удачи: бесплатный прокрут раз в сутки плюс билеты.

Билет позволяет крутить, когда бесплатная попытка ещё не восстановилась.
Билеты выдаются за покупку подписки, за приглашённых друзей, покупаются за
баланс или начисляются админом вручную.

Призом могут быть дни к подписке, рубли на баланс, персональный купон на
скидку или ничего — состав секторов и веса задаются в панели, поэтому логика
здесь ничего не знает про конкретные призы.

Весь розыгрыш идёт на сервере: клиент присылает только «крути», а что
выпало — решает эта функция. Иначе выигрыш подделывался бы запросом.
"""

from __future__ import annotations

import logging
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

from shop_bot.data_manager import database

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

DEFAULT_COOLDOWN_HOURS = 24
DEFAULT_PROMO_DAYS = 30
# Сколько живёт невыданный приз. Без срока они копятся годами, и магазин
# остаётся должен по каждому выигранному дню.
DEFAULT_PRIZE_TTL_DAYS = 14

# Типы призов. Купон создаётся одноразовым и именным: код виден только
# победителю, а в описании остаётся, кому и за что он выдан.
PRIZE_DAYS = "days"
PRIZE_BALANCE = "balance"
PRIZE_PROMO_PERCENT = "promo_percent"
PRIZE_PROMO_FIXED = "promo_fixed"
PRIZE_NOTHING = "nothing"
PRIZE_TYPES = (PRIZE_DAYS, PRIZE_BALANCE, PRIZE_PROMO_PERCENT, PRIZE_PROMO_FIXED, PRIZE_NOTHING)

# Причины отказа. Текст видит человек, поэтому лежит рядом с кодом.
DECLINE_TEXT = {
    "disabled": "Колесо удачи сейчас выключено.",
    "no_prizes": "Призы ещё не настроены — загляните позже.",
    "cooldown": "Бесплатный прокрут ещё не восстановился, а билетов нет.",
    "no_subscription": "Дни ждут подписку — оформите её и заберите приз из истории.",
    "failed": "Не удалось начислить приз. Попытка не сгорела, попробуйте ещё раз.",
    "expired": "Срок этого приза истёк.",
    "no_tickets": "Билетов нет.",
    "tickets_off": "Билеты сейчас не продаются.",
    "not_enough": "На балансе не хватает средств.",
}


def _now() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


def _setting_int(key: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(float(database.get_setting(key) or default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def is_enabled() -> bool:
    return (database.get_setting("wheel_enabled") or "0").strip() == "1"


def cooldown_hours() -> int:
    return _setting_int("wheel_cooldown_hours", DEFAULT_COOLDOWN_HOURS, minimum=1)


def ticket_price() -> float:
    """0 — билеты за деньги не продаются."""
    try:
        return max(0.0, float(database.get_setting("wheel_ticket_price") or 0))
    except (TypeError, ValueError):
        return 0.0


def tickets_per_purchase() -> int:
    return _setting_int("wheel_tickets_per_purchase", 0)


def tickets_per_referral() -> int:
    return _setting_int("wheel_tickets_per_referral", 0)


def promo_valid_days() -> int:
    return _setting_int("wheel_promo_days", DEFAULT_PROMO_DAYS, minimum=1)


def prize_ttl_days() -> int:
    return _setting_int("wheel_prize_ttl_days", DEFAULT_PRIZE_TTL_DAYS, minimum=1)


def reminders_enabled() -> bool:
    return (database.get_setting("wheel_notify_enabled") or "1").strip() == "1"


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


def free_spin_wait(user_id: int) -> int:
    """Сколько секунд осталось до бесплатного прокрута."""
    last = _parse(database.get_last_wheel_spin(user_id))
    if not last:
        return 0
    left = (last + timedelta(hours=cooldown_hours()) - _now()).total_seconds()
    return max(0, int(left))


def format_wait(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, minutes = seconds // 3600, (seconds % 3600) // 60
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин"
    return "меньше минуты"


def user_keys(user_id: int) -> list[dict]:
    """Подписки, к которым можно добавить дни — от истекающей к дальней."""
    keys = []
    for key in database.get_user_keys(user_id) or []:
        expiry = _parse(key.get("expiry_date") or key.get("expire_at"))
        keys.append({
            "key_id": key.get("key_id"),
            "host_name": key.get("host_name") or "",
            "key_email": key.get("key_email"),
            "expiry": expiry,
            "expiry_text": expiry.strftime("%d.%m.%Y") if expiry else "—",
        })
    keys.sort(key=lambda k: k["expiry"] or datetime.max)
    # datetime в JSON не сериализуется, а список уходит прямо в мини-апп
    for key in keys:
        key.pop("expiry", None)
    return keys


def pending_prizes(user_id: int) -> list[dict]:
    """Невыданные призы с оставшимся сроком."""
    now = _now()
    database.expire_wheel_prizes(now.strftime(TIME_FORMAT))
    rows = database.get_pending_wheel_prizes(user_id, now.strftime(TIME_FORMAT)) or []
    out = []
    for row in rows:
        expires = _parse(row.get("expires_at"))
        out.append({
            "spin_id": row.get("spin_id"),
            "label": row.get("label"),
            "prize_type": row.get("prize_type"),
            "amount": float(row.get("amount") or 0),
            "expires_at": row.get("expires_at"),
            "expires_in": int((expires - now).total_seconds()) if expires else None,
            "expires_text": expires.strftime("%d.%m.%Y") if expires else "",
        })
    return out


def history(user_id: int, limit: int = 20) -> list[dict]:
    """История призов: что забрано, что ждёт и что сгорело.

    Пустые сектора сюда не попадают: «Мимо» — это не приз, а в списке
    выигрышей они только мешают искать настоящие. В журнале прокрутов у
    администратора они остаются.
    """
    now = _now()
    database.expire_wheel_prizes(now.strftime(TIME_FORMAT))
    rows = database.get_user_wheel_history(user_id, limit * 3) or []
    out = []
    for row in rows:
        if (row.get("prize_type") or PRIZE_NOTHING) == PRIZE_NOTHING or float(row.get("amount") or 0) <= 0:
            continue
        if len(out) >= limit:
            break
        created = _parse(row.get("created_at"))
        out.append({
            "spin_id": row.get("spin_id"),
            "label": row.get("label"),
            "prize_type": row.get("prize_type"),
            "amount": float(row.get("amount") or 0),
            "status": row.get("status") or "done",
            "detail": row.get("detail") or "",
            "date_text": created.strftime("%d.%m.%Y") if created else "",
            "expires_text": (_parse(row.get("expires_at")) or created or now).strftime("%d.%m.%Y")
                            if row.get("expires_at") else "",
        })
    # невыданные наверх: по ним нужно действие, остальное — просто память
    out.sort(key=lambda p: (p["status"] != "pending", -int(p["spin_id"] or 0)))
    return out


def state(user_id: int) -> dict:
    """Всё, что нужно нарисовать колесо и понять, можно ли крутить."""
    prizes = get_prizes()
    tickets = database.get_wheel_tickets(user_id)
    wait = free_spin_wait(user_id)
    waiting = pending_prizes(user_id)

    result = {
        "enabled": is_enabled(),
        "can_spin": False,
        "reason": None,
        "source": None,
        "wait_seconds": wait,
        "cooldown_hours": cooldown_hours(),
        "tickets": tickets,
        "ticket_price": ticket_price(),
        "tickets_per_purchase": tickets_per_purchase(),
        "tickets_per_referral": tickets_per_referral(),
        "notify": database.get_wheel_notify(user_id),
        "prize_ttl_days": prize_ttl_days(),
        "pending": waiting,
        "keys": user_keys(user_id) if waiting else [],
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

    # Невыданные призы прокрут больше не блокируют: они лежат в истории со
    # своим сроком, и человек забирает их, когда появится подписка.
    if wait <= 0:
        result["can_spin"] = True
        result["source"] = "free"
    elif tickets > 0:
        result["can_spin"] = True
        result["source"] = "ticket"
    else:
        result["reason"] = "cooldown"
    return result


def pick(prizes: list[dict]) -> dict:
    """Случайный сектор с учётом весов."""
    return random.choices(prizes, weights=[p["weight"] for p in prizes], k=1)[0]


def _promo_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "WHEEL" + "".join(secrets.choice(alphabet) for _ in range(6))


def _issue_promo(user_id: int, prize: dict) -> tuple[bool, str]:
    """Персональный одноразовый купон победителю."""
    from shop_bot.data_manager import remnawave_repository as rw_repo

    amount = float(prize.get("amount") or 0)
    percent = prize.get("prize_type") == PRIZE_PROMO_PERCENT
    user = database.get_user(user_id) or {}
    username = user.get("username")
    who = f"@{username}" if username else f"ID {user_id}"
    valid_until = _now() + timedelta(days=promo_valid_days())

    for _ in range(5):
        code = _promo_code()
        try:
            created = rw_repo.create_promo_code(
                code,
                discount_percent=amount if percent else None,
                discount_amount=None if percent else amount,
                promo_type="discount",
                usage_limit_total=1,
                usage_limit_per_user=1,
                valid_until=valid_until,
                created_by=user_id,
                description=f"Выигран в колесе удачи пользователем {who} ({prize.get('label')})",
            )
        except ValueError as e:
            logger.error("Колесо: неверный купон в секторе %r: %s", prize.get("label"), e)
            return False, ""
        if created:
            logger.info("Колесо: пользователю %s выдан купон %s", user_id, code)
            size = f"{amount:.0f}%" if percent else f"{amount:.0f} ₽"
            return True, (f"Ваш промокод на скидку {size}: <code>{code}</code>\n"
                          f"Одноразовый, действует до {valid_until.strftime('%d.%m.%Y')}.")
    logger.error("Колесо: не удалось подобрать свободный код купона для %s", user_id)
    return False, ""


async def _add_days(user_id: int, key: dict, days: int) -> tuple[bool, str]:
    """Продлевает конкретную подписку на выигранные дни."""
    from shop_bot.modules import remnawave_api

    result = await remnawave_api.create_or_update_key_on_host(
        host_name=key.get("host_name"),
        email=key.get("key_email"),
        days_to_add=int(days),
        telegram_id=user_id,
    )
    if not result:
        logger.error("Колесо: не удалось продлить ключ %s пользователю %s", key.get("key_id"), user_id)
        return False, ""

    database.update_key_info(
        key_id=key["key_id"],
        new_remnawave_uuid=result.get("client_uuid"),
        new_expiry_ms=result.get("expiry_timestamp_ms"),
    )
    expiry = datetime.fromtimestamp(result["expiry_timestamp_ms"] / 1000, tz=MSK)
    logger.info("Колесо: пользователю %s добавлено %d дн. к ключу %s", user_id, int(days), key.get("key_id"))
    return True, (f"К подписке «{key.get('host_name')}» добавлено <b>{int(days)} дн.</b>\n"
                  f"Действует до {expiry.strftime('%d.%m.%Y %H:%M')}.")


async def _award(user_id: int, prize: dict, keys: list[dict]) -> tuple[str, dict | None, str]:
    """Начисляет приз.

    Возвращает (исход, ключ, текст). Исход: done — выдано, choose — ждём
    выбора подписки, no_subscription / failed — не получилось.
    """
    prize_type = (prize.get("prize_type") or PRIZE_NOTHING).strip()
    amount = float(prize.get("amount") or 0)

    if prize_type == PRIZE_NOTHING or amount <= 0:
        return "done", None, ""

    if prize_type == PRIZE_BALANCE:
        if database.add_to_balance(user_id, amount):
            logger.info("Колесо: пользователю %s начислено %.2f RUB", user_id, amount)
            return "done", None, f"На баланс зачислено <b>{amount:.0f} ₽</b>."
        return "failed", None, ""

    if prize_type in (PRIZE_PROMO_PERCENT, PRIZE_PROMO_FIXED):
        ok, text = _issue_promo(user_id, prize)
        return ("done", None, text) if ok else ("failed", None, "")

    if prize_type == PRIZE_DAYS:
        # Ни одной подписки — приз не пропадает, а ложится в историю до
        # покупки. Несколько — выбирает владелец, а не мы за него.
        if len(keys) != 1:
            return "choose", None, ""
        ok, text = await _add_days(user_id, keys[0], int(amount))
        return ("done", keys[0], text) if ok else ("failed", keys[0], "")

    logger.warning("Колесо: неизвестный тип приза %r", prize_type)
    return "done", None, ""


async def spin(user_id: int) -> dict:
    """Один прокрут: проверка, розыгрыш, начисление, запись в журнал."""
    current = state(user_id)
    if not current["can_spin"]:
        reason = current["reason"] or "cooldown"
        return {"ok": False, "reason": reason, "wait_seconds": current["wait_seconds"],
                "tickets": current["tickets"], "pending": current["pending"],
                "error": DECLINE_TEXT.get(reason, "Сейчас крутить нельзя.")}

    prizes = get_prizes()
    now = _now()
    source = current["source"]
    previous = database.get_last_wheel_spin(user_id)

    # Попытку занимаем до розыгрыша: иначе два быстрых нажатия успевали
    # прокрутить колесо дважды за один кулдаун.
    if source == "free":
        allowed_before = (now - timedelta(hours=current["cooldown_hours"])).strftime(TIME_FORMAT)
        claimed = database.claim_wheel_spin(user_id, now.strftime(TIME_FORMAT), allowed_before)
    else:
        claimed = database.spend_wheel_ticket(user_id)

    if not claimed:
        again = state(user_id)
        return {"ok": False, "reason": again["reason"] or "cooldown", "wait_seconds": again["wait_seconds"],
                "tickets": again["tickets"], "error": DECLINE_TEXT.get(again["reason"] or "cooldown")}

    prize = pick(prizes)
    # Шанс запоминаем сразу: завтра веса могут быть другими, и проверить
    # честность розыгрыша по журналу будет уже нельзя
    total_weight = sum(p["weight"] for p in prizes) or 1
    chance = round(prize["weight"] * 100 / total_weight, 4)
    keys = user_keys(user_id)
    outcome, key, detail = await _award(user_id, prize, keys)

    if outcome == "failed":
        # Приз не выдан — возвращаем попытку, человек не виноват
        if source == "free":
            database.release_wheel_spin(user_id, previous)
        else:
            database.add_wheel_tickets(user_id, 1, "refund", "приз не удалось выдать")
        return {"ok": False, "reason": outcome, "error": DECLINE_TEXT[outcome],
                "tickets": database.get_wheel_tickets(user_id)}

    status = "pending" if outcome == "choose" else "done"
    expires_at = ((now + timedelta(days=prize_ttl_days())).strftime(TIME_FORMAT)
                  if status == "pending" else None)
    spin_id = database.log_wheel_spin_full(user_id, prize, key.get("key_id") if key else None,
                                           status, detail or None, source, expires_at, chance)

    won = (prize.get("prize_type") or PRIZE_NOTHING) != PRIZE_NOTHING and float(prize.get("amount") or 0) > 0
    return {
        "ok": True,
        "won": won,
        "label": prize.get("label"),
        "prize_type": prize.get("prize_type"),
        "amount": float(prize.get("amount") or 0),
        "detail": detail,
        "needs_choice": outcome == "choose",
        "no_subscription": outcome == "choose" and not keys,
        "spin_id": spin_id,
        "expires_text": ((now + timedelta(days=prize_ttl_days())).strftime("%d.%m.%Y")
                         if status == "pending" else ""),
        "prize_ttl_days": prize_ttl_days(),
        "keys": keys if outcome == "choose" else [],
        "source": source,
        "tickets": database.get_wheel_tickets(user_id),
        "cooldown_hours": current["cooldown_hours"],
    }


async def claim_days(user_id: int, key_id: int, spin_id: int | None = None) -> dict:
    """Досыпает выигранные дни в выбранную подписку.

    spin_id обязателен, когда невыданных призов несколько; без него берём
    самый свежий — так работает кнопка сразу после прокрута.
    """
    waiting = pending_prizes(user_id)
    if not waiting:
        return {"ok": False, "error": "Невыданных призов нет."}

    if spin_id is None:
        prize = waiting[0]
    else:
        prize = next((p for p in waiting if int(p["spin_id"]) == int(spin_id)), None)
        if not prize:
            # приз мог сгореть, пока человек выбирал
            row = database.get_wheel_spin(spin_id)
            if row and int(row.get("user_id") or 0) == int(user_id):
                return {"ok": False, "error": DECLINE_TEXT["expired"]}
            return {"ok": False, "error": "Приз не найден."}

    key = next((k for k in user_keys(user_id) if int(k["key_id"]) == int(key_id)), None)
    if not key:
        return {"ok": False, "error": "Подписка не найдена."}

    ok, detail = await _add_days(user_id, key, int(float(prize.get("amount") or 0)))
    if not ok:
        return {"ok": False, "error": DECLINE_TEXT["failed"]}

    database.complete_wheel_spin(prize["spin_id"], key["key_id"], detail)
    return {"ok": True, "label": prize.get("label"), "detail": detail}


def buy_ticket(user_id: int, count: int = 1) -> dict:
    """Покупка билетов за баланс.

    За деньги напрямую билеты не продаём: сумма мелкая, а через баланс
    покупка проходит мгновенно и без счёта в платёжной системе.
    """
    price = ticket_price()
    if price <= 0:
        return {"ok": False, "error": DECLINE_TEXT["tickets_off"]}
    count = max(1, int(count))
    total = round(price * count, 2)

    if not database.deduct_from_balance(user_id, total):
        return {"ok": False, "error": DECLINE_TEXT["not_enough"], "price": price}

    if not database.add_wheel_tickets(user_id, count, "purchase", f"куплено за {total:.2f} RUB"):
        database.add_to_balance(user_id, total)
        return {"ok": False, "error": DECLINE_TEXT["failed"]}

    logger.info("Колесо: пользователь %s купил %d билет(ов) за %.2f RUB", user_id, count, total)
    return {"ok": True, "tickets": database.get_wheel_tickets(user_id), "spent": total}


def grant_for_purchase(user_id: int, reason_note: str | None = None) -> int:
    """Билеты за оплаченную подписку."""
    amount = tickets_per_purchase()
    if amount <= 0 or not is_enabled():
        return 0
    if database.add_wheel_tickets(user_id, amount, "purchase_bonus", reason_note):
        logger.info("Колесо: %s получил %d билет(ов) за покупку", user_id, amount)
        return amount
    return 0


def grant_for_referral(user_id: int, reason_note: str | None = None) -> int:
    """Билеты пригласившему за нового реферала."""
    amount = tickets_per_referral()
    if amount <= 0 or not is_enabled():
        return 0
    if database.add_wheel_tickets(user_id, amount, "referral_bonus", reason_note):
        logger.info("Колесо: %s получил %d билет(ов) за реферала", user_id, amount)
        return amount
    return 0
