# WA-бот CO Credito365 — описания нодов

Это предложенные description-ы к каждому узлу схемы
`whatsapp-infobip-credito365-prod`. Бизнес-логика и связь с Aventus Bot Hub.
Можно вставить в поле `description` соответствующего нода в Webitel-редакторе
(или через JSON-патч).

Соглашения:
- **Hub-link** — точка соединения с приложением Bot Hub (action_trees.py /
  crm_results.py / dashboard / alerts).
- В `${var}` — переменные канала (channel vars).

---

## Page: main (entry, 11 nodes)

### `start` · 834af3069ee39037
Точка входа всего бота. Срабатывает на каждое входящее сообщение от Infobip
(новый чат или возобновление существующего).

### `set` · 2875e746818ef105 — глобальные константы CO
Закрепляет за каналом ключи проекта: `project_index=CO_`,
`currency_index=$${currency_index}` (валюта — переменная домена,
обычно `COP`), `stage="Start WA Bot"` — отметка для validation/routing,
что прямо сейчас идёт инициализация. **Hub-link:** `project_index` =
`company.key` без `_`; `stage` совпадает со списком `case` в нодах
`validation data:switch` и `routing:switch`.

### `switch` · df2983923d539cdb — диспетчер тестовый/прод по номеру
Проверяет `${user}` (МСИСДН отправителя) против трёх служебных номеров:
`79100096386 → Ivan`, `573146365003 → Pablo`, `573122562287 → Jose`,
иначе → `default` (прод-флоу). **Hub-link:** список тестовых номеров —
кандидат на централизацию в Bot Hub (например, отдельный
`data/testers.json`), чтобы дашборды и Crm-test исключали эти разговоры
из бизнес-метрик.

### `set` · 25c72f80501f3af2 — `test_owner = Ivan`
Помечает диалог как тестовый, хозяин теста — Ivan. Это влияет на:
неотправку результата в CRM в финале (см. `if test_owner==''` в SMART
VERSION/agent flow), показ всплывающего notification агенту, формат
TG-алертов.

### `set` · 10c6c8d91041c65f — `test_owner = Jose`
Аналогично для Jose.

### `set` · 0f6363fa55778b8d — `test_owner = Pablo`
Аналогично для Pablo.

### `set` · f8d7ff7360f8a4dd — env для тестового сценария
Фиксирует тестовое окружение: `gpt_key_coll`, `client_question = ${start_message}`
(первое сообщение клиента), `process_name = "WA_bot_CO_results_test"`,
`crm_call_type = "type_inbound_wa_bot"`, `PARTNER-API-KEY`,
`company_name`, **жёстко проставляет `destination = 573108430258`** (фиктивный
тестовый номер, чтобы CRM не получала результат на реального клиента).
**Hub-link:** `process_name` уходит в TG-алерты в качестве хэштега —
именно по нему Hub-Telegram-топики могут разделять test/prod.

### `set` · 0f9ba1ec1d6c1b19 — env для прод-сценария
Тот же набор, но `process_name = "WA_bot_CO_results_prod"` и
`destination = ${user}` (реальный номер клиента). **Hub-link:** при
аналитике в дашборде это "честный" исходящий-в-CRM рейтинг.

### `httpRequest` · 84151068f3ef2ede — GET CRM по телефону
GET `https://api.credito365.co/api/partner/webitel/client-info?phone=${destination}`
с заголовком `PARTNER-API-KEY=${PARTNER-API-KEY}`. Импортирует в канал
до 18 полей: `collector_id, link, client_id, dpd, amount (← outstanding_amount),
ptp_*, loan_id, discount_*, extension_min_payment (← extension_amount),
loan_type, client_full_name (← client_name), last_wa_template,
short_link, status`. **Hub-link:** ровно тот же
endpoint, который мы дёргаем в `crm_lookup.call_crm_by_phone` и
маппим через `crm_field_types.CO_CREDITO365_FIELD_TYPES`.

