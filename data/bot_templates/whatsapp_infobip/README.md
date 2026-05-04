# Шаблон: WhatsApp Infobip prod (база — Credito365)

Файл [credito365_prod.json](credito365_prod.json) — экспорт текущей продовой routing schema из Webitel
(`whatsapp-infobip-credito365-prod`, id=110, type=`chat`). Зафиксирован 2026-05-04 как опорная точка
для адаптации под другие тенанты (AR/PE/CO2). Схему пока не редактируем —
только наблюдаем структуру.

## 1. Структура файла верхнего уровня

```
{
  "id":         "110",                                 # routing schema id (per-tenant)
  "name":       "whatsapp-infobip-credito365-prod",    # шаблон: whatsapp-infobip-{slug}-prod
  "type":       "chat",                                # фиксированно для WhatsApp
  "tags":       [],
  "editor":     true,                                  # выгружено из визуального редактора
  "createdAt":  "1774594913792",  "createdBy": {id, name},
  "updatedAt":  "1777394343142",  "updatedBy": {id, name},
  "payload":    { ... визуальный редактор ... },
  "schema":     "<JSON-encoded string>"                # исполняемое представление
}
```

* `payload` и `schema` дублируют логику в двух представлениях:
  * **`payload`** — для визуального редактора Webitel: `nodes`, `connections`, `pages`, `positions`.
    При импорте Webitel компилирует его в `schema`. Менять имеет смысл именно `payload` (а не `schema`),
    иначе при следующем сохранении из UI правки в `schema` затрутся.
  * **`schema`** — JSON-строка с массивом операций (то, что фактически исполняется рантаймом).

## 2. Визуальный редактор (`payload`)

* **`nodes`** — 153 узла (это все блоки на холсте, включая декоративные).
* **`connections`** — 195 рёбер между ними.
* **`positions`** — 192 пары `{nodeId: {x, y}}` для отрисовки.
* **`pages`** — **8 страниц** (логические разделы). Имена:
  1. `main` — точка входа (id=`main`).
  2. `SMART VERSION` — LLM-ветка (OpenAI Conversations + Responses).
  3. `Alert` — отправка алертов в Telegram при сбоях.
  4. `validation data` — проверка ответов CRM.
  5. `routing` — маршрутизация на нужную очередь.
  6. `result preparation` — сборка итогов диалога.
  7. `agent flow` — передача оператору (`joinQueue`).
  8. `result mapping` — маппинг CRM-полей в переменные.

  Между страницами в `schema` ходят через `execute { name: <pageId> }` (см. ниже).
  Узел в `payload` имеет `label` (тип операции, например `httpRequest`/`set`/`if`),
  `inputs`/`outputs` (точки соединений), `pageId`, `commons` (`break`, `limit`),
  `controls` (UI-параметры), `description`.
  Поля `type` у узлов нет — для группировки используется `label`.

  Распределение по `label` (топ-10):
  `set`(45), `if`(17), `switch`(14), `sendText`(14), `customModule`(13), `js`(13),
  `httpRequest`(12), `start`(8), `recvMessage`(4), `joinQueue`(4).

## 3. Скомпилированная программа (`schema`)

Это JSON-строка длиной ~161 КБ, после `json.loads(...)` превращается в массив из 9 верхнеуровневых
функций (по одной на page + main). Каждая функция — список операций. Операция — словарь вида
`{ "<op>": <args>, "tag": "<уникальный id>" }`.

Частоты (по всему дереву):

| Операция        | Кол-во | Назначение |
|-----------------|-------:|------------|
| `set`           | 51 | Присвоение переменной (`{"set": {"var": value}}`) |
| `goto`          | 50 | Переход по тегу другой операции |
| `execute`       | 19 | Вызов другой страницы по её id (`{"name": "<pageId>"}`) |
| `if`            | 17 | Условный переход |
| `switch`        | 16 | Множественный выбор по `variable`+`case` |
| `js`            | 16 | Inline-JavaScript для вычислений |
| `sendText`      | 16 | Отправка текстового сообщения пользователю |
| `httpRequest`   | 14 | Внешний HTTP (CRM, Telegram, OpenAI) |
| `joinQueue`     |  4 | Перевод диалога на очередь оператора |
| `export`        |  3 | Экспорт переменных в карточку чата (видны оператору) |
| `recvMessage`   |  4 (в `payload`) | Ожидание сообщения от пользователя |
| `unSet`         |  2 | Удаление переменной |

### `httpRequest` — внешние сервисы

Каркас вызова:
```json
{
  "method": "POST",
  "url": "https://...",
  "headers": {"Content-Type": "application/json", "Authorization": "..."},
  "data": {...},                  # тело
  "parser": "application/json",
  "timeout": 2000,                # мс
  "responseCode": "<varName>",    # куда положить HTTP-код
  "exportVariables": {...},       # из ответа в bot-vars
  "exportCookie": "my-cookie",
  "cacheCookie": false,
  "insecureSkipVerify": true,
  "path": {}
}
```

Уникальные endpoints, по которым ходит этот бот:

