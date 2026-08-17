#!/usr/bin/env python3
"""Сообщения тем, кто остался в старом боте.

Старый бот живёт на другом сервере и про новую систему ничего не знает —
поэтому логика вся здесь. Мы забираем копию его базы по SSH, сравниваем с
базой новой системы и шлём сообщения его же токеном через Bot API. На самом
старом сервере при этом ничего не меняется и ничего не запускается.

Три когорты, три разных повода написать:

  переезд  — подписки нет и в новой системе человека нет. Ежедневное
             напоминание, что бот сменил адрес. Прекращается сразу, как
             только человек появится в новой базе.
  срок-А   — оплаченная подписка заканчивается через N дней, новый бот
             человек ни разу не открывал. Нужен адрес и объяснение.
  срок-Б   — то же, но аккаунт в новой системе уже есть. Хватает даты и
             ссылки на оплату.

Кому что уже отправлено — в своей маленькой базе рядом со скриптом. Она
единственное состояние, которое скрипт заводит.

Ничего не уходит, пока не передашь --send. По умолчанию только показывает.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

# ── что можно менять руками ────────────────────────────────────────────────

# Старый бот: где лежит его база и как туда попасть.
OLD_HOST = "ge3.chorusconnect.cc"
OLD_PORT = 22
OLD_USER = "root"
OLD_KEY = "/root/.ssh/id_chorus"
OLD_DB = "/root/remnawave-shopbot/users.db"

NEW_DB = "/root/remnawave-shopbot/users.db"
STATE_DB = "/root/remnawave-shopbot/tools/migration_nudge_state.db"

NEW_BOT = "ChorusConnect_bot"
CHANNEL = "https://t.me/ChorusConnect"

# Через сколько дней до конца подписки писать про срок.
WARN_DAYS = 3

# Ежедневное напоминание о переезде: как часто и сколько раз максимум.
# 0 в MIGRATE_MAX_SENDS — без ограничений, как и просили.
MIGRATE_EVERY_HOURS = 24
MIGRATE_MAX_SENDS = 0

# Пауза между сообщениями. Telegram разрешает около 30 в секунду, но для
# рассылки в несколько сотен адресов спокойнее держаться заметно ниже.
SEND_DELAY = 0.12

# Ключ дольше этого срока — вечная подписка, её владельцы уже переведены.
FOREVER_DAYS = 730

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("nudge")


# ── тексты ─────────────────────────────────────────────────────────────────

TEXT_MIGRATE = (
    "🚛 Этот бот <b>переехал</b>, новые подписки и продления теперь в другом боте\n"
    f"🌐 Новый никнейм <b>@{NEW_BOT}</b>\n"
    f'⚡ Подробнее в <a href="{CHANNEL}"><b>нашем ТГК</b></a>'
)


def text_deadline_a(when: dt.datetime) -> str:
    """Подписка кончается, а нового бота человек ещё не видел."""
    return (
        f"⏳ Ваша подписка заканчивается <b>{when.strftime('%d.%m')}</b>\n\n"
        "Продлить здесь уже нельзя — мы работаем в другом боте: "
        f"<b>@{NEW_BOT}</b>. Та же команда, новые серверы и личный кабинет "
        "в браузере.\n\n"
        f"👉 https://t.me/{NEW_BOT}\n\n"
        "Хотите перенести оставшиеся дни — напишите в поддержку нового бота "
        f"до {when.strftime('%d.%m')}."
    )


def text_deadline_b(when: dt.datetime) -> str:
    """Аккаунт в новой системе уже есть — остаётся выбрать тариф."""
    return (
        f"⏳ Ваша подписка заканчивается <b>{when.strftime('%d.%m')}</b>\n\n"
        f"Аккаунт в <b>@{NEW_BOT}</b> у вас уже есть — осталось выбрать тариф, "
        "всё остальное на месте.\n\n"
        f"👉 https://t.me/{NEW_BOT}"
    )


# ── данные ─────────────────────────────────────────────────────────────────

def fetch_old_db() -> Path:
    """Снимок базы старого бота.

    Именно снимок, а не копия файла: бот пишет в базу прямо сейчас, и
    обычный scp может утащить её в середине транзакции. sqlite3.backup
    на той стороне делает согласованную копию.
    """
    tmp = Path(tempfile.mkdtemp(prefix="oldbot-")) / "users.db"
    remote_tmp = "/tmp/nudge-snapshot.db"
    ssh = ["ssh", "-i", OLD_KEY, "-p", str(OLD_PORT),
           "-o", "StrictHostKeyChecking=no",
           "-o", "UserKnownHostsFile=/root/.ssh/known_hosts_chorus",
           "-o", "ConnectTimeout=15", "-o", "BatchMode=yes",
           f"{OLD_USER}@{OLD_HOST}"]
    snap = (
        "python3 - <<'EOF'\n"
        "import sqlite3\n"
        f"src = sqlite3.connect({OLD_DB!r})\n"
        f"dst = sqlite3.connect({remote_tmp!r})\n"
        "src.backup(dst); dst.close(); src.close()\n"
        "EOF"
    )
    subprocess.run(ssh + [snap], check=True, capture_output=True, timeout=180)
    subprocess.run(
        ["scp", "-i", OLD_KEY, "-P", str(OLD_PORT),
         "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/root/.ssh/known_hosts_chorus",
         f"{OLD_USER}@{OLD_HOST}:{remote_tmp}", str(tmp)],
        check=True, capture_output=True, timeout=300)
    subprocess.run(ssh + [f"rm -f {shlex.quote(remote_tmp)}"], capture_output=True, timeout=60)
    return tmp


def cohorts(old_path: Path) -> dict[str, list[tuple[int, dt.datetime | None]]]:
    old = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True); old.row_factory = sqlite3.Row
    new = sqlite3.connect(f"file:{NEW_DB}?mode=ro", uri=True); new.row_factory = sqlite3.Row
    now = dt.datetime.now()
    forever_after = now + dt.timedelta(days=FOREVER_DAYS)

    all_old = {r["telegram_id"] for r in old.execute("SELECT telegram_id FROM users")}
    banned = {r["telegram_id"] for r in old.execute(
        "SELECT telegram_id FROM users WHERE is_banned = 1")}
    new_users = {r["telegram_id"] for r in new.execute("SELECT telegram_id FROM users")}
    new_keyed = {r["user_id"] for r in new.execute("SELECT DISTINCT user_id FROM vpn_keys")}

    live: dict[int, dt.datetime] = {}
    forever: set[int] = set()
    for r in old.execute("SELECT user_id, expire_at FROM vpn_keys"):
        try:
            when = dt.datetime.strptime(str(r["expire_at"])[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if when <= now:
            continue
        if when > forever_after:
            forever.add(r["user_id"])
            continue
        if r["user_id"] not in live or when > live[r["user_id"]]:
            live[r["user_id"]] = when
    old.close(); new.close()

    # Переезд: живой подписки нет и в новой системе человека нет.
    migrate = sorted(all_old - set(live) - forever - new_users - banned)

    # Срок: подписка кончается на днях, а ключа в новой системе так и нет.
    edge = now + dt.timedelta(days=WARN_DAYS)
    soon = {u: w for u, w in live.items()
            if u not in new_keyed and u not in banned and now < w <= edge}

    return {
        "переезд": [(u, None) for u in migrate],
        "срок-А": sorted(((u, w) for u, w in soon.items() if u not in new_users)),
        "срок-Б": sorted(((u, w) for u, w in soon.items() if u in new_users)),
    }


# ── состояние ──────────────────────────────────────────────────────────────

def state() -> sqlite3.Connection:
    Path(STATE_DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(STATE_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS sent (
        telegram_id INTEGER NOT NULL,
        kind        TEXT    NOT NULL,
        sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ok          INTEGER NOT NULL DEFAULT 1,
        error       TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sent ON sent(telegram_id, kind, sent_at)")
    # Заблокировавшие бота: повторять им нечего, Telegram всё равно откажет.
    c.execute("""CREATE TABLE IF NOT EXISTS blocked (
        telegram_id INTEGER PRIMARY KEY,
        seen_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.commit()
    return c


def due(st: sqlite3.Connection, uid: int, kind: str) -> bool:
    if st.execute("SELECT 1 FROM blocked WHERE telegram_id = ?", (uid,)).fetchone():
        return False
    if kind != "переезд":
        # Про срок пишем один раз на подписку — второго раза не будет.
        return not st.execute(
            "SELECT 1 FROM sent WHERE telegram_id = ? AND kind = ? AND ok = 1 "
            "AND sent_at > datetime('now', '-30 days')", (uid, kind)).fetchone()
    row = st.execute(
        "SELECT COUNT(*) n, MAX(sent_at) last FROM sent "
        "WHERE telegram_id = ? AND kind = ? AND ok = 1", (uid, kind)).fetchone()
    count, last = row[0], row[1]
    if MIGRATE_MAX_SENDS and count >= MIGRATE_MAX_SENDS:
        return False
    if not last:
        return True
    try:
        prev = dt.datetime.strptime(last[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return (dt.datetime.utcnow() - prev).total_seconds() >= MIGRATE_EVERY_HOURS * 3600


# ── отправка ───────────────────────────────────────────────────────────────

async def send(token: str, uid: int, text: str) -> tuple[bool, str | None]:
    body = urllib.parse.urlencode({
        "chat_id": uid, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def call():
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=25) as r:
                return True, None
        except urllib.error.HTTPError as e:
            try:
                return False, json.load(e).get("description", str(e.code))
            except Exception:
                return False, f"HTTP {e.code}"
        except Exception as e:
            return False, str(e)[:120]

    return await asyncio.to_thread(call)


BLOCKED_MARKERS = ("bot was blocked", "user is deactivated", "chat not found",
                   "bot can't initiate", "user not found")


async def run(kinds: list[str], limit: int | None, do_send: bool) -> None:
    log.info("Снимаю базу старого бота…")
    snapshot = fetch_old_db()
    token = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True).execute(
        "SELECT value FROM bot_settings WHERE key = 'telegram_bot_token'").fetchone()[0]

    groups = cohorts(snapshot)
    st = state()

    for kind in kinds:
        people = groups.get(kind, [])
        ready = [(u, w) for u, w in people if due(st, u, kind)]
        if limit:
            ready = ready[:limit]
        log.info("%s: всего %d, к отправке сейчас %d", kind, len(people), len(ready))
        if not ready:
            continue

        if not do_send:
            for uid, when in ready[:5]:
                text = (TEXT_MIGRATE if kind == "переезд"
                        else text_deadline_a(when) if kind == "срок-А"
                        else text_deadline_b(when))
                log.info("  [показ] %s\n%s\n", uid, text)
            if len(ready) > 5:
                log.info("  …и ещё %d человек", len(ready) - 5)
            continue

        ok = fail = 0
        for uid, when in ready:
            text = (TEXT_MIGRATE if kind == "переезд"
                    else text_deadline_a(when) if kind == "срок-А"
                    else text_deadline_b(when))
            good, err = await send(token, uid, text)
            st.execute("INSERT INTO sent (telegram_id, kind, ok, error) VALUES (?,?,?,?)",
                       (uid, kind, 1 if good else 0, err))
            if good:
                ok += 1
            else:
                fail += 1
                if err and any(m in err.lower() for m in BLOCKED_MARKERS):
                    st.execute("INSERT OR IGNORE INTO blocked (telegram_id) VALUES (?)", (uid,))
            st.commit()
            await asyncio.sleep(SEND_DELAY)
        log.info("%s: доставлено %d, не доставлено %d", kind, ok, fail)

    st.close()
    try:
        os.remove(snapshot)
        os.rmdir(snapshot.parent)
    except OSError:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kind", action="append", choices=["переезд", "срок-А", "срок-Б"],
                   help="какие когорты обработать (по умолчанию все)")
    p.add_argument("--limit", type=int, help="взять не больше стольких человек из когорты")
    p.add_argument("--send", action="store_true",
                   help="действительно отправить. Без него скрипт только показывает")
    a = p.parse_args()
    kinds = a.kind or ["переезд", "срок-А", "срок-Б"]
    if not a.send:
        log.info("Режим показа: ничего не отправляется. Для отправки добавьте --send")
    asyncio.run(run(kinds, a.limit, a.send))
    return 0


if __name__ == "__main__":
    sys.exit(main())