### `customModule` · ad453195901c602c — заход в "validation data"
moduleId = `aa6189b0-…` ("validation data"). Запускает проверку, что
клиентские переменные после CRM-запроса не пустые. **Hub-link:**
эквивалент нашему readiness-чеклисту в action_tree_panel —
проверка наличия `loan_id, collector_id, dpd, amount, …`.

### `customModule` · 768afe1ae26847ee — заход в "routing"
moduleId = `0a139fda-…` ("routing"). Передаёт управление дальше — в
SMART VERSION или ветку перевода на агента в зависимости от `${stage}`.

---

## Page: validation data (11 nodes)

### `start` · 392ad243dc075772
Вход в модуль валидации. Зовётся из main и из result preparation
(`stage = Finish - Registration result in CRM`), и из всех мест,
где `stage = Broken validation`.

### `switch` · 43b5616620b2685c — выбор набора обязательных переменных
Switch по `${stage}`. Кейсы: `Finish - Registration result in CRM` (мы
закрываем диалог и шлём результат — см. `set 790351`), `Broken validation`
(критическая ошибка флоу, см. `set 82206a`), `Start WA Bot` (только что
получили данные из CRM, см. `set 5319edb6`), `default` (трактуем как
broken).

### `set` · 790351f0a9217166 — список vars для финального POST
`vars_to_check = PARTNER-API-KEY,loan_id,collector_id,crm_call_type,
contact_type,contact_result,chat_log,user,promise_type,promise_date,
promise_amount`. Проверяется перед POST в CRM. **Hub-link:** ровно
поля из `CO_CREDITO365_BODY_FIELDS` в [crm_results.py](../app/crm_results.py).

### `if` · 553bfcbc034fae89 — нужен ли promise_*?
Если `${contact_result} != 'contact_result_promise_of_payment'`, то
promise_* не обязателен (см. `set d2c833`); иначе — обязателен.
**Hub-link:** идентично логике в action_trees: ветка `promise_type`
рисуется только при `contact_result = promise_of_payment`.

### `set` · d2c833d77c4fbd5e — список vars без promise
Сокращённый `vars_to_check` — без promise_*.

### `set` · 5319edb6e52f3a58 — список vars после CRM-загрузки
`vars_to_check = collector_id,link,client_id,dpd,amount,loan_id,
extension_min_payment,loan_type,client_full_name,short_link`. **Hub-link:**
эти 10 полей образуют MVP-минимум, который ожидается в JSON-ответе
CRM. Если что-то null — нечем кормить GPT, поэтому сразу алерт.

### `js` · f7de0c284cb736f0 — incrementer counter
`counter = +counter + 1`. Счётчик повторов для anti-loop
проверок (см. SMART VERSION → `if counter='5'`).

### `js` · dc3b5183b0d1c149 — поиск первой пустой переменной
Парсит `vars_to_check`, проходит по списку, кладёт в `problem_variable`
имя первой пустой (или `OK`, если все заполнены). Используется
в Alert-модуле для построения сообщения «🔍 Fields: … ❌ Problem: …».

### `set` · ac883b4a46ff4493 — `alert_type = Validation`
Помечает алерт как обычный validation-сбой.

### `set` · 82206a36e3f7b22b — `alert_type = Broken validation`
Помечает алерт как критическую ошибку флоу.

### `customModule` · 4ca98a307c2b9430 — заход в Alert
moduleId = Alert. Шлёт в TG соответствующее сообщение.

---

## Page: routing (7 nodes)

### `start` · deaad23b16f47de5
Вход в роутер.

### `switch` · 1c6707108d8f3f7d — диспетчер по `${stage}`
Кейсы: `tranfer2agent` (есть test_owner-фильтр), `openai_error` (после 5
неудачных попыток OpenAI), `anomaly case` (необъяснимая ситуация после
result preparation), `Start WA Bot` (новый диалог), `crm_validation_error`.
Все, кроме первого, идут прямиком в SMART VERSION.

### `if` · d43093caac9922b5 — `${test_owner} == ''`
Если тест — обходим календарь и сразу зовём agent_flow. На проде —
проверяем рабочее время.

