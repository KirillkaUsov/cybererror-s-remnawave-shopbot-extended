"""Картинки из рассылок, которые должны пережить саму рассылку.

Телеграму хватает file_id, а панель и вовсе удаляет загруженный файл сразу
после отправки. Ящику уведомлений в кабинете нужна ссылка, по которой браузер
сходит через месяц, — поэтому один экземпляр файла откладываем сюда.

Имя файла — хеш содержимого: одна рассылка кладёт по строке каждому из сотни
человек, а файл при этом остаётся один.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(__file__).resolve().parent.parent / "webapp" / "static" / "broadcasts"
URL_PREFIX = "/static/broadcasts"

# То, что браузер покажет сам. Всё остальное в кабинет не кладём: ссылка на
# файл, который нечем открыть, хуже её отсутствия.
_EXTENSIONS = {
    "photo": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "video": {".mp4", ".webm", ".mov"},
    "animation": {".gif", ".mp4", ".webm"},
}

MAX_BYTES = 25 * 1024 * 1024


def _ensure_dir() -> bool:
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as e:
        logger.warning("Не удалось создать папку для картинок рассылки: %s", e)
        return False


def _normalize_type(media_type: str | None, suffix: str) -> str | None:
    media_type = (media_type or "").strip().lower()
    if media_type == "animation":
        # Для браузера гифка-из-mp4 — это видео с автоповтором, а не картинка.
        media_type = "photo" if suffix == ".gif" else "video"
    if media_type not in ("photo", "video"):
        return None
    allowed = _EXTENSIONS["photo"] | _EXTENSIONS["video"]
    return media_type if suffix in allowed else None


def store_bytes(data: bytes, suffix: str, media_type: str | None) -> tuple[str, str] | None:
    """Кладёт файл рядом с остальной статикой. Возвращает (ссылка, тип)."""
    if not data or len(data) > MAX_BYTES:
        return None
    suffix = ("." + suffix.lstrip(".")).lower()
    kind = _normalize_type(media_type, suffix)
    if not kind or not _ensure_dir():
        return None
    name = hashlib.sha1(data).hexdigest()[:20] + suffix
    target = MEDIA_DIR / name
    if not target.exists():
        try:
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, target)
        except OSError as e:
            logger.warning("Не удалось сохранить картинку рассылки: %s", e)
            return None
    return f"{URL_PREFIX}/{name}", kind


def store_file(path: str | os.PathLike, media_type: str | None) -> tuple[str, str] | None:
    """То же самое для файла, который панель уже положила на диск."""
    source = Path(path)
    try:
        if not source.is_file() or source.stat().st_size > MAX_BYTES:
            return None
    except OSError:
        return None
    kind = _normalize_type(media_type, source.suffix.lower())
    if not kind or not _ensure_dir():
        return None
    try:
        digest = hashlib.sha1(source.read_bytes()).hexdigest()[:20]
    except OSError as e:
        logger.warning("Не удалось прочитать медиафайл рассылки %s: %s", source, e)
        return None
    target = MEDIA_DIR / (digest + source.suffix.lower())
    if not target.exists():
        try:
            shutil.copy2(source, target)
        except OSError as e:
            logger.warning("Не удалось скопировать медиафайл рассылки: %s", e)
            return None
    return f"{URL_PREFIX}/{target.name}", kind
