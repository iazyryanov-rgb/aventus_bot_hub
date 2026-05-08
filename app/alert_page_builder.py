"""Generator for the new (clean) Alert-page payload.

Replaces the legacy 13-node Alert page (1 switch + 7-8 httpRequest + 2 if
+ 2 js, with broken case→httpRequest routing) with a 3-node design:

    start → js (alert_payload_builder) → httpRequest (TG sendMessage)

The js node:
  * normalises `${alert_type}` into a stable `kind` slug;
  * collects every potentially-relevant channel-var (CRM-related, OpenAI-
    related, Collection-related, etc.) into a JSON `details` block;
  * builds a human-readable Telegram-HTML message;
  * routes to the correct per-company forum topic via `${project_index}`;
  * returns a single JSON string that is the entire TG sendMessage body.

The httpRequest node uses `data: "${alert_request_body}"` as its full
body — no per-template text strings, no switch routing, no port-uuid
churn. The whole alert flow is now visible in one place (the js).

Per-schema parameters (champion 110 = champion, candidate 126 =
candidate, etc.) are baked into the js as constants by
`build_alert_payload_js()`.

Format the bot emits (the hub will parse this in Phase I):

    {ICON} <b>{Title}</b>
    🏢 <b>{company}</b> · #{process_name}
    📍 Stage: ...
    👤 Tester: ...
    📱 ...

    {per-kind human-readable body}

    <pre>
    {
      "v": 1,
      "kind": "broken_validation",
      "alert_type_raw": "Broken validation",
      "company_key": "CO_",
      "schema_id": 126,
      "schema_role": "candidate",
      "chat_id": "...",
      "stage": "...",
      "destination": "...",
      "test_owner": "...",
      "ts_ms": 1714999999000,
      "details": { ... }
    }
    </pre>

Stable `kind` slugs: `crm_validation`, `integration_fail`,
`broken_validation`, `unclear_company_index`, `response_fail`,
`anomaly_case`, `wrong_collection_group`, `crm_fail`, `unknown`.
"""
from __future__ import annotations

import json
import secrets
import uuid
from typing import Optional

# These match the existing bot-side TG config (alerts.py DEFAULT_CONFIG).
# Keeping them in code rather than reading from alerts.json so the
# generator doesn't depend on hub state at js-build time.
TG_BOT_TOKEN = "8051942313:AAFyj5poYItKlp0idbCQxw2OdE6WTWMDutw"
TG_CHAT_ID = "-1002627199331"

# project_index → message_thread_id (per-company forum topic).
# Mirrors `alerts.json:telegram.topics`.
COMPANY_TOPICS = {
    "AR_": 159293,
    "PE_": 159294,
    "CO_": 159295,
    "CO2_": 159297,
}


# --- ID helpers -------------------------------------------------------------

def _new_node_id() -> str:
    return secrets.token_hex(8)


def _new_port_id() -> str:
    return str(uuid.uuid4())


def _new_conn_id() -> str:
    return secrets.token_hex(8)


def _input_port(pid: str) -> dict:
    return {
        "id": pid,
        "label": pid,
        "type": "in",
        "socket": {"name": "socket"},
        "multipleConnections": True,
        "showControl": True,
        "control": None,
    }


def _output_port(pid: str, position: int) -> dict:
    return {
        "id": pid,
        "label": pid,
        "type": "out",
        "socket": {"name": "socket"},
        "position": position,
        "goto": False,
        "multipleConnections": False,
    }


def _make_node(
    *,
    label: str,
    page_id: str,
    schema: dict,
    n_inputs: int = 1,
    n_outputs: int = 1,
    description: Optional[str] = None,
) -> tuple[dict, list[str], list[str]]:
    nid = _new_node_id()
    in_ids = [_new_port_id() for _ in range(n_inputs)]
    out_ids = [_new_port_id() for _ in range(n_outputs)]
    node = {
        "id": nid,
        "label": label,
        "pageId": page_id,
        "description": description,
        "inputs": {pid: _input_port(pid) for pid in in_ids},
        "outputs": {
            pid: _output_port(pid, i) for i, pid in enumerate(out_ids)
        },
        "commons": {"break": False, "limit": None},
        "controls": {},
        "schema": schema,
        "tag": f"{label}__{nid}",
    }
    return node, in_ids, out_ids


