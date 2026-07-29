# Шрифты

Раздаются с этого же домена, а не с `fonts.googleapis.com`. Внешний
`<link rel="stylesheet">` блокирует рендер: если до Google с устройства не
дозвониться, страница висит белой сколько угодно долго — именно так у части
пользователей «бесконечно грузился» кабинет.

Оставлены только subset'ы `cyrillic`, `cyrillic-ext`, `latin`, `latin-ext`;
греческий и вьетнамский выброшены.

- **Golos Text** и **JetBrains Mono** — лицензия SIL Open Font License 1.1
  (`OFL.txt`), самостоятельная раздача и изменение разрешены.

Обновить файлы: взять свежий CSS с
`https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap`
(с браузерным User-Agent, иначе Google отдаст ttf вместо woff2) и перекачать
`.woff2` по ссылкам оттуда.
