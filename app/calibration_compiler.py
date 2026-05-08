"""Compile AI calibration recommendations into Webitel-payload patches.

This is the in-code incarnation of the `webitel-schema` skill's pattern
catalog. It maps `applies_to` paths from `chat_audit` recommendations to
concrete coordinates inside `payload.nodes[*].schema`, validates the
resulting payload against the seven invariants, and produces a `Patch`
object that the orchestrator can apply or preview.

Scope (Phase 1):
  * Pattern recognised: WhatsApp-Infobip (Pattern 2 in the skill catalog),
    both v1 (CO_/110) and v2 (AR_/54, CO2_/124, PE_/80). Both share the
    `SMART VERSION` page and `wa_promt_gpt` / `client_content` set-keys.
  * Supported `applies_to`:
      - `gpt.main_prompt`
      - `gpt.builder.client_content_template`
  * Explicitly refused for now:
      - `gpt.secondary_prompt`             — lives inline in httpRequest.data
      - `gpt.functions[*].description`     — same
      - `gpt.functions[*].enum_descriptions.*` — same
      - `gpt.functions[*].parameters.properties.*.enum[+]` — same
    Phase 3 plans either inline JSON-string mutation or a one-time payload
    refactor that extracts these to their own set-nodes.

Mapping table (`SET_NODE_LOCATORS`) is the single source of truth and is
synchronised by hand with `.claude/skills/webitel-schema/references/`. If
the locator changes in the skill, update this table.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Callable, Optional


# --- Pattern identifiers ----------------------------------------------------

PATTERN_WA_INFOBIP_V1 = "wa-infobip-v1"
PATTERN_WA_INFOBIP_V2 = "wa-infobip-v2"
PATTERN_UNKNOWN = "unknown"


# --- Locator table ----------------------------------------------------------
#
# applies_to → (page_name, set_key)
#
# Each entry says: on the page named X, find the `set` node that has a
# `schema.set[*]` entry whose `key == Y`, and that entry's `value` is the
# field we patch.
SET_NODE_LOCATORS: dict[str, tuple[str, str]] = {
    "gpt.main_prompt":                     ("SMART VERSION", "wa_promt_gpt"),
    "gpt.builder.client_content_template": ("SMART VERSION", "client_content"),
}


# Paths the inline-body surgery covers (Phase C.1). Anything starting with
# `gpt.functions[<fn>].description` is also handled (parametric, see below).
_INLINE_BODY_PATHS_LITERAL: set[str] = {
    "gpt.secondary_prompt",
}

# Paths we recognise but still can't patch (Phase C.2 territory).
_INLINE_PATH_DEFERRED_PREFIXES: tuple[str, ...] = (
    # enum_descriptions live as bullet lines inside a tool's parameters.X.description,
    # need bullet-line surgery — defer.
    "gpt.functions[",  # specifically: enum_descriptions / parameters / enum[+]
)


# --- OpenAI httpRequest locator (within the WA-Infobip payload) -------------

_OPENAI_URL_HINTS: tuple[str, ...] = (
    "openai.com/v1/responses",        # current Responses API (Pattern 2 v2)
    "openai.com/v1/chat/completions", # older builds (Pattern 5a)
)


def _find_openai_http_node(payload: dict) -> Optional[dict]:
    """Find the httpRequest node that POSTs to OpenAI Responses or
    chat/completions. Returns the node dict or None."""
    for hint in _OPENAI_URL_HINTS:  # prefer Responses over chat/completions
        for n in (payload.get("nodes") or []):
            if n.get("label") != "httpRequest":
                continue
            url = ((n.get("schema") or {}).get("url") or "")
            if hint in url:
                return n
    return None


# --- Inline body surgeons ---------------------------------------------------
#
# Each surgeon is a pair (extractor, setter):
#   extractor(parsed_body) -> current_value: str
#   setter(parsed_body, new_value: str) -> mutates parsed_body in place
#
# `parsed_body` is the JSON-decoded `httpRequest.schema.data`. The surgeon
# may raise TargetNotFound if the expected structure isn't there.

def _extract_secondary_prompt(body: dict) -> str:
    """Pattern 2 invariant: the developer-role message in `body.input` has the
    shape `${wa_promt_gpt}\\n${client_content}\\n<secondary_prompt>`. The
    secondary_prompt is everything after the second placeholder.
    """
    inputs = body.get("input") or []
    dev = next(
        (m for m in inputs if isinstance(m, dict) and m.get("role") == "developer"),
        None,
    )
    if not dev:
        raise TargetNotFound("body.input has no developer-role message")
    content = dev.get("content")
    if not isinstance(content, str):
        raise TargetNotFound("developer.content is not a string")
    sep = "${client_content}\n"
    idx = content.find(sep)
    if idx < 0:
        raise TargetNotFound(
            "developer.content does not contain '${client_content}\\n' marker; "
            "secondary_prompt extraction needs the canonical Pattern-2 layout"
        )
    return content[idx + len(sep):]


def _set_secondary_prompt(body: dict, new_value: str) -> None:
    inputs = body.get("input") or []
    for m in inputs:
        if not (isinstance(m, dict) and m.get("role") == "developer"):
            continue
        content = m.get("content")
        if not isinstance(content, str):
            continue
        sep = "${client_content}\n"
        idx = content.find(sep)
        if idx < 0:
            raise TargetNotFound(
                "cannot set secondary_prompt: marker missing"
            )
        m["content"] = content[: idx + len(sep)] + new_value
        return
    raise TargetNotFound("no developer message in body.input to update")


def _make_function_description_surgeon(fn_name: str) -> tuple[Callable, Callable]:
    """Surgeons for `gpt.functions[<fn_name>].description`."""
    def extract(body: dict) -> str:
        for tool in (body.get("tools") or []):
            if (tool or {}).get("name") == fn_name:
                return str(tool.get("description") or "")
        raise TargetNotFound(f"no tool named {fn_name!r} in body.tools")

    def setter(body: dict, new_value: str) -> None:
        for tool in (body.get("tools") or []):
            if (tool or {}).get("name") == fn_name:
                tool["description"] = new_value
                return
        raise TargetNotFound(f"no tool named {fn_name!r} in body.tools")

    return extract, setter


# Static mapping: inline_body paths → surgeons.
# Parametric paths (gpt.functions[<fn>].description) are resolved on the fly
# in `_inline_surgeons_for`.
_INLINE_SURGEONS: dict[str, tuple[Callable, Callable]] = {
    "gpt.secondary_prompt": (_extract_secondary_prompt, _set_secondary_prompt),
}


def _inline_surgeons_for(applies_to: str) -> Optional[tuple[Callable, Callable]]:
    """Return (extractor, setter) for an inline-body path, or None if the
    path is unknown / deferred to Phase C.2."""
    static = _INLINE_SURGEONS.get(applies_to)
    if static:
        return static
    m = re.match(r"^gpt\.functions\[([^\]]+)\]\.description$", applies_to)
    if m:
        return _make_function_description_surgeon(m.group(1))
    return None


# --- Errors -----------------------------------------------------------------

class CompilerError(Exception):
    """Base class for compiler errors."""


class UnknownPattern(CompilerError):
    """Payload doesn't match any pattern this compiler knows."""


