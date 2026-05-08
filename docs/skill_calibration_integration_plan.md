# План: интеграция skill `webitel-schema` в autocalibration хаба

## Контекст

В хабе уже работает AI-калибровка bot_config'а:

```
chats (Webitel) + bot_config → Claude (call_audit)
  → {summary, findings, recommendations[]}
  → audit_history/<COMPANY>/<id>.json
  → audit_pending/<COMPANY>.json
  → CalibrationDialog: оператор выбирает A/B-digits, нажимает Apply
  → wa_bot_config/<COMPANY>.json [ab_split]
  → [✋ ОПЕРАТОР ВРУЧНУЮ КОПИРУЕТ "routing snippet" в Webitel UI]
  → Webitel schema выполняется → CRM POST
```

**Дыра:** между `Apply` в диалоге и `Webitel schema` стоит ручной шаг
copy-paste. AI-рекомендация знает поле в bot_config (`gpt.main_prompt`,
`gpt.functions[…].enum_descriptions.contact_result.…`), но **не знает, в каком
именно `set`-узле живой Webitel-схемы это поле подставляется** — это знает
только скилл `webitel-schema`.

**Skill `webitel-schema`** — это глубокая модель 22 routing-паттернов
(Pattern 2 v2 / 5b / 5c / 8a / …), включая:
- структуру payload (pages, nodes, connections),
- расположение prompt'ов и enum'ов в `set`-узлах под каждый паттерн,
- инварианты payload (7 правил из SKILL.md),
- API-рецепты GET/PUT routing/schema.

## Цель

Замкнуть петлю: AI-рекомендация → автоматический PATCH Webitel-payload →
`POST /api/save_audit_apply` (snapshot+lookup) → ❎ нет ручного copy-paste.

Skill играет роль **компилятора**: переводит абстрактный путь
`applies_to` → конкретную точку в `payload.nodes[*].schema`.

## Не-цели (сознательно)

- Не трогать `action_trees` / `crm_results_body` — это отдельная семантика
  POST в CRM, AI-калибровка туда не лезет.
- Не делать автоприменение без подтверждения оператора. Все правки —
  через CalibrationDialog с предварительным diff.
- Не пытаться калибровать voice-боты в первой итерации — фокус на chat
  (Pattern 2 v2: AR_/54, CO_/110, CO2_/124, PE_/80).
- Не делать full-schema rewrite. Только targeted patches в `set`-узлах.

## Архитектура

Три новых модуля + расширение существующих.

### Новые модули

#### 1. `app/webitel_schema_io.py` — I/O для payload

```python
def fetch_payload(client: WebitelClient, schema_id: int) -> dict
def push_payload(client: WebitelClient, schema_id: int, payload: dict, *, expected_updated_at: int) -> dict
def make_snapshot(payload: dict, label: str) -> Path  # data/webitel_schema_snapshots/<co>/<id>_<ts>_<label>.json
```

- `fetch`: GET `/api/routing/schema/{id}` → берёт `payload` поле.
- `push`: PUT `/api/routing/schema/{id}` с conflict-check (обернуть проверку
  `updated_at` чтобы не перезаписать чужую правку из UI).
- `make_snapshot`: дамп старого `payload` ДО патча в файл (rollback target).

#### 2. `app/calibration_compiler.py` — *тут живёт «знание скилла»*

```python
def detect_pattern(payload: dict) -> PatternId
def locate_target(payload: dict, applies_to: str, pattern: PatternId) -> NodePath
def build_patch(payload: dict, recommendation: dict) -> Patch
def apply_patch(payload: dict, patch: Patch) -> dict  # returns NEW payload
def validate_invariants(payload: dict) -> list[str]   # errors, empty if ok
```

`NodePath` = `{page_id, node_id, json_path_in_schema}`. Например:
- `applies_to = "gpt.main_prompt"` для Pattern 2 v2
- `locate_target` смотрит: страница `SMART VERSION`, ищет `set`-ноду где
  `set[*].key == "main_prompt"` или подобное → возвращает координаты.