| Метод | URL                                                                              | Кол-во | Что делает |
|-------|----------------------------------------------------------------------------------|------:|-----------|
| GET   | `https://api.credito365.co/api/partner/webitel/client-info?phone=${user}`        | 1 | Карточка клиента по WA-номеру |
| GET   | `https://api.credito365.co/api/partner/webitel/client-info?phone=${destination}` | 1 | То же по `destination` |
| POST  | `https://api.credito365.co/api/partner/webitel/robot_phone_result_v2`            | 3 | Запись результата диалога в CRM |
| POST  | `https://api.openai.com/v1/conversations`                                        | 1 | LLM: открыть/получить thread |
| POST  | `https://api.openai.com/v1/responses`                                            | 1 | LLM: ответ |
| POST  | `https://api.telegram.org/bot{TOKEN}/sendMessage` → `chat_id=-1002627199331`     | 7 | Алерты в Telegram |

### `joinQueue` — очереди операторов

В этом боте используются 4 очереди (все `type=6` — chat, ext=`${collector_id}` назначается из ответа CRM):

| Queue id | Имя                                              | Приоритет в schema |
|---------:|--------------------------------------------------|-------------------:|
| 32       | Collection WhatsApp-Infobip                      | 100 |
| 137      | Collection Whatsapp - Infobip - PRECOLLECTION    | 1000 |
| 150      | Collection Whatsapp - Infobip - COLLECTION       | 1000 |
| 151      | Collection Whatsapp - Infobip - HARD             | 1000 |

### `export` — что отображается агенту в карточке чата

Три блока экспорта (объединяются Webitel'ом):
1. служебные результаты диалога: `contact_type`, `contact_result`, `promise_type`, `promise_date`.
2. полный лог: `chat_log`.
3. визуальные строки на испанском (отображаются оператору): «La promesa final…», «Código promocional»,
   «Descuento activo», «Días de retraso en el pago», «Nombre del cliente», «Cantidad para liquidar el préstamo» и т.п.

### Часто используемые переменные

Из 51 операции `set` — топ переменных, которые этот бот сам присваивает: `alert_type`, `stage`,
`extension`, `promise_type`, `contact_result`, `vars_to_check`, `test_owner`, `contact_type`,
`Descuento activo`. Остальные переменные приходят либо из `recvMessage` (ввод пользователя),
либо из `exportVariables` httpRequest'ов (CRM/OpenAI), либо из системных (`${user}`, `${destination}`,
`${conv_id}`).

## 4. Что нужно параметризовать при адаптации под другую компанию

Когда захотим клонировать этот шаблон на AR / PE / CO2 — это места, которые нельзя переносить как есть:

| Место                                            | Источник нового значения |
|--------------------------------------------------|--------------------------|
| `name` schema'ы (`whatsapp-infobip-{slug}-prod`) | `companies.json` → `name` (lowercased) |
| `id` (top-level)                                 | назначается Webitel'ом при создании; в шаблоне обнулять |
| `httpRequest` хост CRM (`api.credito365.co/...`) | `companies.json` → `crm_host` |
| `httpRequest` Authorization для CRM              | `companies.json` → `crm_access_token` |
| Очередь(и) в `joinQueue` (`id`, `name`)          | per-tenant; нужно резолвить по имени через `GET /call_center/queues?type=6&q=...` |
| Telegram bot token + `chat_id` в URL/data        | per-tenant (или общий — уточнить) |
| OpenAI ключ (если в headers)                     | per-tenant или общий |
| Тексты `sendText` и поля `export` на испанском   | переводить под язык страны (Argentina — `es-AR`, Peru — `es-PE`, Colombia — `es-CO`) |
| Метаданные (`createdAt/By`, `updatedAt/By`)      | удалять при импорте — Webitel перезапишет |
| `payload.positions` и UUID-теги узлов            | можно оставить как есть; Webitel-редактор это переварит |

В `schema` все места, требующие подмены, ищутся по подстрокам:
`api.credito365.co`, `\"id\": \"32\"` / `\"137\"` / `\"150\"` / `\"151\"` (с проверкой контекста — внутри `joinQueue`),
`api.telegram.org/bot…`, `chat_id`, `${company_name}`/`${process_name}` (если они hardcoded).

## 5. Что инвариантно (можно переносить без правок)

* Топология 8 страниц и логика ветвления внутри них.
* Имена локальных переменных бота (`stage`, `alert_type`, `contact_result`, `promise_*`, `collector_id`,
  `loan_id`, `crm_*`, `tg_*`).
* Шаблон тревожного сообщения в Telegram (только токен/chat_id меняются).
* Имена системных переменных: `${user}` (номер собеседника), `${destination}`, `${conv_id}`.
* Структура верхнего уровня (`type`/`editor`/`tags`).
* Валидация ответов CRM по `responseCode`/`vars_to_check` (паттерн «получили — проверили — алерт при отклонении»).

## 6. Как этот файл будет использоваться в Hub'е (план, не реализовано)

* `data/bot_templates/whatsapp_infobip/credito365_prod.json` — снапшот-«источник истины».
* В будущей фиче «Создать/обновить WhatsApp бота для компании X» Hub:
  1. Берёт этот файл как шаблон.
  2. Подменяет per-tenant поля из таблицы выше (`crm_host`, `crm_access_token`, `queue ids`,
     возможно языковые строки).
  3. Стирает `id`, `createdAt/By`, `updatedAt/By`.
  4. Заменяет `name` на `whatsapp-infobip-{slug}-prod`.
  5. POST'ит в `{webitel_host}/api/routing/schema` (создание) или PUT в `/{id}` (обновление существующей).
* До тех пор файл хранится just-in-case как референс — менять его руками не нужно.
