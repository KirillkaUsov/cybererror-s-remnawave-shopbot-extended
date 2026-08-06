"""Проверяет, всё ли готово для отправки почты с этого сервера.

Смотрит PTR, прямую запись почтового хоста, SPF, DKIM и DMARC, а заодно
сверяет опубликованный ключ DKIM с тем, которым реально подписывает opendkim.

    python3 scripts/check_mail_dns.py

Ничего не меняет. Выходит с ненулевым кодом, если что-то не сошлось, — можно
повесить на cron и не следить руками.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DOMAIN = "chorusconnect.cc"
MAIL_HOST = f"mail.{DOMAIN}"
SERVER_IP = "194.104.10.220"
DKIM_SELECTOR = "mail"
DKIM_KEY_FILE = Path("/etc/opendkim/keys/chorusconnect.cc/mail.txt")

OK, FAIL, WARN = "  ок  ", " нет  ", " ! "


def dig(record_type: str, name: str) -> list[str]:
    try:
        out = subprocess.run(
            ["dig", "+short", "+time=4", "+tries=2", record_type, name],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    # TXT приезжает в кавычках и может быть разбит на куски по 255 символов.
    return [re.sub(r'"\s+"', "", line).strip('"') for line in out.splitlines() if line.strip()]


def local_dkim() -> str | None:
    if not DKIM_KEY_FILE.exists():
        return None
    chunks = re.findall(r'"([^"]*)"', DKIM_KEY_FILE.read_text())
    return "".join(chunks) if chunks else None


def p_value(txt: str) -> str:
    match = re.search(r"p=([A-Za-z0-9+/=]+)", txt)
    return match.group(1) if match else ""


def main() -> int:
    problems: list[str] = []

    def report(status: str, title: str, detail: str = "", problem: str = "") -> None:
        print(f"[{status}] {title}" + (f" — {detail}" if detail else ""))
        if problem:
            problems.append(problem)

    print(f"Проверка почтовой настройки {DOMAIN}\n")

    # --- PTR и прямая запись: почтовики сверяют их в обе стороны ---
    ptr = [p.rstrip(".") for p in dig("-x", SERVER_IP)]
    if not ptr:
        report(FAIL, "PTR", f"у {SERVER_IP} обратной записи нет", "нет PTR")
    elif MAIL_HOST in ptr:
        report(OK, "PTR", f"{SERVER_IP} -> {MAIL_HOST}")
    else:
        report(FAIL, "PTR", f"{SERVER_IP} -> {', '.join(ptr)}, ждём {MAIL_HOST}",
               "PTR указывает не на почтовый хост")

    forward = dig("A", MAIL_HOST)
    if SERVER_IP in forward:
        report(OK, "A почтового хоста", f"{MAIL_HOST} -> {SERVER_IP}")
    elif forward:
        report(FAIL, "A почтового хоста", f"{MAIL_HOST} -> {', '.join(forward)}",
               "A почтового хоста указывает на чужой адрес")
    else:
        report(FAIL, "A почтового хоста", f"{MAIL_HOST} не резолвится",
               "нет A-записи почтового хоста")

    # --- SPF ---
    spf = [t for t in dig("TXT", DOMAIN) if t.startswith("v=spf1")]
    if len(spf) > 1:
        report(FAIL, "SPF", f"записей {len(spf)}, а должна быть одна",
               "SPF-записей больше одной — почтовики признают домен непроверяемым")
    elif not spf:
        report(FAIL, "SPF", "записи нет", "нет SPF")
    elif f"ip4:{SERVER_IP}" in spf[0]:
        report(OK, "SPF", spf[0])
    else:
        report(FAIL, "SPF", f"{spf[0]} — нашего адреса в ней нет",
               "SPF не разрешает отправку с этого сервера")

    # --- DKIM ---
    published = [t for t in dig("TXT", f"{DKIM_SELECTOR}._domainkey.{DOMAIN}") if "p=" in t]
    mine = local_dkim()
    if not published:
        report(FAIL, "DKIM", f"{DKIM_SELECTOR}._domainkey не опубликован", "нет DKIM")
    elif mine is None:
        report(WARN, "DKIM", "запись есть, но ключа на сервере нет — сверить не с чем")
    elif p_value(published[0]) == p_value(mine):
        report(OK, "DKIM", f"селектор {DKIM_SELECTOR}, ключ совпал с серверным")
    else:
        report(FAIL, "DKIM", "опубликован не тот ключ, которым подписывает сервер",
               "ключ DKIM в DNS не совпадает с серверным")

    # --- DMARC ---
    dmarc = [t for t in dig("TXT", f"_dmarc.{DOMAIN}") if t.startswith("v=DMARC1")]
    if dmarc:
        report(OK, "DMARC", dmarc[0])
    else:
        report(FAIL, "DMARC", "записи нет", "нет DMARC")

    # --- приём почты ---
    mx = dig("MX", DOMAIN)
    if mx:
        report(OK, "MX (приём)", ", ".join(mx))
    else:
        report(WARN, "MX (приём)", "нет — писать на @chorusconnect.cc некуда, "
                                   "отчёты DMARC не дойдут")

    print()
    if problems:
        print("Отправлять рано, мешает:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Всё на месте: можно включать отправку в панели.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
