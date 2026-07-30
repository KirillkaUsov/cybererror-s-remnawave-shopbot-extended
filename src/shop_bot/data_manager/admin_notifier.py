"""Рассылка уведомлений администраторам.

Раньше каждое место собирало получателей по-своему: где-то через
get_admin_ids(), где-то перебором таблицы users, а вход в панель уходил
единственному admin_telegram_id. Из-за этого дополнительные администраторы
получали лишь часть уведомлений. Здесь один список получателей на всех.
"""

from __future__ import annotations

import asyncio
import logging

from shop_bot.data_manager import remnawave_repository as rw_repo

logger = logging.getLogger(__name__)


def admin_ids(exclude: int | None = None) -> list[int]:
    """Все администраторы: и главный, и дополнительные.

    Порядок стабильный, чтобы уведомления приходили предсказуемо, а не в
    случайном порядке множества.
    """
    try:
        ids = {int(x) for x in (rw_repo.get_admin_ids() or set())}
    except Exception as e:
        logger.error("Уведомления: не удалось получить список администраторов: %s", e)
        return []
    if exclude is not None:
        ids.discard(int(exclude))
    return sorted(ids)


async def notify_admins(bot, text: str, *, reply_markup=None, parse_mode: str = "HTML",
                        exclude: int | None = None, **kwargs) -> int:
    """Отправляет текст каждому администратору. Возвращает число доставленных.

    Ошибка доставки одному не мешает остальным: администратор мог не
    запускать бота или заблокировать его.
    """
    if not bot:
        return 0
    targets = admin_ids(exclude)
    if not targets:
        logger.warning("Уведомления: администраторы не настроены, сообщение не отправлено")
        return 0

    sent = 0
    for chat_id in targets:
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup,
                                   parse_mode=parse_mode, **kwargs)
            sent += 1
        except Exception as e:
            logger.warning("Уведомления: не удалось написать администратору %s: %s", chat_id, e)
    return sent


def notify_admins_threadsafe(bot, loop, text: str, *, reply_markup=None,
                             parse_mode: str = "HTML") -> None:
    """То же самое из синхронного кода — например из Flask-панели, которая
    живёт в своём потоке и не может дождаться корутины."""
    if not bot:
        return
    coro = notify_admins(bot, text, reply_markup=reply_markup, parse_mode=parse_mode)
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, loop)
        return
    try:
        asyncio.run(coro)
    except Exception as e:
        logger.error("Уведомления: не удалось отправить из синхронного кода: %s", e)