`validate_invariants` проверяет 7 правил из `SKILL.md` (все `connections`
ссылаются на существующие `nodes/inputs/outputs`, `pageId` валиден,
`tag` соответствует `<label>__<id>`, и т.д.).

**Это — главная inkarnacja скилла в коде.** Mapping таблицы патернов
кодируется здесь (read-only справочник), импорт из `references/patterns.md`
делается вручную при поддержке (не автогенерация).

#### 3. `app/calibration_apply.py` — orchestrator

```python
def preview(co_key: str, pending: list[Recommendation]) -> ApplyPreview
def apply(co_key: str, approved_recs: list[str], dry_run: bool = False) -> ApplyResult
```

`preview` → diff: какие узлы тронем, before/after значения, инварианты.
`apply` → fetch payload → snapshot → build_patch+apply_patch для каждой
рекомендации → validate_invariants → push_payload → log в `audit_history`.

### Изменения в существующих модулях

#### `app/webitel.py`
- Добавить `get_schema(id)` (полный JSON со всеми полями), `put_schema(id, body)`.
- Добавить `update_schema_payload(id, payload, updated_at)` — обёртка с
  proper Conflict handling.

Reuse: уже есть `_get`, `WebitelError`, headers. Нужны только два метода.

#### `app/ui/calibration_dialog.py`
- Текущая кнопка `Apply` остаётся (пишет в `wa_bot_config`/`ab_split`).
- Добавить кнопку **`Preview Webitel Patch`** → открывает diff-окно
  (`PatchPreviewDialog`).
- В diff-окне кнопка **`Apply to Webitel`** → вызывает
  `calibration_apply.apply()`, показывает результат, обновляет статус.
- При успехе — отметка в audit_history записи `applied_to_webitel_at_ms`.

