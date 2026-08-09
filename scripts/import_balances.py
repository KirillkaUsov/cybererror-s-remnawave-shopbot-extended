"""Переносит балансы пользователей из базы старого бота.

Кто уже есть в новом боте — получает деньги сразу. Кого ещё нет — баланс
дожидается его в таблице balance_imports и зачисляется при первом /start.

    python3 scripts/import_balances.py --old /root/old_bot_users.db --dry-run
    python3 scripts/import_balances.py --old /root/old_bot_users.db --apply
    python3 scripts/import_balances.py --old ... --apply --skip 123,456

Деньги прибавляются к тому, что уже есть в новом боте, а не заменяют его:
человек мог пополниться и здесь. Повторный запуск ничего не удвоит — уже
выданные записи помечены applied_at и второй раз не начисляются.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NEW_DB = REPO / "users.db"


def connect(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro" if readonly else str(path)
    con = sqlite3.connect(uri, uri=readonly, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", required=True, help="файл users.db старого бота")
    ap.add_argument("--new", default=str(NEW_DB), help="файл базы нового бота")
    ap.add_argument("--skip", default="", help="id через запятую — не переносить")
    ap.add_argument("--min", type=float, default=0.01, help="меньшие суммы не переносим")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="только показать, что произойдёт")
    group.add_argument("--apply", action="store_true", help="записать в базу")
    args = ap.parse_args()

    if not Path(args.old).exists():
        print(f"Нет файла старой базы: {args.old}", file=sys.stderr)
        return 2

    skip = {int(x) for x in args.skip.replace(" ", "").split(",") if x}
    old = connect(args.old, readonly=True)
    new = connect(args.new)

    balances: dict[int, float] = {}
    for row in old.execute("SELECT telegram_id, balance FROM users WHERE balance > 0"):
        try:
            uid, amount = int(row["telegram_id"]), round(float(row["balance"]), 2)
        except (TypeError, ValueError):
            continue
        if amount >= args.min and uid not in skip:
            balances[uid] = amount

    new_users = {r["telegram_id"] for r in new.execute("SELECT telegram_id FROM users")}
    # Уже выданное второй раз не выдаём.
    done = {
        r["telegram_id"]
        for r in new.execute("SELECT telegram_id FROM balance_imports WHERE applied_at IS NOT NULL")
    }
    balances = {u: v for u, v in balances.items() if u not in done}

    now = {u: v for u, v in balances.items() if u in new_users}
    later = {u: v for u, v in balances.items() if u not in new_users}

    print(f"К переносу: {len(balances)} человек на {sum(balances.values()):,.2f} ₽")
    print(f"  зачислим сразу (уже в боте): {len(now)} на {sum(now.values()):,.2f} ₽")
    print(f"  будут ждать прихода:         {len(later)} на {sum(later.values()):,.2f} ₽")
    if skip:
        skipped = {
            int(r["telegram_id"]): float(r["balance"])
            for r in old.execute("SELECT telegram_id, balance FROM users WHERE balance > 0")
            if int(r["telegram_id"]) in skip
        }
        print(f"  пропущено по --skip:         {len(skipped)} на {sum(skipped.values()):,.2f} ₽")
    if done:
        print(f"  уже переносили раньше:       {len(done)}")

    big = sorted(balances.items(), key=lambda kv: -kv[1])[:5]
    if big:
        print("\nСамые крупные из переносимых:")
        for uid, amount in big:
            where = "в боте" if uid in new_users else "ждёт"
            print(f"  {uid:>12}  {amount:>12,.2f} ₽   ({where})")

    if args.dry_run:
        print("\nЭто был просмотр. Записать: --apply")
        return 0

    cur = new.cursor()
    for uid, amount in balances.items():
        cur.execute(
            "INSERT INTO balance_imports (telegram_id, amount, source) VALUES (?, ?, 'old_bot') "
            "ON CONFLICT(telegram_id) DO UPDATE SET amount = excluded.amount "
            "WHERE balance_imports.applied_at IS NULL",
            (uid, amount))

    credited = 0.0
    for uid, amount in now.items():
        cur.execute(
            "UPDATE users SET balance = COALESCE(balance, 0) + ? WHERE telegram_id = ?",
            (amount, uid))
        if cur.rowcount:
            cur.execute(
                "UPDATE balance_imports SET applied_at = CURRENT_TIMESTAMP "
                "WHERE telegram_id = ? AND applied_at IS NULL", (uid,))
            credited += amount

    new.commit()
    print(f"\nГотово. Зачислено сразу: {credited:,.2f} ₽ ({len(now)} человек). "
          f"Ждут прихода: {len(later)} на {sum(later.values()):,.2f} ₽.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