class UnknownPath(CompilerError):
    """`applies_to` path doesn't match any known locator."""


class InlinePathUnsupported(UnknownPath):
    """`applies_to` is recognised but lives inline in an httpRequest body
    string. Out of scope for Phase 1."""


class TargetNotFound(CompilerError):
    """Locator is known, but the actual node/key isn't in this payload."""


class BeforeMismatch(CompilerError):
    """The recommendation's `before` text doesn't match what's in payload.
    Probably means the schema drifted since the audit ran."""


# --- Data classes -----------------------------------------------------------

SET_VALUE = "set_value"
INLINE_BODY = "inline_body"


@dataclass(frozen=True)
class NodePath:
    page_id: str
    page_name: str
    node_id: str
    json_path: str  # "schema.set[<idx>].value" or "schema.data:<descriptor>"
    kind: str = SET_VALUE


@dataclass(frozen=True)
class Patch:
    target: NodePath
    before: str
    after: str
    rec_id: str
    applies_to: str


# --- Public API -------------------------------------------------------------

def detect_pattern(payload: dict) -> str:
    """Best-effort identification. Returns one of PATTERN_* constants."""
    pages = (payload or {}).get("pages") or []
    names = {p.get("name", "") for p in pages}
    if {"SMART VERSION", "validation data"}.issubset(names):
        # v1 has all of: main, SMART VERSION, validation data, result mapping
        # v2 has: main, validation data, routing, SMART VERSION, agent flow,
        #         result preparation, Alert (no result mapping page)
        if "result mapping" in names:
            return PATTERN_WA_INFOBIP_V1
        if "agent flow" in names or "result preparation" in names:
            return PATTERN_WA_INFOBIP_V2
        return PATTERN_WA_INFOBIP_V2
    return PATTERN_UNKNOWN


