import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional


class WebitelError(Exception):
    pass


@dataclass
class ChatSchema:
    id: int
    name: str


QUEUE_TYPE_NAMES = {
    0: "Offline (callbacks)",
    1: "Inbound (звонок)",
    2: "Outbound IVR",
    3: "Preview dialer",
    4: "Progressive dialer",
    5: "Predictive dialer",
    6: "Inbound chat",
    7: "Inbound task (Agent task)",
    8: "Outbound task",
    9: "Inbound IM",
    10: "Outbound call",
}


@dataclass
class Lookup:
    id: int
    name: str


@dataclass
class ChatDialog:
    id: str
    title: str
    peer_name: str
    peer_id: str
    peer_type: str
    via_name: str
    started_at_ms: int
    last_msg_at_ms: int
    last_msg_text: str


@dataclass
class ChatMessage:
    id: str
    sender_id: str
    text: str
    date_ms: int


@dataclass
class ChatPeer:
    id: str
    type: str
    name: str


@dataclass
class Agent:
    id: int
    user_id: str
    name: str
    team_name: str


def _parse_lookup(raw: dict | None) -> Optional[Lookup]:
    if not isinstance(raw, dict):
        return None
    rid = raw.get("id")
    name = raw.get("name", "")
    if rid in (None, ""):
        return None
    try:
        return Lookup(id=int(rid), name=name or "")
    except (TypeError, ValueError):
        return None


@dataclass
class Queue:
    id: int
    name: str
    type: int
    enabled: bool
    calendar: Optional[Lookup] = None
    schema: Optional[Lookup] = None
    do_schema: Optional[Lookup] = None
    after_schema: Optional[Lookup] = None
    form_schema: Optional[Lookup] = None
    team: Optional[Lookup] = None
    agents_total: Optional[int] = None
    agents_online: Optional[int] = None
    agents_offline: Optional[int] = None
    agents_pause: Optional[int] = None

    @property
    def type_name(self) -> str:
        return QUEUE_TYPE_NAMES.get(self.type, f"type={self.type}")


