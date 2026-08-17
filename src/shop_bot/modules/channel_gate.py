"""Подписка на канал как условие для пробного периода.

Обязательная подписка на входе отпугивает: человек ещё ничего не получил,
а с него уже что-то требуют. А вот перед бесплатными днями просьба
подписаться выглядит честным обменом — поэтому проверка живёт отдельной
настройкой и срабатывает ровно в одном месте.

Ответ кэшируем на минуту: экран пробного периода спрашивает статус при
каждом открытии, а Telegram считает getChatMember обычным запросом с общим
лимитом.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

CACHE_TTL = 60
_cache: dict[int, tuple[float, bool]] = {}

_MEMBER_STATUSES = ("member", "administrator", "creator")


def _setting(key: str) -> str | None:
    from shop_bot.data_manager.remnawave_repository import get_setting
    return get_setting(key)


def channel_url() -> str:
    return (_setting("channel_url") or "").strip()


def required() -> bool:
    """Нужна ли подписка для пробного периода прямо сейчас."""
    flag = (_setting("trial_requires_subscription") or "").strip().lower()
    return flag in ("1", "true", "on", "yes") and bool(channel_url())


def chat_id() -> str | None:
    """Канал в том виде, в каком его понимает Bot API."""
    url = channel_url()
    if not url:
        return None
    if url.startswith("@"):
        return url
    if "t.me/" in url:
        name = url.rstrip("/").split("/")[-1]
        # Приватный канал даёт ссылку-приглашение вида t.me/+AbCdEf —
        # по ней участника не проверить, нужен числовой id в настройке.
        if not name or name.startswith("+"):
            return None
        return "@" + name
    return None


async def is_member(user_id: int, bot=None) -> bool:
    """Подписан ли человек. При любой ошибке отвечаем «да».

    Заперев человека из-за нашего же сбоя связи с Telegram, мы потеряем его
    насовсем; пропустив одного неподписанного — ничего.
    """
    target = chat_id()
    if not target:
        return True

    hit = _cache.get(int(user_id))
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]

    own = None
    try:
        if bot is None:
            from aiogram import Bot
            token = _setting("telegram_bot_token")
            if not token:
                return True
            own = bot = Bot(token=token)
        member = await bot.get_chat_member(chat_id=target, user_id=int(user_id))
        ok = str(getattr(member, "status", "")).lower().split(".")[-1] in _MEMBER_STATUSES
    except Exception as e:
        logger.info("Не удалось проверить подписку %s на %s: %s", user_id, target, e)
        return True
    finally:
        if own is not None:
            try:
                await own.session.close()
            except Exception:
                pass

    _cache[int(user_id)] = (time.monotonic(), ok)
    return ok


def forget(user_id: int) -> None:
    """Сбросить кэш — человек говорит, что только что подписался."""
    _cache.pop(int(user_id), None)
