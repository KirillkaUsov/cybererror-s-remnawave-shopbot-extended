# 🛍️ Remnawave ShopBot Extended

> Форк [CyberERROR/remnawave-shopbot](https://github.com/CyberERROR/remnawave-shopbot) — Telegram Mini App для клиентов, вложения в поддержке, единая тёмная тема.

<div align="center">

[![License](https://img.shields.io/github/license/KirillkaUsov/cybererror-s-remnawave-shopbot-extended?label=license&style=flat-square)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/KirillkaUsov/cybererror-s-remnawave-shopbot-extended?label=last%20commit&style=flat-square)](https://github.com/KirillkaUsov/cybererror-s-remnawave-shopbot-extended/commits)
[![Issues](https://img.shields.io/github/issues/KirillkaUsov/cybererror-s-remnawave-shopbot-extended?label=issues&style=flat-square)](https://github.com/KirillkaUsov/cybererror-s-remnawave-shopbot-extended/issues)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue?style=flat-square)](https://www.python.org/downloads/)

</div>

---

## Для кого это

Для тех, кто **уже держит** оригинальный Remnawave ShopBot и хочет большего. Как устроен сам бот, как подключить платёжки, настроить хосты, тарифы и рефералку — всё это описано в [README оригинала](https://github.com/CyberERROR/remnawave-shopbot#readme) и здесь не дублируется. Ниже только то, чем этот форк от него отличается.

Если вы никогда не запускали оригинальный бот — начните с него, а сюда возвращайтесь, когда захотите мини-апп и остальное.

---

## Что добавлено

### 🪟 Telegram Mini App для клиентов

Полноценный кабинет вместо переписки с ботом: подписки с оставшимся сроком и списком устройств, покупка и продление, пополнение баланса, промокоды, инструкции по подключению, обращения в поддержку с перепиской. Работает и как мини-апп внутри Telegram, и как обычный сайт в браузере.

Вход: `initData` внутри Telegram, а в браузере — Telegram, Email или ссылка подписки. Токен кабинета живёт в `localStorage` и куке.

| Подписки | Тарифы | Кабинет |
|:---:|:---:|:---:|
| ![Подписки](docs/screenshots/app-home.png) | ![Тарифы](docs/screenshots/app-tariffs.png) | ![Кабинет](docs/screenshots/app-profile.png) |
| ![Инструкция](docs/screenshots/app-guide.png) | ![Поддержка](docs/screenshots/app-support.png) | |
| Инструкция | Поддержка | |

### 📱 Устройства докупаются отдельно от продления

Раньше поднять лимит одновременных подключений можно было только вместе с продлением — то есть заплатив за срок, который ещё не кончился. Теперь на локациях с наборами устройств (`device_mode = tiers`) в боте и мини-аппе есть отдельная покупка: срок не меняется, доплата считается по остатку — разница в месячной цене набора, умноженная на оставшиеся дни.

Цену считает только сервер: клиент присылает лишь желаемое количество устройств, а набор и сумма пересчитываются заново перед созданием счёта. Истёкшим, бессрочным и уже максимальным подпискам докупка не предлагается — вместо кнопки они получают объяснение.

### 🔗 Привязка Telegram к веб-аккаунту

Аккаунт, созданный по Email, привязывается к Telegram-профилю через `initData` — дальше это один и тот же пользователь с одним балансом и одними подписками.

### 📎 Вложения в поддержке

Фото, видео, голосовые и документы из обращений сохраняются локально рядом с тикетом, а не живут одним `file_id` в Telegram. В панели — отдельный раздел с превью, размерами, поиском осиротевших файлов и чисткой по возрасту.

### 🎨 Одна тёмная тема на всё

Панель, мини-апп и лендинг в одной палитре с сиреневым акцентом. Зелёного не осталось нигде: переопределены даже Tailwind-шкалы `green/emerald/teal/lime`, чтобы случайно забытый класс не дал неоновой зелени.

![Дашборд](docs/screenshots/dashboard.png)

<details>
<summary><b>Ещё разделы панели</b></summary>

<br>

| | |
|:---:|:---:|
| ![Пользователи](docs/screenshots/users.png) | ![Ключи](docs/screenshots/keys.png) |
| Пользователи | Ключи |
| ![Мониторинг](docs/screenshots/monitor.png) | ![Ноды](docs/screenshots/nodes.png) |
| Мониторинг | Ноды |
| ![Настройки](docs/screenshots/settings.png) | ![Вложения](docs/screenshots/attachments.png) |
| Настройки | Вложения поддержки |
| ![Конструктор кнопок](docs/screenshots/buttons.png) | ![Рассылка](docs/screenshots/broadcast.png) |
| Конструктор кнопок | Рассылка |
| ![Поддержка](docs/screenshots/support.png) | |
| Обращения | |

<sub>Данные на скриншотах подменены: идентификаторы, имена и ссылки подписок — выдуманные.</sub>

</details>

### 📐 Вёрстка под реальные экраны

Мини-апп и панель проверены от 360 px до десктопа: без горизонтального скролла, без обрезанных заголовков, без разъезжающихся строк. На телефоне панель не ужимается до 85%, области нажатия не меньше 44 px, учтены вырезы экрана.

### 🛡 Мелочи, которые чинили по логам

- Шрифты раздаются со своего домена — внешний блокирующий `<link>` на `fonts.googleapis.com` не давал странице отрендериться там, откуда до Google не дозвониться.
- Вход через Telegram в браузере — универсальная ссылка `https://t.me/…` вместо схемы `tg://`, которую iOS во встроенных браузерах не открывает вовсе.
- Загрузка кабинета не может зависнуть навсегда: у опроса авторизации есть таймаут, у ошибок — текст и кнопка повтора.
- Пароли кабинета хранятся хешем с солью, а не открытым текстом.
- Правовые документы лежат в проекте и раздаются им же — ссылки больше не могут стать битыми.

---

## Установка

Скриптов-установщиков здесь нет: они предполагали чистый сервер и разворачивали Docker, Nginx и Certbot с нуля. Если бот у вас уже работает, всё это уже есть.

**Переехать с оригинала на этот форк** — без потери базы, ключей и настроек:

```bash
cd /root/remnawave-shopbot
git remote set-url origin https://github.com/KirillkaUsov/cybererror-s-remnawave-shopbot-extended.git
git pull
docker compose up -d --build
```

Схема БД доезжает сама при старте — новые таблицы и колонки создаются миграциями.

**С нуля** — если сервер уже с Docker, Nginx и сертификатом:

```bash
git clone https://github.com/KirillkaUsov/cybererror-s-remnawave-shopbot-extended.git /root/remnawave-shopbot
cd /root/remnawave-shopbot
docker compose up -d --build
```

Дальше панель на `:1488`, мини-апп на `:8000` — их принято закрывать своим Nginx с сертификатом. Мини-аппу нужен отдельный домен (или путь) с валидным HTTPS, иначе Telegram его не откроет.

Требования те же, что у оригинала: Ubuntu 20.04+ / Debian 11+, root по SSH, Remnawave на целевых хостах, 1 ГБ RAM.

---

## Обновление

```bash
cd /root/remnawave-shopbot && git pull && docker compose up -d --build
```

Правки шаблонов и HTML подхватываются без пересборки — каталог проекта смонтирован в контейнер. Пересборка нужна только для изменений в Python и зависимостях.

---

## Что взять из оригинала

Обновления автора не прилетают автоматически — он остался вторым remote:

```bash
git remote add upstream https://github.com/CyberERROR/remnawave-shopbot.git
git fetch upstream
git merge upstream/main
```

Конфликты будут в шаблонах панели и в `webapp/app.html` — там переписано больше всего.

---

## Баги

Про то, что появилось в форке — [сюда](https://github.com/KirillkaUsov/cybererror-s-remnawave-shopbot-extended/issues). Про то, что воспроизводится и в оригинале — [в апстрим](https://github.com/CyberERROR/remnawave-shopbot/issues), там это починят для всех.

---

## Лицензия и происхождение

[GPLv3](LICENSE) — та же, что у оригинала.

Основан на [Remnawave ShopBot](https://github.com/CyberERROR/remnawave-shopbot) © [@CyberERROR](https://github.com/CyberERROR). Авторство базового кода принадлежит ему, изменения в форке — [@KirillkaUsov](https://github.com/KirillkaUsov).

Шрифты Golos Text и JetBrains Mono в `src/shop_bot/webapp/static/fonts/` — [SIL Open Font License 1.1](src/shop_bot/webapp/static/fonts/OFL.txt).
