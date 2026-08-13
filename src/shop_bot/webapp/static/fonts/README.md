# Шрифты

Раздаются с этого же домена, а не с `fonts.googleapis.com`. Внешний
`<link rel="stylesheet">` блокирует рендер: если до Google с устройства не
дозвониться, страница висит белой сколько угодно долго — именно так у части
пользователей «бесконечно грузился» кабинет.

- **Onest** — основной текст и заголовки.
- **Geist Mono** — цифры, коды и технические метки. Табличные знаки держат
  суммы и остаток дней на месте при пересчёте.

Оба под лицензией SIL Open Font License 1.1 (`OFL.txt`), самостоятельная
раздача и изменение разрешены.

Оставлены только subset'ы `cyrillic`, `cyrillic-ext`, `latin`, `latin-ext`;
греческий, вьетнамский и символьные выброшены. Файлы **переменные**: один на
subset вместо одного на начертание, поэтому вес берётся любой от 100 до 900,
а не только заявленные в `@font-face`. Восемь файлов весят меньше, чем
двадцать фиксированных начертаний до этого.

Кириллица обязательна: у Geist Sans, который часто советуют в паре к Geist
Mono, её нет вовсе — при подборе это проверяется первым делом.

Обновить файлы:

    https://cdn.jsdelivr.net/fontsource/fonts/onest:vf@latest/<subset>-wght-normal.woff2
    https://cdn.jsdelivr.net/fontsource/fonts/geist-mono:vf@latest/<subset>-wght-normal.woff2

где `<subset>` — `cyrillic`, `cyrillic-ext`, `latin`, `latin-ext`.

Те же файлы лежат у лендинга в `/var/www/html/assets/fonts/` (там пути в
`fonts.css` начинаются с `/assets/`, а не с `/static/`). Раскладывает их
`backups/site/assets.py`.
