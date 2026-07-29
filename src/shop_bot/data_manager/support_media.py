"""
Хранилище вложений технической поддержки.

Схема гибридная:
  * file_id Telegram — чтобы мгновенно переслать файл обратно в чат,
    не выгружая его повторно;
  * локальная копия — чтобы показать вложение в админ-панели и не
    потерять его при смене токена бота (file_id к токену привязан).

Файлы лежат по пути <корень>/support/<ticket_id>/<uuid>.<ext>,
разбивка по тикетам упрощает ручную чистку и перенос.
"""

import logging
import mimetypes
import re
import shutil
import uuid
from pathlib import Path

from . import database

logger = logging.getLogger(__name__)


# Корень хранилища выбираем рядом с базой: в докере это /app/project,
# при локальном запуске — текущая папка. Проверяем не сам каталог, а
# признаки развёрнутого проекта внутри: пустой /app/project мог остаться
# от другого модуля и уводил медиа в несуществующую папку.
_DOCKER_ROOT = Path("/app/project")
if (_DOCKER_ROOT / "users.db").exists() or (_DOCKER_ROOT / "src").exists():
    MEDIA_ROOT = _DOCKER_ROOT / "media"
else:
    MEDIA_ROOT = Path("media")

SUPPORT_MEDIA_DIR = MEDIA_ROOT / "support"

# Расширения, которые показываем как картинку / видео / аудио в админке
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}
VIDEO_EXTS = {"mp4", "mov", "webm", "m4v"}
AUDIO_EXTS = {"ogg", "oga", "opus", "mp3", "m4a", "wav"}

# Голосовые и кружки Telegram присылает всегда, независимо от списка
# разрешённых форматов — их расширение пользователь не выбирает.
TELEGRAM_NATIVE_KINDS = {"voice", "video_note"}


def ensure_dirs() -> None:
    try:
        SUPPORT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Медиа: не удалось создать каталог {SUPPORT_MEDIA_DIR}: {e}")


def get_settings() -> dict:
    return database.get_support_media_settings()


def guess_ext(file_name: str | None, mime_type: str | None) -> str:
    """Расширение по имени файла, а если его нет — по MIME-типу."""
    if file_name and "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower()
        if re.fullmatch(r"[a-z0-9]{1,6}", ext):
            return ext
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type.split(";")[0].strip())
        if guessed:
            return guessed.lstrip(".").lower()
    return "bin"


def kind_for_ext(ext: str) -> str:
    ext = (ext or "").lower().lstrip(".")
    if ext in IMAGE_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return "document"


def validate(file_name: str | None, mime_type: str | None, size: int,
             kind: str | None = None) -> tuple[bool, str, str]:
    """
    Проверяет вложение по настройкам админки.
    Возвращает (можно_ли, текст_ошибки, расширение).

    Голосовые и видеокружки проверку формата не проходят: их расширение
    задаёт сам Telegram, требовать его в списке разрешённых бессмысленно.
    """
    cfg = get_settings()
    if not cfg["enabled"]:
        return False, "Отправка файлов отключена администратором", ""

    ext = guess_ext(file_name, mime_type)
    if kind not in TELEGRAM_NATIVE_KINDS and ext not in cfg["allowed"]:
        return False, f"Формат .{ext} не разрешён. Доступны: {', '.join(cfg['allowed'])}", ext

    if size and size > cfg["max_bytes"]:
        limit = cfg["max_mb"]
        return False, f"Файл больше {limit:g} МБ", ext

    return True, "", ext


def _target_path(ticket_id: int, ext: str) -> Path:
    folder = SUPPORT_MEDIA_DIR / str(int(ticket_id))
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{uuid.uuid4().hex}.{ext}"


def rel_path(path: Path | str) -> str:
    """Путь относительно корня — его и держим в БД, чтобы можно было переносить."""
    try:
        return str(Path(path).relative_to(MEDIA_ROOT))
    except Exception:
        return str(path)


def abs_path(stored: str | None) -> Path | None:
    if not stored:
        return None
    p = Path(stored)
    if not p.is_absolute():
        p = MEDIA_ROOT / p
    # Путь обязан быть абсолютным: Flask send_file резолвит относительные
    # пути от каталога приложения (src/shop_bot/webhook_server), а не от
    # рабочей директории, и падал с FileNotFoundError.
    p = p.resolve()
    return p if p.exists() else None