### `calendar` · d885aa456a521163 — рабочее время COLLECTION_INBOUND
Проверка календаря id=17 «COLLECTION_INBOUND». Результат пишется в
`collection_work` (true/false). **Hub-link:** этот календарь — **не** один
из тех, что мы рисуем в чек-листе очередей; кандидат на отдельный визуал
"Сейчас рабочее время сектора Collection?".

### `if` · 953c675101b4e972 — `${collection_work} == 'true'`
Если рабочее время — заход в agent_flow; иначе → SMART VERSION (нет
смысла переводить чат на оффлайн-агента).

### `customModule` · 47d3932fb6fb88a9 — agent flow
moduleId = `3f3881fc-…` (agent flow).

### `customModule` · e13929549368c6de — SMART VERSION
moduleId = `a13d61bc-…` (SMART VERSION).

---

## Page: SMART VERSION (LLM, 36 nodes)

### `start` · 7ea7c6f88c79ed8c
Вход в LLM-флоу.

### `js` · 332e2e9b1ce58716 — завтрашняя дата (UTC-6)
Считает `tomorrow_dt` в формате `DD.MM.YYYY` для часового пояса Мехико
(UTC-6). **Hub-link:** GPT использует это как "tomorrow" в правилах
обещания оплаты. Работает для CO/CO2/MX без перехода на летнее время.

### `js` · 7231442683d3e633 — текущая дата (UTC-6)
Аналогично, `cur_dt`.

### `set` · b2268cdafcc360f7 — env для прямой массовой рассылки
В сценарии "клиент пришёл по mass-template" префиксует `chat_log`
строкой `Mass sending: ${last_wa_template}`, ставит
`crm_call_type = "action_type_whatsapp"`, и хардкодит `test_owner = Ivan`
(подозрительно — для прод-mass должно быть пусто, см. ❓).

### `set` · 5b26c504e146425f — собирает контекст для GPT
Строит огромный `client_content` с PROMISE_DATE_TODAY/TOMORROW и
снимком клиента: `dpd, amount, ptp_*, loan_id, extension_min_payment,
discount_*, short_link, loan_term, loan_type, last_contact_*,
client_full_name, status, …`. И ставит `stage = Start - Conversations-Open AI`.
**Hub-link:** этот блок — единственный шанс ответить GPT'у с актуальными
цифрами из CRM. Важно держать список синхронным с тем, что мы тянем в
`crm_lookup`.

### `set` · 54239123f8c944b3 — Системный промпт CO
Записывает в `wa_promt_gpt` ~6 KB текста с правилами работы коллекторского
агента Crédito 365 на испанском: цели (получить promise to pay),
правила классификации обещаний, шкала тонов, запреты, инструкции по
вызову `return_final_status` / `connect_to_agent`. **Hub-link:** имеет
смысл хранить копию в `data/bot_prompts/CO_.txt` для diff-а между билдами
схемы и привязки к веткам action-tree.

### `if` · 61f910147b1034b6 — `${conv_id} == ''`
Первое ли это сообщение в данном диалоге? Если да — создать новый
OpenAI Conversation, иначе — добавить в существующий.

### `httpRequest` · d9a427e8dbef9a8a — POST /v1/conversations
Создаёт новый OpenAI Conversation, кладёт его id в `conv_id`.
Заголовок `Authorization: ${gpt_key_coll}`. Ответ-код в
`conversations_response`.

### `switch` · 70b067faf7ca2a1e — успех создания диалога?
По `conversations_response`. На 200 — добавляем сообщение в этот диалог,
иначе — `alert_type = response`, в Alert.

### `httpRequest` · 148ed7fa6a7a3960 — добавление сообщения в OpenAI
POST в OpenAI Conversations с `client_question`, системным промтом
(`wa_promt_gpt`) и контекстом (`client_content`). Регистрирует tools:
`return_final_status` (выйти из цикла с JSON-аргументами для CRM),
`connect_to_agent` (escalation). Получает в `text` ответ ассистента,
в `function_name` — выбранную функцию, в `function_arguments` — JSON
с полями. **Hub-link:** именно эти `function_arguments` потом
парсятся в `result preparation` и формируют тело POST в CRM.

