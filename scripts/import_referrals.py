"""Переносит реферальные связи из базы старого бота.

Старый бот знал, кто кого привёл. Новый узнаёт об этом только когда человек
нажмёт /start — а большинство приглашённых ещё не дошли. Поэтому связи
кладутся заранее, в таблицу referral_imports, и применяются в момент прихода.

    python3 scripts/import_referrals.py --old /путь/к/users-старый.db --dry-run
    python3 scripts/import_referrals.py --old /путь/к/users-старый.db --apply

Скрипт можно запускать повторно: связи обновляются по telegram_id, уже
проставленные referred_by не трогаются.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NEW_DB = REPO / "users.db"

# Настройки реферальной программы переносим целиком: заказчик просил
# «как в прошлом боте».
REFERRAL_SETTINGS = (
    "enable_referrals",
    "referral_reward_type",
    "referral_percentage",
    "fixed_referral_bonus_amount",
    "referral_on_start_referrer_amount",
    "referral_discount",
    "enable_fixed_referral_bonus",
    "wheel_tickets_per_referral",
)


def connect(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro" if readonly else str(path)
    con = sqlite3.connect(uri, uri=readonly, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def old_pairs(old: sqlite3.Connection) -> dict[int, int]:
    """Кто кого привёл, по данным старого бота. Мусор отсеиваем здесь."""
    pairs: dict[int, int] = {}
    known = {r["telegram_id"] for r in old.execute("SELECT telegram_id FROM users")}
    for row in old.execute(
        "SELECT telegram_id, referred_by FROM users "
        "WHERE referred_by IS NOT NULL AND referred_by != 0"
    ):
        uid, ref = row["telegram_id"], row["referred_by"]
        try:
            uid, ref = int(uid), int(ref)
        except (TypeError, ValueError):
            continue
        if uid == ref:
            continue                      # сам себя пригласить не мог
        if ref not in known:
            continue                      # пригласившего нет даже в старой базе
        pairs[uid] = ref
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", required=True, help="файл users.db старого бота")
    ap.add_argument("--new", default=str(NEW_DB), help="файл базы нового бота")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="только показать, что произойдёт")
    group.add_argument("--apply", action="store_true", help="записать в базу")
    args = ap.parse_args()

    if not Path(args.old).exists():
        print(f"Нет файла старой базы: {args.old}", file=sys.stderr)
        return 2

    old = connect(args.old, readonly=True)
    new = connect(args.new)

    pairs = old_pairs(old)
    print(f"Связей в старой базе: {len(pairs)}")

    new_users = {r["telegram_id"] for r in new.execute("SELECT telegram_id FROM users")}
    # Уже проставленные связи не трогаем: победил тот, кто успел первым.
    taken = {
        r["telegram_id"]
        for r in new.execute(
            "SELECT telegram_id FROM users WHERE referred_by IS NOT NULL AND referred_by != 0")
    }

    backfill = {u: r for u, r in pairs.items() if u in new_users and u not in taken}
    waiting = {u: r for u, r in pairs.items() if u not in new_users}
    conflicts = {u: r for u, r in pairs.items() if u in taken}

    print(f"  проставим сразу (уже в новом боте, связи нет): {len(backfill)}")
    print(f"  будут ждать прихода человека: {len(waiting)}")
    print(f"  пропустим (связь уже есть): {len(conflicts)}")

    earned = {
        r["telegram_id"]: float(r["referral_balance_all"] or 0)
        for r in old.execute(
            "SELECT telegram_id, referral_balance_all FROM users WHERE referral_balance_all > 0")
    }
    earned_here = {u: v for u, v in earned.items() if u in new_users}
    print(f"\nСчётчик «заработано»: {len(earned)} человек в старой базе, "
          f"из них дошли до нового бота {len(earned_here)} "
          f"на сумму {sum(earned_here.values()):.2f} ₽")

    settings = {}
    for key in REFERRAL_SETTINGS:
        row = old.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)).fetchone()
        if row is not None:
            settings[key] = row["value"]
    print("\nНастройки рефералки из старого бота:")
    for k, v in settings.items():
        cur = new.execute("SELECT value FROM bot_settings WHERE key = ?", (k,)).fetchone()
        mark = "" if cur and cur["value"] == v else "   <- изменится"
        print(f"  {k} = {v}{mark}")

    if args.dry_run:
        print("\nЭто был просмотр. Записать: --apply")
        return 0

    cur = new.cursor()
    for uid, ref in pairs.items():
        cur.execute(
            "INSERT INTO referral_imports (telegram_id, referrer_id, source) VALUES (?, ?, 'old_bot') "
            "ON CONFLICT(telegram_id) DO UPDATE SET referrer_id = excluded.referrer_id",
            (uid, ref))

    for uid, ref in backfill.items():
        cur.execute(
            "UPDATE users SET referred_by = ? WHERE telegram_id = ? "
            "AND (referred_by IS NULL OR referred_by = 0)",
            (ref, uid))
        cur.execute(
            "UPDATE referral_imports SET applied_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (uid,))

    # Только счётчик «заработано всего»: деньги в старом боте уже выплачивались
    # на основной баланс, второй раз их отдавать нельзя.
    for uid, amount in earned_here.items():
        cur.execute(
            "UPDATE users SET referral_balance_all = ? WHERE telegram_id = ? "
            "AND COALESCE(referral_balance_all, 0) < ?",
            (amount, uid, amount))

    for key, value in settings.items():
        cur.execute(
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))

    new.commit()
    print(f"\nГотово. Связей записано: {len(pairs)}, проставлено сразу: {len(backfill)}, "
          f"ждут прихода: {len(waiting)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
