"""Рендерит страницы админки и проверяет разметку.

Запускать внутри контейнера:
    docker exec remnawave-shopbot python3 /app/project/scripts/check_panel_markup.py

Смотрит на то, что ломает вёрстку молча: незакрытые и лишние теги, повторяющиеся
id, содержимое за пределами {% block %}. Ошибки печатает и выходит с кодом 1.
"""

import re
import sys
from html.parser import HTMLParser

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
# Теги, которые браузер закрывает сам, — не считаем их незакрытыми.
OPTIONAL_END = {"li", "tr", "td", "th", "tbody", "thead", "tfoot", "option", "p"}


class Structure(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.ids = {}

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value:
                if value in self.ids:
                    self.errors.append(
                        f"дубль id={value!r}: строки {self.ids[value]} и {self.getpos()[0]}"
                    )
                else:
                    self.ids[value] = self.getpos()[0]
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for depth in range(len(self.stack) - 1, -1, -1):
            if self.stack[depth][0] == tag:
                # всё, что осталось выше, закрылось неявно
                for unclosed, line in self.stack[depth + 1:]:
                    if unclosed not in OPTIONAL_END:
                        self.errors.append(
                            f"<{unclosed}> со строки {line} не закрыт — "
                            f"его закрывает </{tag}> на строке {self.getpos()[0]}"
                        )
                del self.stack[depth:]
                return
        self.errors.append(f"лишний </{tag}> на строке {self.getpos()[0]}")

    def finish(self):
        for tag, line in self.stack:
            if tag not in OPTIONAL_END:
                self.errors.append(f"<{tag}> со строки {line} так и не закрыт")
        return self.errors


def check_template_source(path: str, text: str) -> list[str]:
    """Дефекты, видимые прямо в исходнике шаблона-наследника."""
    problems = []
    if "{% extends" not in text:
        return problems
    tail = text.rsplit("{% endblock %}", 1)
    # Шаблон может выбирать между partial и полной страницей через
    # {% if %}{% extends %}{% else %}, и тогда {% endif %} в хвосте законен.
    if len(tail) == 2 and tail[1].strip() and tail[1].strip() != "{% endif %}":
        problems.append(
            f"{len(tail[1].strip())} символов после последнего {{% endblock %}} — "
            "Jinja их выбрасывает"
        )
    return problems


def main() -> int:
    sys.path.insert(0, "/app/project/src")
    from shop_bot.webhook_server.app import create_webhook_app
    from shop_bot.bot_controller import BotController

    app = create_webhook_app(BotController())
    app.config["WTF_CSRF_ENABLED"] = False

    pages = [
        "/", "/users", "/admin/keys", "/support", "/support/media",
        "/button-constructor", "/settings", "/monitor", "/node", "/other",
    ]

    failures = 0
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["logged_in"] = True
        for page in pages:
            response = client.get(page, follow_redirects=True)
            if response.status_code != 200:
                print(f"[FAIL] {page}: HTTP {response.status_code}")
                failures += 1
                continue
            html = response.get_data(as_text=True)
            parser = Structure()
            parser.feed(html)
            errors = parser.finish()
            if errors:
                failures += 1
                print(f"[FAIL] {page}: {len(errors)} проблем")
                for error in errors[:15]:
                    print(f"        {error}")
            else:
                print(f"[ ok ] {page}: {len(html)} байт, вложенность в порядке")

    import pathlib
    templates = pathlib.Path("/app/project/src/shop_bot/webhook_server/templates")
    for template in sorted(templates.glob("*.html")):
        problems = check_template_source(str(template), template.read_text(encoding="utf-8"))
        for problem in problems:
            failures += 1
            print(f"[FAIL] {template.name}: {problem}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