### `customCode` · fa4e9932d1c609d7 — конкатенация chat_log
Дописывает `<client_full_name>: <client_question>\nWA Bot: <text>` в
`chat_log`. Этот лог потом уходит в CRM как `comment`.

### `export` · 24fbf74c5a832d71 — экспорт chat_log
Экспортирует `chat_log` в Webitel-вариативные переменные диалога —
чтобы при handover агент в Workspace его видел.

### `switch` · bd59d44a06d20cbe — успех ответа GPT?
По коду `response`. 200 → дальше через `function_name`-switch; иначе
`alert_type=conversations_response` + alert.

### `set` · d6583027d490f49a — `alert_type = response`
Метка алерта при не-200 от OpenAI.

### `customModule` · 5961d693c6cfdcf8 — Alert (response)
Шлёт в TG.

### `if` · 6ac1ba421cc699aa — `${counter} = '5'`
Если уже было 5 неуспешных попыток — `stage = openai_error`, выход;
иначе — повтор запроса.

### `set` · ea9df7cce1d9e711 — `stage = openai_error`
После исчерпания лимита переключает stage и идёт через routing →
escalation на агента.

### `set` · a06729be399accbf — `alert_type = conversations_response`
Метка алерта на проблему создания диалога.

### `customModule` · d4fb4391ff26269f — Alert (conversations_response)
Шлёт в TG.

### `if` · 722e4db87084f51d — `${counter} = '5'`
Парный к `6ac1ba`, но для ошибок создания conversation.

### `sendText` · a5d3cd6cf6cc1ce1 — отправить ответ ассистента клиенту
Шлёт `${text}` (то, что вернул GPT). **Hub-link:** все клиентские
сообщения проходят здесь — именно эти строки можно мониторить на стороне
Hub'а, если хотим вести историю.

### `if` · 530b2d3570904b38 — `${test_owner} == ''`
Прод (timeout 60 сек) или тест (10 минут — больше времени тестеру)?

### `recvMessage` · d3a9c59eb6b54d89 — приём сообщения, прод
timeout=60 секунд. Если клиент не ответил — `client_question = ''`.

### `recvMessage` · 8a1ea7a2adab0eb8 — приём сообщения, тест
timeout=600 секунд.

### `if` · 41165e2dd6d19373 — клиент не ответил?
Если `client_question == ''` — переходим к проверке файлов / напоминанию;
иначе сразу зовём GPT.

### `if` · 40a84ebf1c02d481 — клиент прислал файл?
Если есть `client_question.file.id` — отправляем "у меня нет ответа,
закроем через 5 минут" + ждём; иначе — сразу `tranfer2agent`.

### `sendText` · 41bcd0af3360498d — мягкое предупреждение
"Estimado cliente: a menos que tenga alguna otra pregunta, cerraré
esta solicitud en 5 minutos."

### `if` · ee850c572f3ff75a — тестер vs прод (длинный таймаут)
Опять разделение на тест/прод.

### `recvMessage` · 0dcd82861bab012e — recvMessage прод 30 сек
Короткий таймаут после предупреждения.

### `recvMessage` · baee919ae71884f6 — recvMessage тест 300 сек
Тестовая длинная пауза.

### `if` · bc6b7aff7e634f68 — клиент молчит после предупреждения?
Если опять `client_question == ''` → последний нужный вопрос, иначе —
GPT.

### `sendText` · 3c81c94fb59924ba — финальный поджим
"${client_full_name}, estamos a la espera de su respuesta para poder
avanzar y establecer un acuerdo de pago…"

### `set` · a589ee1d25353437 — фолбэк-результат "ongoing"
`contact_type=Client, contact_result=ongoing_negotiation`. **Hub-link:**
это тех. метка, не из канонического списка action_trees — её бот в CRM
не отправляет (нет дальнейшего HTTP request).

### `switch` · fe20be81b184c9f6 — диспетчер по `function_name`
Кейсы: `return_final_status` (закрываем разговор → result preparation),
`connect_to_agent` (escalation), `default` (продолжаем диалог — отвечаем
текстом и слушаем).