def locate_target(payload: dict, applies_to: str) -> NodePath:
    """Translate an `applies_to` path into payload coordinates.

    Returns a NodePath whose `kind` is either:
      * `SET_VALUE` — patchable via `schema.set[i].value` direct mutation;
      * `INLINE_BODY` — patchable via parse/mutate/stringify of the OpenAI
        httpRequest's `schema.data` JSON string.

    Raises:
        UnknownPath: path doesn't match any locator we have.
        InlinePathUnsupported: path is known to be inline-only but isn't
            covered yet (e.g. enum_descriptions, enum[+]).
        TargetNotFound: locator matched, but payload doesn't contain the
            expected page/node/key.
    """
    # 1. Direct set-node locators (Phase B).
    set_locator = SET_NODE_LOCATORS.get(applies_to)
    if set_locator:
        page_name, set_key = set_locator
        pages = (payload or {}).get("pages") or []
        page = next((p for p in pages if p.get("name") == page_name), None)
        if not page:
            raise TargetNotFound(
                f"Page '{page_name}' not present in payload.pages."
            )
        page_id = page.get("id") or ""
        for n in (payload or {}).get("nodes") or []:
            if n.get("pageId") != page_id or n.get("label") != "set":
                continue
            sets = (n.get("schema") or {}).get("set") or []
            for i, kv in enumerate(sets):
                if kv.get("key") == set_key:
                    return NodePath(
                        page_id=page_id,
                        page_name=page_name,
                        node_id=n.get("id") or "",
                        json_path=f"schema.set[{i}].value",
                        kind=SET_VALUE,
                    )
        raise TargetNotFound(
            f"No set-node with key '{set_key}' on page '{page_name}'."
        )

    # 2. Inline-body surgeons (Phase C.1).
    inline = _inline_surgeons_for(applies_to)
    if inline is not None:
        http = _find_openai_http_node(payload)
        if not http:
            raise TargetNotFound(
                "no OpenAI httpRequest node found in payload "
                f"(searched URL hints: {_OPENAI_URL_HINTS!r})"
            )
        # Resolve the page name for diagnostics.
        page_id = http.get("pageId") or ""
        pages = (payload or {}).get("pages") or []
        page = next((p for p in pages if p.get("id") == page_id), None)
        page_name = (page or {}).get("name", "?") if page else "?"
        return NodePath(
            page_id=page_id,
            page_name=page_name,
            node_id=http.get("id") or "",
            json_path=f"schema.data:{applies_to}",
            kind=INLINE_BODY,
        )

    # 3. Recognised-but-deferred inline paths (Phase C.2).
    if any(applies_to.startswith(p) for p in _INLINE_PATH_DEFERRED_PREFIXES):
        raise InlinePathUnsupported(
            f"applies_to '{applies_to}' is an inline body field but the "
            "compiler only supports the function-description form right now. "
            "Phase C.2 plans the rest (enum_descriptions, enum[+])."
        )

    raise UnknownPath(
        f"applies_to '{applies_to}' has no entry in SET_NODE_LOCATORS, "
        "nor in inline-body surgeons. Add a locator if this path should be "
        "supported."
    )


