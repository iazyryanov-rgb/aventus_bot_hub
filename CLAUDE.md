# Aventus Bot Hub — правила работы с кодом

## i18n

Любая новая строка, попадающая на экран (`text="..."`, `title=...`,
заголовки колонок Treeview, статусы, сообщения об ошибках UI), обязана
проходить через `app.i18n.t(<key>)`. Если ключа ещё нет — добавь его
в `app/i18n.py` сразу для **всех** трёх языков: `RU`, `ENG`, `ES`.

Не оставляй RU-only строки в виджетах. Проверка перед коммитом:
`grep -rn 'text="[А-Я]' app/ui/` — список не должен расти.

Доменные строки внутри `app/action_trees.py`, `app/crm_results.py` и
прочих data-моделей **не переводим** — это семантика, а не UI.

## Производительность дашборда

- Параллельные I/O делаем через `ThreadPoolExecutor` в одном пуле
  на воркер.
- Календари Webitel читаем через `app/calendar_cache.py` (TTL 6 ч).
- `MAX_PAGES = 20` — больше не нужно: при включённой защите от дублей
  по `id` повторных страниц не бывает.
- Пагинатор `_paginate` ловит «застрявшие на page=1» Webitel-эндпоинты
  и автоматически останавливается.
- Скрытые фоновые `DashboardPanel`-ы (`background=True`) тикают по
  `BACKGROUND_REFRESH_MIN` (15 мин), а не по выбранному пользователем.
- В `_reload` стоит debounce + skip-on-fresh (<30 с).

## Структура данных

- Один общий доступ к CRM-БД компании — `db.connect_for_company(company)`.
  Не плодить локальные `_open_for`.
- Цвета UI — `app/ui/colors.py`. Не дублировать `META_FG`, `TBD_FG` и т. п.
  по модулям.
- `data/db_catalogs/` — справочник схем CRM-БД, **не** копируется в `dist/`
  при сборке (см. `build.py:SKIP_TOPLEVEL`).

## Сборка

`py -3 build.py` собирает `dist/AventusBotHub.exe` (PyInstaller, --onefile,
--windowed, --collect-all tzdata, hidden-imports `pymysql`/`pg8000`).
Пользовательские данные в `dist/data/<USER_DATA_FILES>` не перетираются.
