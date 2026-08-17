"""Разметка телеграм-сообщений, пригодная для показа в браузере.

Рассылку пишут в том же HTML, который понимает Telegram, и в базу она попадает
как есть. В кабинете этот текст раньше просто экранировали — человек видел
`<b>работает</b>` вместо жирного слова. Разобрать разметку в браузере нельзя:
вставить чужой текст в innerHTML без разбора — это XSS. Поэтому чистим здесь,
на сервере, и наружу отдаём уже безопасный кусок HTML.
"""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser

# Ровно то, что размечает сам Telegram, плюс перенос строки.
# https://core.telegram.org/bots/api#html-style
_ALLOWED = {
    "b": "b", "strong": "b",
    "i": "i", "em": "i",
    "u": "u", "ins": "u",
    "s": "s", "strike": "s", "del": "s",
    "code": "code",
    "pre": "pre",
    "blockquote": "blockquote",
    "br": "br",
    "a": "a",
    "span": "span",
    "tg-spoiler": "span",
}

_VOID = {"br"}

_MUTED = {"script", "style"}

# Голые схемы, а не «всё, что не javascript:»: список разрешённого короче
# списка того, чем можно навредить.
_SAFE_SCHEMES = ("http://", "https://", "tg://", "mailto:")


class _Cleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._open: list[str] = []
        self._muted = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _MUTED:
            # Содержимое <script> экранированным вывести можно, но показывать
            # человеку чужой код незачем — выкидываем вместе с тегом.
            self._muted += 1
            return
        safe = _ALLOWED.get(tag)
        if not safe:
            return
        if tag in _VOID:
            self.out.append("<br>")
            return
        if safe == "a":
            href = ""
            for name, value in attrs:
                if name.lower() == "href":
                    href = (value or "").strip()
            if not href.lower().startswith(_SAFE_SCHEMES):
                # Ссылка никуда не ведёт — текст показываем, обёртку выкидываем.
                return
            self.out.append(
                f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">')
            self._open.append("a")
            return
        if safe == "span":
            # <span> из Telegram бывает только спойлером; остальные — чужие.
            classes = ""
            for name, value in attrs:
                if name.lower() == "class":
                    classes = (value or "").lower()
            if tag != "tg-spoiler" and "tg-spoiler" not in classes:
                return
            self.out.append('<span class="tg-spoiler">')
            self._open.append("span")
            return
        self.out.append(f"<{safe}>")
        self._open.append(safe)

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.lower() in _VOID:
            self.out.append("<br>")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _MUTED:
            self._muted = max(0, self._muted - 1)
            return
        safe = _ALLOWED.get(tag.lower())
        if not safe or safe == "br":
            return
        # Закрываем только то, что сами открыли, и в своём порядке: иначе
        # незакрытый чужой тег утащил бы за собой вёрстку страницы.
        if safe in self._open:
            while self._open:
                current = self._open.pop()
                self.out.append(f"</{current}>")
                if current == safe:
                    break

    def handle_data(self, data: str) -> None:
        if self._muted:
            return
        self.out.append(escape(data, quote=False))

    def result(self) -> str:
        while self._open:
            self.out.append(f"</{self._open.pop()}>")
        return "".join(self.out)


def sanitize(text: str | None) -> str:
    """Телеграм-разметка → безопасный HTML для вставки в innerHTML."""
    if not text:
        return ""
    cleaner = _Cleaner()
    cleaner.feed(text.replace("\r\n", "\n").replace("\r", "\n"))
    cleaner.close()
    return cleaner.result()


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._muted = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _MUTED:
            self._muted += 1
        elif tag == "br":
            self.out.append("\n")

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _MUTED:
            self._muted = max(0, self._muted - 1)

    def handle_data(self, data: str) -> None:
        if not self._muted:
            self.out.append(data)


def to_text(text: str | None) -> str:
    """Та же разметка без тегов — для мест, где HTML показать негде."""
    if not text:
        return ""
    stripper = _Stripper()
    stripper.feed(text.replace("\r\n", "\n").replace("\r", "\n"))
    stripper.close()
    return "".join(stripper.out)
