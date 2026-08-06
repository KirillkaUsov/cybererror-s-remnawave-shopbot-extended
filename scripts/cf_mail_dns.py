"""Прописывает в Cloudflare записи, нужные для отправки почты с этого сервера.

Ставит A для почтового хоста, SPF, DKIM и DMARC. Повторный запуск ничего не
ломает: существующие записи обновляются, а не дублируются.

Значение DKIM берётся из ключа, который лежит на сервере, — чтобы в DNS не
уехал ключ от другой пары.

    export CF_API_TOKEN=...
    python3 scripts/cf_mail_dns.py --check     # показать, что изменится
    python3 scripts/cf_mail_dns.py --apply

Токену нужны права Zone:DNS:Edit на зоне. Токена только на чтение не хватит:
скрипт честно скажет об этом на первой же записи.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"

ZONE_NAME = "chorusconnect.cc"
MAIL_HOST = "mail"                      # -> mail.chorusconnect.cc, он же PTR и HELO
SERVER_IP = "194.104.10.220"
DKIM_SELECTOR = "mail"
DKIM_KEY_FILE = Path("/etc/opendkim/keys/chorusconnect.cc/mail.txt")

# ~all, а не -all: пока не убедились, что вся исходящая почта идёт через этот
# сервер, жёсткий отказ рискует зарубить письма, о которых мы забыли.
SPF_BASE = f"v=spf1 ip4:{SERVER_IP} ~all"
SPF_WITH_ROUTING = f"v=spf1 ip4:{SERVER_IP} include:_spf.mx.cloudflare.net ~all"

# p=none — режим наблюдения. Ужесточать до quarantine только после того, как
# отчёты покажут, что чужой почты от нашего имени нет.
DMARC = "v=DMARC1; p=none; rua=mailto:dmarc@chorusconnect.cc; fo=1; adkim=r; aspf=r"


class CFError(RuntimeError):
    pass


def _call(token: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read() or b"{}")
    except urllib.error.URLError as exc:
        raise CFError(f"Cloudflare недоступен: {exc.reason}") from exc
    if not body.get("success"):
        errors = "; ".join(e.get("message", "") for e in body.get("errors", []))
        raise CFError(errors or "Cloudflare отказал без объяснений")
    return body


def dkim_value() -> str:
    """Собирает TXT из файла opendkim-genkey: он разбит на куски в кавычках."""
    if not DKIM_KEY_FILE.exists():
        raise CFError(f"Нет файла с публичным ключом: {DKIM_KEY_FILE}")
    chunks = re.findall(r'"([^"]*)"', DKIM_KEY_FILE.read_text())
    if not chunks:
        raise CFError(f"В {DKIM_KEY_FILE} не нашлось значения в кавычках")
    return "".join(chunks)


def zone_id(token: str) -> str:
    result = _call(token, "GET", f"/zones?name={ZONE_NAME}")["result"]
    if not result:
        raise CFError(f"Зона {ZONE_NAME} не найдена — токен выдан не на тот аккаунт?")
    return result[0]["id"]


def existing(token: str, zone: str) -> list[dict]:
    try:
        return _call(token, "GET", f"/zones/{zone}/dns_records?per_page=200")["result"]
    except CFError as exc:
        # Список зон отдаётся и по урезанному токену, а записи — уже нет.
        raise CFError(
            f"{exc}. Похоже, у токена нет прав на DNS: нужен Zone -> DNS -> Edit "
            f"на зоне {ZONE_NAME}"
        ) from exc


def routing_enabled(records: list[dict]) -> bool:
    """Включён ли приём почты через Cloudflare — по MX на их хосты."""
    return any(r["type"] == "MX" and "mx.cloudflare.net" in r["content"] for r in records)


def desired(records: list[dict]) -> list[dict]:
    spf = SPF_WITH_ROUTING if routing_enabled(records) else SPF_BASE
    return [
        {"type": "A", "name": MAIL_HOST, "content": SERVER_IP, "proxied": False,
         "comment": "Почтовый хост: должен совпадать с PTR, проксировать нельзя"},
        {"type": "TXT", "name": "@", "content": spf, "comment": "SPF"},
        {"type": "TXT", "name": f"{DKIM_SELECTOR}._domainkey", "content": dkim_value(),
         "comment": "DKIM, ключ лежит на сервере в /etc/opendkim"},
        {"type": "TXT", "name": "_dmarc", "content": DMARC, "comment": "DMARC"},
    ]


def full_name(name: str) -> str:
    return ZONE_NAME if name == "@" else f"{name}.{ZONE_NAME}"


def txt_kind(content: str) -> str:
    """Чем различать TXT на одном имени.

    SPF, DKIM и DMARC начинаются с `v=`, а рядом на апексе обычно висят
    подтверждения владения доменом — их трогать нельзя.
    """
    match = re.match(r"v=[A-Za-z0-9]+", content.strip().lstrip('"'))
    return match.group(0).lower() if match else content[:16].lower()


def match(records: list[dict], want: dict) -> dict | None:
    """Ищет запись, которую надо обновить, а не создавать заново."""
    fqdn = full_name(want["name"])
    same = [r for r in records if r["type"] == want["type"] and r["name"] == fqdn]
    if want["type"] != "TXT":
        return same[0] if same else None

    kind = txt_kind(want["content"])
    same = [r for r in same if txt_kind(r["content"]) == kind]
    if len(same) > 1:
        # Две записи `v=spf1` — то же самое, что ни одной: домен становится
        # непроверяемым. Молча обновить одну из них значит оставить поломку.
        raise CFError(
            f"На {fqdn} уже {len(same)} записей вида {kind} — лишние надо удалить "
            f"вручную, иначе почтовики перестанут доверять домену"
        )
    return same[0] if same else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="только показать разницу")
    group.add_argument("--apply", action="store_true", help="записать в Cloudflare")
    args = parser.parse_args()

    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not token:
        print("Нет CF_API_TOKEN в окружении", file=sys.stderr)
        return 2

    try:
        zone = zone_id(token)
        records = existing(token, zone)
    except CFError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if not routing_enabled(records):
        print("MX на Cloudflare нет: приём почты не включён, SPF пишем без их include.\n")

    changes = 0
    for want in desired(records):
        try:
            current = match(records, want)
        except CFError as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 1
        label = f"{want['type']:5} {full_name(want['name'])}"
        if current and current["content"].strip('"') == want["content"]:
            print(f"  без изменений  {label}")
            continue

        changes += 1
        action = "обновить" if current else "создать"
        print(f"  {action:9}      {label}")
        print(f"                 -> {want['content'][:100]}")
        if current:
            print(f"                 было: {current['content'][:100]}")
        if args.check:
            continue

        payload = {k: want[k] for k in ("type", "name", "content", "comment") if k in want}
        payload["ttl"] = 300
        if want["type"] == "A":
            payload["proxied"] = want["proxied"]
        try:
            if current:
                _call(token, "PATCH", f"/zones/{zone}/dns_records/{current['id']}", payload)
            else:
                _call(token, "POST", f"/zones/{zone}/dns_records", payload)
        except CFError as exc:
            print(f"    не вышло: {exc}", file=sys.stderr)
            return 1
        print("    записано")

    if not changes:
        print("\nВсё уже на месте.")
    elif args.check:
        print(f"\nК изменению: {changes}. Запустить с --apply.")
    else:
        print(f"\nГотово, изменено записей: {changes}.")
        print("Проверить через пару минут: python3 scripts/check_mail_dns.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