#### `app/audit_storage.py`
- Расширить структуру элемента `pending`: добавить опциональное поле
  `webitel_target` (заполняется compiler'ом):
  ```json
  {
    "rec_id": "...",
    "applies_to": "gpt.main_prompt",
    "before": "...",
    "after": "...",
    "webitel_target": {
      "schema_id": 110,
      "page_id": "...",
      "node_id": "...",
      "json_path": "schema.set[2].value",
      "compiled_at_ms": 1731000000000
    }
  }
  ```
- `webitel_target` заполняется лениво, при первом `preview`.

### Skill API surface (что скилл «обещает» хабу)

Скилл — это **read-only справочник + инварианты**. Не код, который
импортируется (Python не импортирует скилл напрямую). Связь через два
артефакта:

1. **Lookup-таблица паттернов** в `app/calibration_compiler.py`
   (захардкожена), которая транслирует `applies_to` →
   page-name + set-key для каждого Pattern 2 v2 / 5b / 8a / etc. Эта
   таблица **поддерживается вручную, синхронно со скиллом**. Изменился
   паттерн в скилле → правим табличку. Это не идеально, но альтернатива
   (parsing markdown скилла) хуже.

2. **Чеклист инвариантов** в `validate_invariants` — 1:1 с разделом
   «Проверочный чек-лист» из `.claude/skills/webitel-schema/SKILL.md`.

В скилле добавить новый файл `references/calibration_locators.md` —
машиночитаемую таблицу локаторов (name patterns + page hints + set keys),
которая синхронизируется руками с lookup-таблицей в коде.

## Phases (этапы реализации)

### Phase 0 — фундамент (1-2 дня)
- `webitel_schema_io.py`: fetch/push/snapshot.
- В `webitel.py`: `get_schema`, `put_schema`.
- Каталог `data/webitel_schema_snapshots/<co>/`.
- Smoke-тест: вручную вызвать fetch для CO_/110, дамп, push того же
  payload обратно — проверить, что Webitel принимает.

### Phase 1 — compiler-skeleton (2-3 дня)
- `calibration_compiler.py`: только Pattern 2 v2.
- `detect_pattern`: распознать v2 по уникальному маркеру (например,
  имя страницы `SMART VERSION` + наличие `$${project_index}`-switch).
- `locate_target`: 2-3 базовых пути (`gpt.main_prompt`,
  `gpt.functions[return_final_status].description`).
- `validate_invariants`: 7 правил.
- Unit-тесты на снимках из `data/bot_templates/whatsapp_infobip/*.json`.

### Phase 2 — orchestrator + UI (2-3 дня)
- `calibration_apply.py`: preview + apply.
- `PatchPreviewDialog`: показывает before/after с подсветкой,
  ошибки validation, кнопка `Apply to Webitel`.
- `CalibrationDialog`: новая кнопка `Preview Webitel Patch`.
- E2E на staging (отдельная test-схема, не CO_/110).

### Phase 3 — расширение покрытия паттернов (incrementally)
- Добавить Pattern 5b, 5c, 8a — по мере того, как для них появятся
  AI-рекомендации.
- Каждый новый паттерн = новая запись в lookup-таблице + тесты.

### Phase 4 — отполировать
- Conflict resolution: что делать если `updated_at` Webitel изменился
  между fetch и push (кто-то правил в UI). По умолчанию — abort с
  показом diff.
- Auto-snapshot перед каждым apply (snapshot retention 30 дней).
- Кнопка `Rollback to last snapshot` в UI (использует payload из
  `webitel_schema_snapshots/`).

## Безопасность

1. **Никогда не пишем без preview**. UI обязан показать diff до push.
2. **Snapshot всегда**. Каждый push предваряется снимком текущего payload.
3. **Conflict check.** Если `updated_at` в Webitel сменился — отказ с
   просьбой re-fetch.
4. **Validate invariants — обязательно**. Если 7 правил из SKILL.md
   нарушены — push блокируется.
5. **Allowlist applies_to.** Compiler знает только конкретный набор путей.
   Любой `applies_to`, который ещё не известен — отклоняется с message
   «не знаю как маппить, нужна запись в lookup-таблице». Не угадываем.
6. **Лог всех patch'ей.** В audit_history запись `webitel_apply` с
   `{rec_id, schema_id, before_node, after_node, snapshot_path,
     pushed_at_ms, pushed_by}`.

## Открытые вопросы (нужно подтвердить с пользователем)

1. **Auth для PUT.** Текущий `WebitelClient` использует
   `X-Webitel-Access`-токен с правами на чтение. Имеет ли он права на
   PUT? Если нет — нужен ли отдельный токен / отдельный API-user
   («bot-hub-writer»)?

2. **Conflict policy.** При расхождении `updated_at` — abort, force-push
   с warning, или auto-rebase (взять fresh payload, переприменить
   patch, push)?

3. **Scope первой итерации: только chat (Pattern 2 v2) или сразу
   включаем 8a (WAMM ChatGPT post-processing)?** 8a проще структурно
   (один main page), но он processing — не используется напрямую как
   chat-bot, а пост-обработчик. Калибровать его осмысленно? Если нет —
   фокус только на 2 v2.

4. **Где хранить snapshots?** В `data/webitel_schema_snapshots/<co>/` (
   локально, попадёт в dist-build → не очень). Или в `~/.aventus_bot_hub/snapshots/`
   (вне репо, но не виден другим разработчикам). Или вообще в Webitel
   через notes-API (если есть)?

5. **Кто видит и применяет?** Только админ хаба? Любой пользователь UI?
   Если многопользовательский режим — нужен ли confirmation token /
   second-eye review перед push?

## Где это лежит в репо

После реализации структура:

```
app/
  webitel_schema_io.py        # NEW: fetch/push/snapshot payload
  calibration_compiler.py     # NEW: applies_to → NodePath, validate
  calibration_apply.py        # NEW: orchestrator
  webitel.py                  # MOD: + get_schema, put_schema
  audit_storage.py            # MOD: + webitel_target в pending
  ui/
    calibration_dialog.py     # MOD: + Preview Webitel button
    patch_preview_dialog.py   # NEW: diff + Apply
data/
  webitel_schema_snapshots/   # NEW: rollback targets
.claude/skills/webitel-schema/
  references/
    calibration_locators.md   # NEW: lookup map (синхронно с compiler)
docs/
  skill_calibration_integration_plan.md  # этот файл
```