def _make_connection(
    src: dict, src_port: str, tgt: dict, tgt_port: str, page_id: str,
) -> dict:
    return {
        "id": _new_conn_id(),
        "pageId": page_id,
        "source": src["id"],
        "sourceOutput": src_port,
        "target": tgt["id"],
        "targetInput": tgt_port,
    }


# --- JS source --------------------------------------------------------------

def build_alert_payload_js(schema_id: int, schema_role: str) -> str:
    """Render the alert builder JS for a specific schema. The js is a
    self-contained string the Webitel `js` node will execute on every
    Alert-page invocation.
    """
    topics_json = json.dumps(COMPANY_TOPICS)
    chat_id = TG_CHAT_ID
    return r"""
function val(name) {
  var v = _getChannelVar(name);
  if (v === null || typeof v === 'undefined') return '';
  var s = String(v).replace(/^\s+|\s+$/g, '');
  if (s === 'undefined' || s === 'null') return '';
  return s;
}
function num(name) {
  var s = val(name);
  if (s === '') return null;
  var n = Number(s);
  return (n !== n) ? null : n;
}

var KIND_TABLE = {
  'Validation':              {kind: 'crm_validation',         title: 'CRM Validation',         icon: '⚠️'},
  'conversations_response':  {kind: 'integration_fail',       title: 'Integration · OpenAI', icon: '🔴'},
  'Broken validation':       {kind: 'broken_validation',      title: 'Broken Validation',      icon: '🔴'},
  'Unclear company index':   {kind: 'unclear_company_index',  title: 'Unclear company index',  icon: '🔴'},
  'response':                {kind: 'response_fail',          title: 'OpenAI response fail',   icon: '🔴'},
  'anomaly case':            {kind: 'anomaly_case',           title: 'Anomaly case',           icon: '🔴'},
  'wrong collection group':  {kind: 'wrong_collection_group', title: 'Wrong collection group', icon: '🔴'},
  'CRM_fail':                {kind: 'crm_fail',               title: 'CRM result POST fail',   icon: '🔴'}
};

var raw = val('alert_type');
var entry = KIND_TABLE[raw] || {kind: 'unknown', title: 'Unknown alert', icon: '⚠️'};

var rawDetails = {
  vars_to_check:        val('vars_to_check') || null,
  problem_variable:     val('problem_variable') || null,
  crm_error:            val('crm_error') || null,
  crm_message:          val('crm_message') || null,
  crm_response_code:    val('CRM_response_code_result') || null,
  counter:              num('counter'),
  function_name:        val('function_name') || null,
  function_arguments:   val('function_arguments') || null,
  response:             val('response') || null,
  conversations_response: val('conversations_response') || null,
  contact_type:         val('contact_type') || null,
  contact_result:       val('contact_result') || null,
  promise_type:         val('promise_type') || null,
  promise_date:         val('promise_date') || null,
  promise_amount:       num('promise_amount'),
  collection_group:     val('collection_group') || null,
  dpd:                  num('dpd'),
  link:                 val('link') || null,
  loan_id:              num('loan_id'),
  collector_id:         val('collector_id') || null,
  crm_call_type:        val('crm_call_type') || null,
  project_index:        val('project_index') || null
};
var details = {};
for (var k in rawDetails) {
  if (rawDetails.hasOwnProperty(k) && rawDetails[k] !== null && rawDetails[k] !== '') {
    details[k] = rawDetails[k];
  }
}

var payload = {
  v: 1,
  kind: entry.kind,
  alert_type_raw: raw || null,
  company_key:    val('project_index') || null,
  schema_id:      __SCHEMA_ID__,
  schema_role:    "__SCHEMA_ROLE__",
  chat_id:        val('conv_id') || null,
  stage:          val('stage') || null,
  destination:    val('destination') || null,
  test_owner:     val('test_owner') || null,
  ts_ms:          new Date().getTime(),
  details:        details
};

var lines = [];
lines.push(entry.icon + ' <b>' + entry.title + '</b>');
var orgName = val('company_name') || val('project_index') || '';
var procName = val('process_name') || '';
var orgLine = '🏢 <b>' + orgName + '</b>';
if (procName) orgLine += ' · #' + procName;
lines.push(orgLine);
if (val('stage')) lines.push('📍 Stage: ' + val('stage'));
if (val('test_owner')) lines.push('👤 Tester: ' + val('test_owner'));
if (val('destination')) lines.push('📱 ' + val('destination'));
lines.push('');

function pushIf(label, key) {
  if (details.hasOwnProperty(key) && details[key] !== null && details[key] !== '') {
    lines.push(label + ': ' + details[key]);
  }
}

if (entry.kind === 'crm_validation' || entry.kind === 'crm_fail') {
  pushIf('CRM HTTP', 'crm_response_code');
  pushIf('Fields', 'vars_to_check');
  pushIf('Problem', 'problem_variable');
  pushIf('Error', 'crm_error');
  pushIf('Message', 'crm_message');
} else if (entry.kind === 'integration_fail' || entry.kind === 'response_fail') {
  pushIf('Attempt #', 'counter');
  pushIf('Function', 'function_name');
  pushIf('OpenAI response', 'conversations_response');
  pushIf('Response', 'response');
} else if (entry.kind === 'broken_validation') {
  pushIf('Problem', 'problem_variable');
  if (raw && raw !== 'Broken validation') lines.push('Type: ' + raw);
} else if (entry.kind === 'unclear_company_index') {
  pushIf('project_index', 'project_index');
} else if (entry.kind === 'wrong_collection_group') {
  pushIf('Group', 'collection_group');
  pushIf('DPD', 'dpd');
  pushIf('Link', 'link');
} else if (entry.kind === 'anomaly_case' || entry.kind === 'unknown') {
  if (raw) lines.push('Type: ' + raw);
}

if (val('chat_log')) {
  lines.push('');
  lines.push('━━━ 💬 Chat log ━━━');
  lines.push(val('chat_log'));
}

lines.push('');
lines.push('<pre>' + JSON.stringify(payload, null, 2) + '</pre>');

var TOPICS = __TOPICS_JSON__;
var threadId = TOPICS[val('project_index')] || null;
var tgBody = {
  chat_id: "__TG_CHAT_ID__",
  text: lines.join('\n'),
  parse_mode: 'HTML'
};
if (threadId) tgBody.message_thread_id = threadId;
return JSON.stringify(tgBody);
""".replace(
        "__SCHEMA_ID__", str(int(schema_id)),
    ).replace(
        "__SCHEMA_ROLE__", schema_role,
    ).replace(
        "__TOPICS_JSON__", topics_json,
    ).replace(
        "__TG_CHAT_ID__", chat_id,
    )