def build_patch(payload: dict, recommendation: dict) -> Patch:
    """Compile a recommendation dict (from audit_pending) into a Patch."""
    applies_to = str(recommendation.get("applies_to") or "")
    target = locate_target(payload, applies_to)
    return Patch(
        target=target,
        before=str(recommendation.get("before") or ""),
        after=str(recommendation.get("after") or ""),
        rec_id=str(recommendation.get("id") or ""),
        applies_to=applies_to,
    )


def apply_patch(payload: dict, patch: Patch, *, strict_before: bool = True) -> dict:
    """Return a NEW payload with the patch applied. Original is untouched.

    `strict_before=True` (default): refuse if the current value doesn't
    match `patch.before`. This guards against patching stale recommendations
    after the schema has drifted. Set to False to force-apply.
    """
    new = copy.deepcopy(payload)
    nodes = new.get("nodes") or []
    node = next((n for n in nodes if n.get("id") == patch.target.node_id), None)
    if not node:
        raise TargetNotFound(
            f"Node {patch.target.node_id} not found in payload "
            "(disappeared between locate and apply)."
        )

    if patch.target.kind == SET_VALUE:
        return _apply_set_value(new, node, patch, strict_before=strict_before)
    if patch.target.kind == INLINE_BODY:
        return _apply_inline_body(new, node, patch, strict_before=strict_before)
    raise CompilerError(f"Unknown NodePath kind: {patch.target.kind!r}")


def _apply_set_value(
    new_payload: dict,
    node: dict,
    patch: Patch,
    *,
    strict_before: bool,
) -> dict:
    m = re.match(r"^schema\.set\[(\d+)\]\.value$", patch.target.json_path)
    if not m:
        raise CompilerError(
            f"Unsupported set-value json_path '{patch.target.json_path}'."
        )
    idx = int(m.group(1))
    sets = (node.get("schema") or {}).get("set") or []
    if idx >= len(sets):
        raise TargetNotFound(
            f"Index {idx} out of range for set-array (len={len(sets)}) "
            f"on node {patch.target.node_id}."
        )

    cur = sets[idx].get("value")
    if strict_before and patch.before and cur != patch.before:
        raise BeforeMismatch(
            f"Stale recommendation: at {patch.target.json_path} on node "
            f"{patch.target.node_id} the live value differs from the "
            f"recommendation's `before`."
        )

    sets[idx]["value"] = patch.after
    return new_payload


def _apply_inline_body(
    new_payload: dict,
    node: dict,
    patch: Patch,
    *,
    strict_before: bool,
) -> dict:
    # json_path format: "schema.data:<applies_to>"
    if not patch.target.json_path.startswith("schema.data:"):
        raise CompilerError(
            f"Unsupported inline-body json_path '{patch.target.json_path}'."
        )
    applies_to = patch.target.json_path[len("schema.data:"):]
    surgeons = _inline_surgeons_for(applies_to)
    if surgeons is None:
        raise CompilerError(
            f"No inline surgeon for '{applies_to}' (locate_target should "
            "have caught this earlier)."
        )
    extractor, setter = surgeons

    schema = node.get("schema") or {}
    raw = schema.get("data")
    if not isinstance(raw, str) or not raw.strip():
        raise TargetNotFound(
            f"node {patch.target.node_id} schema.data is empty/non-string"
        )
    try:
        body = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise CompilerError(
            f"node {patch.target.node_id} schema.data is not valid JSON: {e}"
        )

    cur = extractor(body)
    if strict_before and patch.before and cur != patch.before:
        raise BeforeMismatch(
            f"Stale recommendation: at inline path '{applies_to}' on node "
            f"{patch.target.node_id} the live value differs from the "
            f"recommendation's `before`."
        )

    setter(body, patch.after)

    # Re-serialize. Use indent=4 because that's the format Webitel UI emits
    # (indent doesn't affect runtime — only diff readability if someone
    # opens the schema in UI later).
    schema["data"] = json.dumps(body, ensure_ascii=False, indent=4)
    return new_payload