### `customModule` · 93fd8f3a06bb7994 — result preparation
moduleId = `1e5656f5-…`. Зовётся при `return_final_status`.

### `set` · 54fdbc319d71d335 — `stage = tranfer2agent`
Перед заходом в routing для escalation.

---

## Page: agent flow (handover, 19 nodes)

### `start` · 236b135a981d4a88
Вход в флоу перевода на коллектора.

### `httpRequest` · 9e7e4b3f51b54ac5 — GET CRM (свежие данные)
Те же поля, что в main, но повторно — чтобы у агента были самые свежие
цифры (DPD/amount могли поменяться за время диалога с ботом).
URL: `…?phone=${user}` (не destination).

### `userInfo` · be90f3065801aeb4 — collector_name из Webitel
По `${collector_id}` (extension) тянет `name → collector_name` и
`extension → webitel_user_id`. **Hub-link:** этот collector_id берётся из
CRM-ответа; в нашем action_trees мы пишем `company.crm_bot_id` (id бота
в CRM-стенде), а тут — реальный персональный коллектор.

### `unSet` · 7fba257eef5ea959 — скрыть тех. переменные от Workspace
Существует, но `unSet` пуст — значит ничего не скрывает (заглушка/TODO).

### `if` · c3a3d9509ec257b8 — есть ли активный дисконт?
`${discount_valid_to} == ''` → нет дисконта → fallback-текст;
иначе → строка `${discount_type} hasta ${discount_valid_to} pago
${discount_payment}`.

### `set` · e5b1e7b2aef4ff0a — "No hay descuento"
"Descuento activo" = плейсхолдер.

### `set` · 699382ebea15b192 — "Descuento {type} hasta {date} pago {sum}"
Для активного дисконта.

### `set` · f48fe385ba3a4b81 — испанские агентские переменные
Заполняет 12+ человекочитаемых ключей: "Días de retraso en el pago",
"Nombre del cliente", "Responder al mensaje", "Enlace_al_préstamo",
"Cantidad para liquidar el préstamo", "Registra el resultado" (URL в
агис-админку для регистрации результата). **Hub-link:** это шаблон,
который агент видит в Workspace; при добавлении новых полей в CRM-ответ
их полезно сразу прокидывать сюда.

### `set` · 14aa9ec1b5991517 — `body` для логирования
Дамп всего тела в один key `body`. Используется в TG-алертах.

### `export` · 980b9fe79cb9d95d — экспорт ключей в Workspace
Делает 14 испанских переменных видимыми агенту.

### `if` · 8e60b772c5258005 — `${test_owner} == ''`
В тесте — показать notification, в проде — нет.

### `notification` · 2e5fbc6f5cf1ca02 — баннер о тестовом клиенте
"Este no es un cliente real. El chat fue iniciado por el empleado
${test_owner}." Тип warning, timeout 200.

### `js` · 2b02add1117f6c82 — расчёт collection_group из DPD
`dpd ≤ 0 → G1, 1–15 → G2, ≥16 → G3, иначе unknown`. **Hub-link:** тот же
threshold, что зашит в дашборд (мы рассчитываем ту же группу при
визуализации очередей).

### `switch` · cd51d2a168fdb750 — диспетчер по `collection_group`
G1 → joinQueue 137 (PRECOLLECTION), G2 → joinQueue 150 (COLLECTION),
G3 → joinQueue 151 (HARD), default → wrong-group alert.

### `joinQueue` · 0230aeec6e9f9a6d — Queue 137 PRECOLLECTION
G1, priority 1000.

### `joinQueue` · 60fa19bc0d2a2f42 — Queue 150 COLLECTION
G2, priority 1000.

### `joinQueue` · 5b99efa094a13382 — Queue 151 HARD
G3, priority 1000.

### `set` · d119dee4c12c909d — `alert_type = wrong collection group`
Если DPD не парсится — алерт.

### `customModule` · fab578ef722c5e3f — Alert (wrong collection group)
TG. После — всё равно joinQueue 137 (graceful fallback в самую раннюю
группу).

---

## Page: result preparation (final, 36 nodes)

### `start` · 9970028c971a4b4c
Точка входа после `return_final_status` от GPT.