# --- Page generator ---------------------------------------------------------

def build_alert_page(
    page_id: str,
    *,
    schema_id: int,
    schema_role: str,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Build the new Alert page (3 nodes + 2 connections + 3 positions).
    Returns (nodes, connections, positions).

    Args:
        page_id: the alert page UUID (kept stable so call-sites don't
            need re-wiring — every business page that does
            `customModule.moduleId = <this id>` keeps working).
        schema_id: the integer id of the schema this page lives in;
            baked into the `payload.schema_id` field so the hub-side
            consumer can attribute alerts.
        schema_role: champion | candidate | router. Same purpose.
    """
    js_body = build_alert_payload_js(schema_id, schema_role)

    start, _, start_outs = _make_node(
        label="start", page_id=page_id, schema={},
        n_inputs=0, n_outputs=1,
    )
    js_node, js_ins, js_outs = _make_node(
        label="js", page_id=page_id,
        schema={"data": js_body, "setVar": "alert_request_body"},
        description=(
            "Alert payload builder (Phase J). Normalises ${alert_type}, "
            "collects context vars, builds Telegram HTML message + JSON "
            "tail, returns the full sendMessage body. Hub-side consumer "
            "parses the <pre>{json}</pre> tail."
        ),
    )
    http_node, http_ins, _ = _make_node(
        label="httpRequest", page_id=page_id,
        schema={
            "method": "POST",
            "url": f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            "headers": {"Content-Type": "application/json"},
            "data": "${alert_request_body}",
            "parser": "application/json",
            "timeout": 5000,
            "responseCode": "tg_alert_http_code",
            "exportVariables": [],
            "exportCookie": "",
            "cacheCookie": False,
            "insecureSkipVerify": False,
            "path": {},
        },
        description="Send to Telegram bot API. Body fully built upstream by the js node.",
    )

    nodes = [start, js_node, http_node]
    connections = [
        _make_connection(start, start_outs[0], js_node, js_ins[0], page_id),
        _make_connection(js_node, js_outs[0], http_node, http_ins[0], page_id),
    ]
    positions = {
        start["id"]: {"x": 0, "y": 0},
        js_node["id"]: {"x": 280, "y": 0},
        http_node["id"]: {"x": 560, "y": 0},
    }
    return nodes, connections, positions
