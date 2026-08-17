"""Когда поддержка на связи.

Два независимых переключателя: общий рубильник и часы приёма. Рубильник
старше расписания — если поддержку выключили совсем, обещать «вернитесь
в рабочее время» нечестно, никто не вернётся.

Правило, в котором мы расходимся с исходным ботом: закрытые часы не пускают
только НОВОЕ обращение. Ответ в уже открытый тикет проходит всегда — там
человека о чём-то спросили, и потерять его ответ хуже, чем прочитать его
утром вместе с остальными.
"""

from __future__ import annotations

from datetime import datetime

from shop_bot.config import get_msk_time

OFF_TEXT = ("<b>👨‍💻 Поддержка сейчас не на связи.</b>\n\n"
            "Мы вернёмся и ответим. Спасибо за понимание.")

DEFAULT_START = "10:00"
DEFAULT_END = "23:00"


def _flag(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "off", "no", "")


def _parse(value: str | None, fallback: str):
    try:
        return datetime.strptime((value or fallback).strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        return datetime.strptime(fallback, "%H:%M").time()


def unavailable_text(get_setting) -> str | None:
    """Текст отказа, если обращение сейчас принимать нельзя. Иначе None.

    `get_setting` передаётся снаружи: этим модулем пользуются и бот
    поддержки, и кабинет, а тянуть базу они привыкли по-разному.
    """
    if not _flag(get_setting("support_enabled"), True):
        return OFF_TEXT
    if not _flag(get_setting("support_schedule_enabled"), False):
        return None

    start = _parse(get_setting("support_schedule_start"), DEFAULT_START)
    end = _parse(get_setting("support_schedule_end"), DEFAULT_END)
    if start == end:
        # Одинаковые границы читаем как «круглосуточно», а не как «никогда»:
        # незаполненное расписание не должно закрывать поддержку насовсем.
        return None

    now = get_msk_time().time()
    # Смена через полночь (23:00–10:00) — это два отрезка, а не один.
    inside = start <= now < end if start < end else (now >= start or now < end)
    if inside:
        return None
    return ("<b>👨‍💻 Поддержка сейчас не на связи.</b>\n\n"
            f"Мы отвечаем с {start.strftime('%H:%M')} до {end.strftime('%H:%M')} по Москве. "
            "Напишите, пожалуйста, в рабочее время — так ответ придёт быстрее.")


def plain(text: str | None) -> str:
    """То же самое без тегов — для кабинета, где текст приходит в JSON."""
    if not text:
        return ""
    return (text.replace("<b>", "").replace("</b>", "")
                .replace("<i>", "").replace("</i>", ""))
