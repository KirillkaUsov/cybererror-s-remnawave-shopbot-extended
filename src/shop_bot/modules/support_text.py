"""Служебные пометки о вложениях в переписке поддержки.

В `support_messages.content` фотография сохраняется как «[Фото] подпись».
Пометка нужна там, где само вложение показать нельзя — в списке обращений,
в уведомлении админу, в поиске. Там, где картинка и так висит рядом, она
только дублирует очевидное, поэтому на показе её убирают.

Правило одно на все три поверхности — бот, панель и мини-апп, — иначе
пометка неизбежно всплывает то в одном месте, то в другом.
"""

from __future__ import annotations

import re

# Названия ровно те, что кладёт бот и загрузка файлов
LABEL_RE = re.compile(r'^\[(Фото|Видео|Голосовое|Кружок|Аудио|Документ:[^\]]*)\]\s*')

# Чем заменить пометку, когда текста рядом нет и вложение не показать
SPOKEN = {
    "photo": "фотография",
    "video": "видео",
    "voice": "голосовое сообщение",
    "video_note": "видеокружок",
    "audio": "аудиозапись",
    "document": "файл",
}


# Обратное соответствие: какую пометку поставить вложению этого вида
LABEL = {
    "photo": "[Фото]",
    "video": "[Видео]",
    "voice": "[Голосовое]",
    "video_note": "[Кружок]",
    "audio": "[Аудио]",
}


def label_for(kind: str, file_name: str | None = None) -> str:
    """Пометка для сообщения с вложением — одна на бота, панель и мини-апп."""
    if kind in LABEL:
        return LABEL[kind]
    return f"[Документ: {file_name}]" if file_name else "[Документ]"


def strip_label(text: str | None) -> str:
    """Текст сообщения без служебной пометки о вложении."""
    return LABEL_RE.sub('', (text or '').strip()).strip()


def has_label(text: str | None) -> bool:
    return bool(LABEL_RE.match((text or '').strip()))


def describe(kinds) -> str:
    """«фотография», «2 файла» — чем подписать сообщение без текста."""
    kinds = list(kinds or [])
    if not kinds:
        return ""
    if len(kinds) == 1:
        return SPOKEN.get(kinds[0], "файл")
    return f"{len(kinds)} вложения" if len(kinds) < 5 else f"{len(kinds)} вложений"


def preview(text: str | None, kinds=None, limit: int = 60) -> str:
    """Строка для списка обращений: текст, а если его нет — что приложено."""
    body = strip_label(text)
    if not body:
        body = describe(kinds) or strip_label(text) or ""
        if not body and has_label(text):
            # вложение не сохранилось — оставляем исходную пометку
            body = (text or '').strip()
    return body if len(body) <= limit else body[:limit - 1].rstrip() + "…"