def save_bytes(ticket_id: int, data: bytes, ext: str) -> str | None:
    """Кладёт файл на диск и возвращает относительный путь."""
    try:
        ensure_dirs()
        path = _target_path(ticket_id, ext)
        path.write_bytes(data)
        return rel_path(path)
    except Exception as e:
        logger.error(f"Медиа: не удалось сохранить файл тикета {ticket_id}: {e}")
        return None


async def download_from_telegram(bot, file_id: str, ticket_id: int, ext: str) -> tuple[str | None, int]:
    """
    Забирает файл из Telegram в локальное хранилище.
    Возвращает (относительный путь, размер). Ошибка не критична —
    file_id остаётся, файл можно будет получить позже.
    """
    try:
        ensure_dirs()
        tg_file = await bot.get_file(file_id)
        path = _target_path(ticket_id, ext)
        await bot.download_file(tg_file.file_path, destination=str(path))
        size = path.stat().st_size if path.exists() else 0
        return rel_path(path), size
    except Exception as e:
        logger.warning(f"Медиа: не удалось скачать файл {file_id} из Telegram: {e}")
        return None, 0


def delete_file(stored: str | None) -> bool:
    p = abs_path(stored)
    if not p:
        return False
    try:
        p.unlink()
        return True
    except Exception as e:
        logger.warning(f"Медиа: не удалось удалить файл {stored}: {e}")
        return False


def delete_ticket_files(ticket_id: int) -> int:
    """Удаляет всю папку тикета. Возвращает число убранных файлов."""
    folder = SUPPORT_MEDIA_DIR / str(int(ticket_id))
    if not folder.exists():
        return 0
    try:
        count = sum(1 for _ in folder.rglob("*") if _.is_file())
        shutil.rmtree(folder, ignore_errors=True)
        return count
    except Exception as e:
        logger.warning(f"Медиа: не удалось удалить каталог тикета {ticket_id}: {e}")
        return 0


def disk_usage() -> dict:
    """Сколько реально занято на диске (не по данным БД, а по факту)."""
    total = 0
    files = 0
    try:
        if SUPPORT_MEDIA_DIR.exists():
            for f in SUPPORT_MEDIA_DIR.rglob("*"):
                if f.is_file():
                    files += 1
                    total += f.stat().st_size
    except Exception as e:
        logger.warning(f"Медиа: не удалось посчитать занятое место: {e}")
    return {"files": files, "bytes": total}


def cleanup(older_than_days: int = 0, orphan_only: bool = False) -> dict:
    """
    Убирает вложения: осиротевшие (тикет удалён) и/или старше N дней.
    Чистит и записи в БД, и сами файлы.
    """
    rows = database.get_media_to_cleanup(older_than_days=older_than_days, orphan_only=orphan_only)
    removed_files = 0
    freed = 0
    for row in rows or []:
        freed += int(row.get("file_size") or 0)
        if delete_file(row.get("local_path")):
            removed_files += 1
        database.delete_support_media(row.get("media_id"))

    stray = purge_stray_files()
    return {
        "records": len(rows or []),
        "files": removed_files,
        "freed_bytes": freed,
        "stray": stray,
    }


def purge_stray_files() -> int:
    """
    Файлы, которых нет ни в одной записи БД (например, остались после
    сбоя при загрузке). Удаляем, чтобы диск не забивался молча.
    """
    try:
        if not SUPPORT_MEDIA_DIR.exists():
            return 0
        known = set()
        for row in database.list_support_media(limit=100000, offset=0) or []:
            p = abs_path(row.get("local_path"))
            if p:
                known.add(str(p.resolve()))

        removed = 0
        for f in SUPPORT_MEDIA_DIR.rglob("*"):
            if f.is_file() and str(f.resolve()) not in known:
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
        return removed
    except Exception as e:
        logger.warning(f"Медиа: ошибка чистки бесхозных файлов: {e}")
        return 0


def human_size(num: int | float) -> str:
    num = float(num or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if num < 1024 or unit == "ГБ":
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} ГБ"