### `js` · e57accaf878fb35f / `8922cd…` / `cc57ce…` / `82c31e…` / `398f9a…`
Пять JS-нодов парсят `function_arguments` JSON:
`contact_type / contact_result / promise_type / promise_date /
promise_amount` → в одноимённые channel vars.

### `if` · 2488215baf102162 — `${promise_type} == 'no_promise'`
Если GPT сказал "обещания нет" — занулить promise-поля.

### `if` · 49a2c20e669b5e61 — `${contact_result} != 'contact_result_promise_of_payment'`
Аналогично — promise-поля обнуляются для не-PTP результатов.

### `set` · 32f09464d406265f — занулить promise_*
Пустые строки.

### `unSet` · f0c4ca9526899209 — удалить promise_* как channel vars
Полное удаление (не только пустота).

### `export` · 1e887993a982de1e — экспорт contact_*/promise_* в чат
Чтобы при последующем handover-е (если будет) агент их увидел.

### `switch` · d5c8697614086dbb — диспетчер по `contact_result`
9 кейсов. Каждый шлёт свой испанский текст-подтверждение и потом
готовит body. **Hub-link:** все 9 значений совпадают со списком
ветки `contact_result_client` в action_trees.py.

### `sendText` · 41cc61e5ba2c07a3 — confirmation: other
"¡Estamos encantados de ayudarte en cualquier momento!"

### `sendText` · 4376d52b7361fdab — confirmation: refusal_to_transfer_information
"¡Disculpe, hubo un error!" (тут странно — для refusal_to_transfer
текст про ошибку, см. ❓).

### `sendText` · c4a269414c970ace — confirmation: provided_client_contact_info
"Gracias por la información!"

### `sendText` · 6c2068babfffc887 — confirmation: already_payed
"Aún no hemos recibido tu información de pago…"

### `sendText` · 713b0ad44bce2ce3 — confirmation: ptp_follow_up
"Gracias! Esperamos recibir su pago de ${amount} antes del ${promise_date}…"

### `sendText` · b573bb6cc3413ebe — confirmation: refusal_to_pay
"…lamentamos mucho no haber podido resolver el problema del pago de
forma voluntaria. Continuaremos con las gestiones de cobro…"

### `sendText` · b4e79588dc4e9364 — confirmation: customer_with_current_agreement
"¡Gracias! Disculpe las molestias!"

### `sendText` · cd6dc01c5e23dd74 — confirmation: promise_of_payment / discount / no_promise
"Gracias! Esperamos recibir su pago de ${amount}…" (одна формулировка
для нескольких promise-веток, отличаются только сумма и текст про
"улучшает кредитную историю").

### `joinQueue` · 4bd9182a235846ba — Queue 32 Collection WhatsApp-Infobip
Альтернативный handover: для confirmation `paid_after_wa` — кладём
чат в общую группу для finally-проверки человеком. priority 100 (низший).

### `switch` · 2f78cede30a33481 — диспетчер по `promise_type`
6 кейсов. Каждый шлёт свой текст подтверждения с конкретной суммой.

### `sendText` · 02bba3a32e75ca07 — promise_type_extension
"Esperamos recibir su pago de ${extension_min_payment} antes del
${promise_dt}…"

### `sendText` · 604d4d1b4a90f082 — promise_type_discount
"Esperamos recibir su pago de ${discount_payment} del ${promise_dt}…"

### `sendText` · dca9483c51490a46 — promise_type_partial_payment
"Esperamos recibir su pago de ${amount} antes del ${promise_dt}.
Un pago parcial no cubre la totalidad del préstamo…"

### `set` · 8901f2d0d2535d12 — `body` (debug-дамп) + `crm_call_type=action_type_whatsapp`
Записывает в `body` развёрнутый текст со всеми полями и кодом ответа
CRM для использования в алерте; **переключает crm_call_type на
`action_type_whatsapp`** перед самым POST'ом.

### `set` · 8f94c2adf3922a35 — anomaly body
Аналогично, но с `alert_type=anomaly case, stage=anomaly case`. Срабатывает
если `contact_result` пришёл с непредусмотренным значением (default).

