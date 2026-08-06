"""Возвращает файлам их исходные окончания строк.

Инструменты правки нередко переписывают весь файл с \n, и тогда diff разбухает
до полного переписывания. Скрипт сверяет рабочую копию с HEAD построчно:
неизменившимся строкам возвращает прежний терминатор, новым — тот, что
преобладает в файле.

    python3 scripts/restore_line_endings.py <файл> [<файл> ...]
"""

import difflib
import subprocess
import sys
from pathlib import Path


def lines_with_endings(data: bytes) -> list[tuple[bytes, bytes]]:
    """Разбирает файл на пары (текст строки, её терминатор)."""
    result = []
    start = 0
    while start < len(data):
        index = data.find(b"\n", start)
        if index == -1:
            result.append((data[start:], b""))
            break
        line = data[start:index]
        if line.endswith(b"\r"):
            result.append((line[:-1], b"\r\n"))
        else:
            result.append((line, b"\n"))
        start = index + 1
    return result


def restore(path: Path) -> bool:
    head = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        capture_output=True,
    )
    if head.returncode != 0:
        return False

    old = lines_with_endings(head.stdout)
    new = lines_with_endings(path.read_bytes())

    crlf = sum(1 for _, ending in old if ending == b"\r\n")
    dominant = b"\r\n" if crlf * 2 > len(old) else b"\n"
    if not any(ending == b"\r\n" for _, ending in old):
        return False

    matcher = difflib.SequenceMatcher(
        a=[text for text, _ in old], b=[text for text, _ in new], autojunk=False
    )
    rebuilt = bytearray()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(j2 - j1):
                text, _ = new[j1 + offset]
                rebuilt += text + old[i1 + offset][1]
        else:
            for index in range(j1, j2):
                text, ending = new[index]
                rebuilt += text + (dominant if ending else b"")

    current = path.read_bytes()
    if bytes(rebuilt) == current:
        return False
    path.write_bytes(rebuilt)
    return True


def main() -> int:
    changed = 0
    for name in sys.argv[1:]:
        path = Path(name)
        if restore(path):
            print(f"восстановлено: {path}")
            changed += 1
        else:
            print(f"без изменений: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
