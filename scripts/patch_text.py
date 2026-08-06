"""Точечная замена в файле с сохранением его окончаний строк.

Замены описываются парами (было, стало) с обычным \n — скрипт сам приводит их
к терминаторам файла. Нужен потому, что часть файлов проекта в CRLF, и
дословный поиск многострочного фрагмента в них не находится.
"""

from pathlib import Path


def apply(path: str | Path, replacements: list[tuple[str, str]], *, count: int = 1) -> None:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    crlf = raw.count(b"\r\n") * 2 > raw.count(b"\n")

    def fit(fragment: str) -> str:
        return fragment.replace("\n", "\r\n") if crlf else fragment

    for old, new in replacements:
        old, new = fit(old), fit(new)
        found = text.count(old)
        if found != count:
            raise AssertionError(f"{path}: найдено {found} вхождений, ожидалось {count}: {old[:60]!r}")
        text = text.replace(old, new, count)

    path.write_bytes(text.encode("utf-8"))
