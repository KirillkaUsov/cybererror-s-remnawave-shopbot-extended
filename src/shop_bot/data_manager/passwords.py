"""Хеширование паролей личного кабинета.

Пароли клиентов лежали в БД открытым текстом, а вход сравнивал их построчно.
Ст. 19 152-ФЗ требует от оператора мер защиты персональных данных, и хранение
паролей в открытом виде им противоречит — плюс любая утечка файла БД сразу
отдаёт чужие пароли, которые люди переиспользуют на других сервисах.

Формат хранения:

    pbkdf2_sha256$<итераций>$<соль_hex>$<хеш_hex>

Старые значения не в этом формате считаются legacy: вход по ним ещё работает,
но при первом успешном входе значение переписывается на хеш. Иначе пришлось бы
разом отключить уже существующие аккаунты.
"""

import hashlib
import hmac
import os

ALGO = "pbkdf2_sha256"
ITERATIONS = 260_000
SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """Возвращает строку для записи в users.auth_pass."""
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGO}${iterations}${salt.hex()}${digest.hex()}"


def is_hashed(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(ALGO + "$")


def verify_password(password: str, stored: str | None) -> tuple[bool, bool]:
    """Проверяет пароль.

    Возвращает (пароль_верный, нужно_перехешировать). Второй флаг поднимается
    для legacy-значений и при смене числа итераций — вызывающий код должен
    сохранить свежий хеш.
    """
    if not stored or not password:
        return False, False

    stored = str(stored)

    if not is_hashed(stored):
        # legacy: в БД открытый текст. Сравниваем в постоянном времени, чтобы
        # не подсказывать длину и содержимое по времени ответа.
        ok = hmac.compare_digest(stored.encode("utf-8"), password.encode("utf-8"))
        return ok, ok

    try:
        _, iters_raw, salt_hex, digest_hex = stored.split("$", 3)
        iterations = int(iters_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        # битая запись — вход запрещаем, но и не падаем
        return False, False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    ok = hmac.compare_digest(actual, expected)
    return ok, ok and iterations != ITERATIONS