class WebitelClient:
    def __init__(self, host: str, token: str, timeout: float = 15.0) -> None:
        self.host = host.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get(self, path: str) -> dict:
        url = f"{self.host}/api{path}"
        req = urllib.request.Request(url, headers={"X-Webitel-Access": self.token})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise WebitelError(f"HTTP {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise WebitelError(f"Network error: {e.reason}") from e
        except (json.JSONDecodeError, ValueError) as e:
            raise WebitelError(f"Invalid response: {e}") from e

    def list_queues(self, types: Optional[list[int]] = None) -> list[Queue]:
        params = ["size=500"]
        for f in (
            "id", "name", "type", "enabled",
            "calendar", "schema", "do_schema", "after_schema", "form_schema",
            "team", "tags",
        ):
            params.append(f"fields={f}")
        if types:
            for t in types:
                params.append(f"type={t}")
        data = self._get("/call_center/queues?" + "&".join(params))
        out: list[Queue] = []
        for it in data.get("items", []) or []:
            try:
                out.append(
                    Queue(
                        id=int(it.get("id", 0)),
                        name=it.get("name", ""),
                        type=int(it.get("type", -1)),
                        enabled=bool(it.get("enabled", False)),
                        calendar=_parse_lookup(it.get("calendar")),
                        schema=_parse_lookup(it.get("schema")),
                        do_schema=_parse_lookup(it.get("do_schema")),
                        after_schema=_parse_lookup(it.get("after_schema")),
                        form_schema=_parse_lookup(it.get("form_schema")),
                        team=_parse_lookup(it.get("team")),
                    )
                )
            except (TypeError, ValueError):
                continue
        return out

    def list_queue_agent_statuses(self, queue_id: int) -> list[str]:
        path = (
            f"/call_center/agents?size=500&queue_id={queue_id}"
            "&fields=id&fields=status"
        )
        data = self._get(path)
        out: list[str] = []
        for it in data.get("items", []) or []:
            out.append(str(it.get("status") or "").lower())
        return out

    def list_agents(self) -> list["Agent"]:
        params = ["size=500"] + [
            f"fields={f}" for f in ("id", "user", "team", "name")
        ]
        data = self._get("/call_center/agents?" + "&".join(params))
        out: list[Agent] = []
        for it in data.get("items", []) or []:
            user = it.get("user") or {}
            team = it.get("team") or {}
            try:
                aid = int(it.get("id", 0) or 0)
            except (TypeError, ValueError):
                aid = 0
            out.append(
                Agent(
                    id=aid,
                    user_id=str(user.get("id", "") or ""),
                    name=str(it.get("name", "") or user.get("name", "") or ""),
                    team_name=str(team.get("name", "") or ""),
                )
            )
        return out

    def list_dialog_members(self, chat_id: str) -> list[ChatPeer]:
        data = self._get(f"/chat/dialogs/{chat_id}/members")
        out: list[ChatPeer] = []
        for it in data.get("data", []) or []:
            p = it.get("peer") or {}
            out.append(
                ChatPeer(
                    id=str(p.get("id", "") or ""),
                    type=str(p.get("type", "") or ""),
                    name=str(p.get("name", "") or ""),
                )
            )
        return out

    def list_dialogs(
        self,
        date_since_ms: Optional[int] = None,
        date_until_ms: Optional[int] = None,
        q: Optional[str] = None,
        size: int = 100,
    ) -> list["ChatDialog"]:
        params = [f"size={size}"]
        if date_since_ms is not None:
            params.append(f"date.since={date_since_ms}")
        if date_until_ms is not None:
            params.append(f"date.until={date_until_ms}")
        if q:
            params.append("q=" + urllib.parse.quote(q))
        data = self._get("/chat/dialogs?" + "&".join(params))
        out: list[ChatDialog] = []
        for d in data.get("data", []) or []:
            via = d.get("via") or {}
            frm = d.get("from") or {}
            msg = d.get("message") or {}
            try:
                started = int(d.get("started", 0) or 0)
                last = int(d.get("date", 0) or 0)
            except (TypeError, ValueError):
                started = last = 0
            out.append(
                ChatDialog(
                    id=str(d.get("id", "")),
                    title=str(d.get("title", "") or ""),
                    peer_name=str(frm.get("name", "") or ""),
                    peer_id=str(frm.get("id", "") or ""),
                    peer_type=str(frm.get("type", "") or ""),
                    via_name=str(via.get("name", "") or ""),
                    started_at_ms=started,
                    last_msg_at_ms=last,
                    last_msg_text=str(msg.get("text", "") or ""),
                )
            )
        return out

    def get_dialog_messages(
        self, chat_id: str, limit: int = 300
    ) -> tuple[list["ChatMessage"], dict[str, "ChatPeer"]]:
        data = self._get(f"/chat/dialogs/{chat_id}/messages?limit={limit}")
        msgs: list[ChatMessage] = []
        for m in data.get("messages", []) or []:
            try:
                ts = int(m.get("date", 0) or 0)
            except (TypeError, ValueError):
                ts = 0
            msgs.append(
                ChatMessage(
                    id=str(m.get("id", "")),
                    sender_id=str((m.get("from") or {}).get("id", "")),
                    text=str(m.get("text", "") or ""),
                    date_ms=ts,
                )
            )
        peers: dict[str, ChatPeer] = {}
        for i, p in enumerate(data.get("peers", []) or [], start=1):
            pid = str(p.get("id", ""))
            peer = ChatPeer(
                id=pid,
                type=str(p.get("type", "") or ""),
                name=str(p.get("name", "") or ""),
            )
            peers[str(i)] = peer
            if pid:
                peers.setdefault(pid, peer)
        return msgs, peers

    def list_chat_schemas(self) -> list[ChatSchema]:
        data = self._get("/routing/schema?type=chat&size=500")
        out: list[ChatSchema] = []
        for it in data.get("items", []) or []:
            try:
                out.append(ChatSchema(id=int(it.get("id")), name=it.get("name", "")))
            except (TypeError, ValueError):
                continue
        return out


def find_whatsapp_infobip_prod(
    items: list[ChatSchema], company_name: str
) -> Optional[ChatSchema]:
    needle = company_name.lower()

    def is_prod(s: ChatSchema) -> bool:
        n = s.name.lower()
        return "whatsapp-infobip" in n and "prod" in n

    narrow = [s for s in items if is_prod(s) and needle in s.name.lower()]
    if narrow:
        return narrow[0]
    broad = [s for s in items if is_prod(s)]
    return broad[0] if len(broad) == 1 else None