### `customModule` · 98588af06f87aa8a — alert (anomaly case)
moduleId validation data — но реально через switch по stage уйдёт в
broken-validation алерт.

### `js` · 7b927e0554604d88 — fallback promise_date = cur_date
Если `promise_date` пустой — подставляем сегодняшнюю дату. Защита от
NPE при POST в CRM.

### `customModule` · f06ae0f91a4803cb — result mapping
moduleId = `b7d79a8c-…`. Финальный normalizer сокращений GPT в slug-и.

### `set` · 4bb0eadf59afab37 — `stage = Finish - Registration result in CRM`
Перед валидацией набора `vars_to_check` для финального POST.

### `customModule` · 213a1e89a883bf46 — validation data (final check)
moduleId validation data. Если что-то пусто — алерт.

### `httpRequest` · 8f704c82ae085f01 — POST CRM result
POST `https://api.credito365.co/api/partner/webitel/robot_phone_result_v2`
с body `{loan_id, collector_id, call_type, contact_type,
direction="direction_incoming", contact_result, comment=chat_log,
phone_number=${destination}, promise_type, promise_date,
promise_amount}` и `PARTNER-API-KEY`. Ответ → `CRM_response_code_result,
crm_error, crm_message`. **Hub-link:** это тот же эндпоинт, что должен
лежать в `companies.json[CO_].crm_results_host`. Тело **точно** совпадает
со схемой `CO_CREDITO365_BODY_FIELDS` в [crm_results.py](../app/crm_results.py).
Поле `phone_number = ${destination}` — отвечает на ❓1 (см. анализ): для
WA-входящего phone_number — это сам клиентский МСИСДН, а не ярлык "user".

### `switch` · 13722452c8514090 — успешен ли POST в CRM?
По `CRM_response_code_result`. 200 → дальше, не-200 → CRM_fail alert.

### `set` · 45b2f17e64a14c0d — Build CRM fail alert vars
Готовит подробный TG-message с дампом запроса + ответа CRM.

### `customModule` · 7e049f6cdb88484d — Send to alerts module
moduleId Alert. Шлёт сообщение в TG.

---

## Page: result mapping (LLM→canonical, 20 nodes)

### `start` · 6c4b88b6d203fd57

### `switch` · 187a07d175bbf65b — `${contact_client}` → contact_type
Кейсы: `contact_type_client`, `third_party_contact`, `default`.

### `set` · 1b9d044b8d2fe5a9 — `contact_type=contact_type_client`
### `set` · a0ed20df9df6cd51 — `contact_type=third_party_contact`

### `switch` · f98c9f4e57d2f4fb — `${contact_result}` → канонический slug
10 кейсов (default + 9 разных contact_result).

### `set` · 63d2d330cc6c8aaf — promise_of_payment
### `set` · b6e987e5234f0f18 — refusal_to_pay
### `set` · cbfadcf587f83f29 — already_payed
### `set` · 581b7f4757c2a244 — ptp_follow_up
### `set` · 930cd5c42adb4882 — customer_with_current_agreement
### `set` · 2b3defb22ef7b2bf — paid_after_wa
### `set` · 29880cd6851af25b — provided_client_contact_info
### `set` · 75b96dfe66c95c5b — other
### `set` · f2f2d5b04c955528 — other (default)

### `switch` · dbd8306b1041d4a5 — `${promise_type}` → канонический slug
5 кейсов.

### `set` · 6ce5cdbdc19d218f — promise_type_full_payment
### `set` · 5747f197fd8fdfc5 — promise_type_partial_payment
### `set` · 902ed0aa595402c0 — promise_type_discount
### `set` · 263ad4b8418c71ff — promise_type_extension
### `set` · 3b341d951bc27ae6 — promise_type = "" (default)

**Hub-link:** все 9 contact_result + 4 promise_type slug-а
зеркалят `CO_CREDITO365_TREE.contact_result_client.values` /
`CO_CREDITO365_TREE.promise_type.values` в action_trees.py.

---

## Page: Alert (TG dispatcher, 13 nodes)