def validate_invariants(payload: dict) -> list[str]:
    """Return a list of human-readable error strings. Empty list = payload
    passes the seven SKILL.md invariants (relaxed where the SKILL is too
    strict for real-world data — see comments inline)."""
    errors: list[str] = []
    pages = payload.get("pages") or []
    page_ids = {p.get("id") for p in pages}
    nodes = payload.get("nodes") or []
    node_ids = {n.get("id") for n in nodes}

    # Build port-uuid maps for the connection check.
    node_outputs = {
        n.get("id"): set((n.get("outputs") or {}).keys()) for n in nodes
    }
    node_inputs = {
        n.get("id"): set((n.get("inputs") or {}).keys()) for n in nodes
    }

    # Inv 1+2: connections reference real nodes and real port uuids.
    for c in payload.get("connections") or []:
        cid = c.get("id") or "?"
        src = c.get("source")
        tgt = c.get("target")
        if src not in node_ids:
            errors.append(f"connection {cid}: source '{src}' not in nodes")
        if tgt not in node_ids:
            errors.append(f"connection {cid}: target '{tgt}' not in nodes")
        so = c.get("sourceOutput")
        ti = c.get("targetInput")
        if src in node_outputs and so and so not in node_outputs[src]:
            errors.append(
                f"connection {cid}: sourceOutput '{so}' not on node {src}"
            )
        if tgt in node_inputs and ti and ti not in node_inputs[tgt]:
            errors.append(
                f"connection {cid}: targetInput '{ti}' not on node {tgt}"
            )

    # Inv 3: every node has a position entry (else UI renders at 0,0).
    positions = payload.get("positions") or {}
    for n in nodes:
        nid = n.get("id")
        if nid and nid not in positions:
            errors.append(
                f"node {nid} ({n.get('label')}) missing in payload.positions"
            )

    # Inv 4: pageId valid.
    for n in nodes:
        pid = n.get("pageId")
        if pid and pid not in page_ids:
            errors.append(
                f"node {n.get('id')}: pageId '{pid}' not in payload.pages"
            )

    # Inv 5 (relaxed): tag is non-empty. The SKILL says <label>__<id>, but
    # production schemas also use the legacy "<num>-<label>-custom-tag"
    # convention. We accept both — only enforce non-empty.
    for n in nodes:
        if not (n.get("tag") or ""):
            errors.append(f"node {n.get('id')}: empty tag")

    # Inv 6 (skipped): "exactly one start per page" — too restrictive in
    # practice (sub-pages called via customModule may have 0).

    # Inv 7 is enforced by Webitel itself (it recompiles `schema` from
    # `payload` on save), so nothing for us to check.

    return errors


# --- Helpers ----------------------------------------------------------------

def supported_paths() -> list[str]:
    """Diagnostic: every `applies_to` Phase 1 + C.1 can patch (literal paths
    only — does NOT include parametric `gpt.functions[<fn>].description`,
    which is supported for any fn name)."""
    out = list(SET_NODE_LOCATORS.keys())
    out.extend(_INLINE_SURGEONS.keys())
    out.append("gpt.functions[<fn>].description  (parametric)")
    return sorted(out)


def is_supported(applies_to: str) -> bool:
    """Quick check without raising. Used by the UI to filter pending recs."""
    if applies_to in SET_NODE_LOCATORS:
        return True
    if _inline_surgeons_for(applies_to) is not None:
        return True
    return False