### `start` · ed899224251a673f

### `switch` · d224f14b40996006 — диспетчер по `${alert_type}`
Кейсы: `Validation, conversations_response, Broken validation,
Unclear company index, response, anomaly case, wrong collection group,
CRM_fail`. **Hub-link:** см. ❓ — стоит выровнять имена с шаблонами в
[alerts.py](../app/alerts.py).

### `if` · 57d02ac150d8fccd — `${problem_variable} == 'OK'`
Specifically для `anomaly case`: если problem_variable=OK
(валидация прошла), всё равно шлём детальный лог через
js → fancy message; иначе — простой алерт.

### `if` · 3916b5273c2154f1 — `${test_owner} == ''`
В тесте используем "красивое" сообщение через js, в проде — короткое.

### `js` · f03df09545f4f708 — построитель развёрнутого TG-message
Собирает многосекционный текст: 🤖 OpenAI / 📋 Contact / 🏦 Loan /
🔧 CRM / 💬 Chat log / 📦 Arguments. Полезно для дебага в TG.
**Hub-link:** этот формат — кандидат на унификацию с нашими
`alerts.py` шаблонами.

### `httpRequest` · 502f7cc8001796cd — TG alert: Validation (OK case)
POST на api.telegram.org/bot…/sendMessage, chat_id=`-1002627199331`.

### `httpRequest` · 2e577563b771619e — TG alert: Integration / response
"🔴 Integration | Type: ${alert_type} | AI response: …"

### `js` · 6693d2d8af33d0c9 — counter += 1
В цепочке после Integration-алерта — для counter=5 проверки в
SMART VERSION.

### `httpRequest` · 25dbd1224898fe52 — TG alert: Broken Validation
"🔴 Broken Validation".

### `httpRequest` · 072aa3f67966e64e — TG alert: Company Error
"🔴 Company Error" (для Unclear company index).

### `httpRequest` · 6ffdd16576b498f7 — TG alert: generic Error
"🔴 Error" — для прочих.

### `httpRequest` · d30b35711aa535bc — TG alert: Collection Group
"🔴 Collection Group | Group: ${collection_group} | DPD: ${dpd}".

### `httpRequest` · 122ca78cc001a8ac — TG alert: ⚠️ + tg_message
Принимает `tg_message` (построенный js-узлом f03df0…) и шлёт его как
основной текст. Используется для anomaly case + красивых развёрнутых
алертов.

---

## Hub-side action items (по результатам анализа)

1. `phone_value_wa = "user"` в `action_trees.py:phone_value_wa` →
   рекомендую сменить на **`destination`** (бот шлёт именно его в
   `phone_number`).
2. `comment_value_wa = "chat"` → должно быть **`chat_log`** (бот шлёт
   накопленную беседу).
3. `call_type_value_wa = "action_type_whatsapp"` корректно для прод-флоу;
   но добавить второй вариант **`type_inbound_wa_bot`** для test/inbound
   сценария.
4. Календарь `COLLECTION_INBOUND` (id 17) — добавить в
   `LoanStatusesPanel`-стиле визуал «рабочее время сектора Collection».
5. Чек-лист очередей: реально-используемые ботом — `137 PRECOLLECTION
   (G1)`, `150 COLLECTION (G2)`, `151 HARD (G3)` + одна общая `32 Collection
   WhatsApp-Infobip` для `paid_after_wa`. APTP/BPTP в WA-флоу не
   участвуют — они для voice. Возможно стоит показывать разную сетку для
   voice/whatsapp.
6. Test-номера hardcoded в схеме (79100096386 / 573146365003 /
   573122562287) — централизовать в `data/testers.json`.
7. Промпт CO дублировать в `data/bot_prompts/CO_.txt` для diff-а.
8. Выровнять `alert_type` slug-и: бот шлёт
   `Validation/conversations_response/Broken validation/Unclear
   company index/response/anomaly case/wrong collection group/CRM_fail`,
   у нас в `alerts.py` — `broken_validation/crm_validation/company_error/
   generic_error/integration/collection_group/…`. Сделать соответствие
   1-в-1.
