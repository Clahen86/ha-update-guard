"""Help and answers - the same file in each of Clahen86's integrations (keep the copies alike).

- Get help: the user's message, up to 3 pictures and a short diagnosis go privately to the developer (the receiver at
  ep-reports.clahen86.workers.dev files them in a private repository). Only when the user presses Send.
- Answers: when the developer comments on it - or on an error the app reported - the comment is fetched with this
  installation's own id (nobody else can read it), shown in the panel, and gives one notification in Home Assistant per
  new comment. The user can write back on a help report and close an answer ("Close"); a closed issue goes away after a
  week, a seen answer after two weeks, and a new comment brings it back.
- Errors in the app (on unless turned off): the kind of error and where in the code - never the message, which may hold
  names - once a day per error.

Never sent: names of devices, entities, areas or people, addresses, keys or passwords.
"""

from __future__ import annotations

from collections.abc import Callable
import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import time
import traceback
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.components import persistent_notification, websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)
URL = "https://ep-reports.clahen86.workers.dev"
DAY = 24 * 3600
ANSWER_DAYS = 60
FRESH = 7 * DAY  # asked every 10 minutes the first week after a report or an error, then hourly
CLOSED_KEEP = 7 * DAY
SEEN_KEEP = 14 * DAY
SECRET = ("key", "token", "password", "secret", "api", "pin", "code")
NEW_MESSAGE = {
    "da": "💬 Ny besked fra udvikleren. Åbn {name} → 🛟 Hjælp for at læse den.",
    "en": "💬 New message from the developer. Open {name} → 🛟 Help to read it.",
    "de": "💬 Neue Nachricht vom Entwickler. Öffne {name} → 🛟 Hilfe, um sie zu lesen.",
    "fr": "💬 Nouveau message du développeur. Ouvrez {name} → 🛟 Aide pour le lire.",
    "nl": "💬 Nieuw bericht van de ontwikkelaar. Open {name} → 🛟 Hulp om het te lezen.",
    "sv": "💬 Nytt meddelande från utvecklaren. Öppna {name} → 🛟 Hjälp för att läsa det.",
    "nb": "💬 Ny melding fra utvikleren. Åpne {name} → 🛟 Hjelp for å lese den.",
}


class Support:
    def __init__(self, hass: HomeAssistant, domain: str, app: str, name: str,
                 summary: Callable[[], dict[str, Any]] | None = None) -> None:
        self.hass, self.domain, self.app, self.name, self.summary = hass, domain, app, name, summary
        self.store = Store(hass, 1, f"{domain}.support")
        self.d: dict[str, Any] = {}
        self._errors_sent: dict[str, str] = {}
        self.recent_errors: list[str] = []
        self._unsub: list[Callable[[], None]] = []
        self._handler: logging.Handler | None = None

    # ---------- setup ----------
    async def async_setup(self) -> None:
        self.d = await self.store.async_load() or {}
        if not self.d.get("install"):
            self.d["install"] = uuid.uuid4().hex
            await self.store.async_save(self.d)
        self._handler = _ErrorHandler(self)
        logging.getLogger(f"custom_components.{self.domain}").addHandler(self._handler)
        self._unsub.append(async_track_time_interval(self.hass, self._round, datetime.timedelta(minutes=10)))
        self.hass.data.setdefault(f"{self.domain}_support", self)
        if not self.hass.data.get(f"{self.domain}_support_ws"):
            websocket_api.async_register_command(self.hass, _ws_for(self.domain))
            self.hass.data[f"{self.domain}_support_ws"] = True

    def unload(self) -> None:
        for u in self._unsub:
            u()
        self._unsub.clear()
        if self._handler:
            logging.getLogger(f"custom_components.{self.domain}").removeHandler(self._handler)
        self.hass.data.pop(f"{self.domain}_support", None)

    def version(self) -> str:
        try:
            return json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
        except Exception:  # noqa: BLE001
            return "?"

    @property
    def share(self) -> bool:
        return self.d.get("share", True) is not False

    async def _save(self) -> None:
        await self.store.async_save(self.d)

    async def _post(self, path: str, data: dict[str, Any], timeout: int = 30) -> dict[str, Any] | None:
        try:
            s = async_get_clientsession(self.hass)
            async with s.post(f"{URL}{path}", json=data, headers={"x-ep-client": self.app}, timeout=timeout) as r:
                body = await r.json(content_type=None)
                return body if r.status == 200 else {"error": (body or {}).get("error") or f"http_{r.status}"}
        except Exception as e:  # noqa: BLE001 - never in the way
            return {"error": "unreachable", "detail": str(e)[:120]}

    # ---------- errors in the app ----------
    def error(self, record: logging.LogRecord) -> None:
        if not record.exc_info or not record.exc_info[1]:
            return
        exc = record.exc_info[1]
        if _network(exc):
            return
        frames = [f for f in traceback.extract_tb(record.exc_info[2]) if self.domain in f.filename]
        where = f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno} {frames[-1].name}" if frames else "?"
        text = f"{type(exc).__name__} at {where}"
        self.recent_errors = (self.recent_errors + [text])[-10:]
        if not self.share:
            return
        h = hashlib.sha1(text.encode()).hexdigest()[:16]
        today = datetime.date.today().isoformat()
        if self._errors_sent.get(h) == today:
            return
        self._errors_sent[h] = today
        self.d["last_error"] = time.time()
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return  # never from tests
        body = {"kind": "error", "install": self.d.get("install"), "hash": h, "text": text, "version": self.version()}
        # the log can come from any thread - the sending starts on Home Assistant's own loop
        self.hass.loop.call_soon_threadsafe(lambda: self.hass.async_create_background_task(self._post("/t", body), f"{self.domain} error report"))

    # ---------- get help ----------
    def diagnostics(self) -> dict[str, Any]:
        entries = self.hass.config_entries.async_entries(self.domain)
        opts = {}
        for e in entries:
            for k, v in {**e.data, **e.options}.items():
                # only numbers and on/off: text may hold names, entity ids or keys
                if isinstance(v, (bool, int, float)) and not any(s in k.lower() for s in SECRET):
                    opts[k] = v
                elif isinstance(v, (list, dict)) and not any(s in k.lower() for s in SECRET):
                    opts[k] = f"{len(v)} items"
        try:
            extra = self.summary() if self.summary else {}
        except Exception:  # noqa: BLE001
            extra = {"summary_failed": True}
        return {"version": self.version(), "ha": {"version": str(getattr(self.hass.config, "version", "") or ""),
                                                  "country": self.hass.config.country, "language": self.hass.config.language},
                "options": opts, "summary": extra, "errors": self.recent_errors}

    async def send(self, note: str, images: list[dict[str, Any]]) -> dict[str, Any]:
        images = [{"name": str(i.get("name") or "picture")[:60], "data": i["data"]} for i in (images or [])[:3]
                  if isinstance(i, dict) and isinstance(i.get("data"), str) and len(i["data"]) <= 2_000_000]
        res = await self._post("/", {"note": str(note or "")[:4000], "images": images, "diagnostics": self.diagnostics(),
                                     "lang": (self.hass.config.language or "en")[:5], "install": self.d.get("install")}, timeout=60)
        if res and res.get("ok"):
            self.d["last_help"] = {"id": res.get("id"), "t": time.time()}
            self.d["replies"] = {}
            await self._save()
            return {"ok": True, "id": res.get("id")}
        return {"ok": False, "error": (res or {}).get("error", "unreachable")}

    # ---------- answers ----------
    def _last_sent(self) -> float:
        return max(float((self.d.get("last_help") or {}).get("t") or 0), float(self.d.get("last_error") or 0))

    def answer_every(self) -> float | None:
        age = time.time() - self._last_sent()
        if age < ANSWER_DAYS * DAY:
            return 590 if age < FRESH else 3000
        return DAY if self.share else None  # an error sent by an older version

    async def _round(self, _now: Any = None) -> None:
        every = self.answer_every()
        if every and time.time() - float((self.d.get("replies") or {}).get("t") or 0) >= every:
            await self.fetch_answers()

    async def fetch_answers(self) -> None:
        d = await self._post("/replies", {"install": self.d.get("install")})
        if not d or "reports" not in d:
            return
        self.d["replies"] = {"reports": d["reports"][:5], "notes": (d.get("notes") or [])[:5], "t": time.time()}
        newest = max((self._newest(r) for r in self.d["replies"]["reports"] + self.d["replies"]["notes"]), default="")
        seen = self.d.get("seen") if isinstance(self.d.get("seen"), str) else ""
        self.d["seen"] = max(newest, seen)
        await self._save()
        if newest > seen:  # once per new comment - closing the issue changes nothing
            lang = (self.hass.config.language or "en").split("-")[0]
            persistent_notification.async_create(self.hass, NEW_MESSAGE.get(lang, NEW_MESSAGE["en"]).format(name=self.name),
                                                 title=self.name, notification_id=f"{self.domain}_answer")

    @staticmethod
    def _key(r: dict[str, Any]) -> str:
        return str(r.get("id") or "e:" + hashlib.sha1(str(r.get("error")).encode()).hexdigest()[:12])

    @staticmethod
    def _newest(r: dict[str, Any]) -> str:
        return max((str(m.get("t") or "") for m in r.get("msgs") or [] if m.get("from") == "dev"), default="")

    def visible(self, mark_seen: bool = False) -> dict[str, Any]:
        got = self.d.get("replies") or {}
        hidden, shown = self.d.get("hidden") or {}, self.d.setdefault("shown", {})
        now, out = time.time(), {"reports": [], "notes": []}
        for kind in ("reports", "notes"):
            for r in got.get(kind) or []:
                k, new = self._key(r), self._newest(r)
                if k in hidden and hidden[k] >= new:
                    continue
                closed = r.get("closed_at")
                try:
                    if closed and datetime.datetime.fromisoformat(str(closed).replace("Z", "+00:00")).timestamp() < now - CLOSED_KEEP and new <= closed:
                        continue
                except ValueError:
                    pass
                sh = shown.get(k)
                if new and sh and sh.get("t") == new and now - float(sh.get("at") or 0) > SEEN_KEEP:
                    continue
                if mark_seen and new and (not sh or sh.get("t") != new):
                    shown[k] = {"t": new, "at": now}
                out[kind].append({**r, "key": k})
        return out

    async def status(self) -> dict[str, Any]:
        if self.answer_every() and time.time() - float((self.d.get("replies") or {}).get("t") or 0) > 300:
            await self.fetch_answers()
        out = {"share": self.share, "last_help": self.d.get("last_help"), "answers": self.visible(mark_seen=True)}
        await self._save()
        return out

    async def hide(self, key: str) -> None:
        got = self.d.get("replies") or {}
        r = next((x for kind in ("reports", "notes") for x in got.get(kind) or [] if self._key(x) == key), None)
        if r is not None:
            self.d.setdefault("hidden", {})[key] = self._newest(r)
            await self._save()

    async def reply(self, report_id: str, text: str) -> dict[str, Any]:
        res = await self._post("/reply", {"install": self.d.get("install"), "id": str(report_id)[:40], "text": str(text)[:4000]})
        if res and res.get("ok"):
            await self.fetch_answers()
            return {"ok": True}
        return {"ok": False, "error": (res or {}).get("error", "unreachable")}

    async def set_share(self, on: bool) -> None:
        self.d["share"] = bool(on)
        await self._save()


class _ErrorHandler(logging.Handler):
    def __init__(self, support: Support) -> None:
        super().__init__(level=logging.WARNING)
        self.s = support

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.s.error(record)
        except Exception:  # noqa: BLE001
            pass


def _ws_for(domain: str) -> Callable:
    @websocket_api.websocket_command({
        vol.Required("type"): f"{domain}/support",
        vol.Required("action"): vol.In(["status", "send", "reply", "hide", "share"]),
        vol.Optional("note"): vol.All(str, vol.Length(max=4000)),
        vol.Optional("images"): vol.All(list, vol.Length(max=3)),
        vol.Optional("report"): str,  # not "id": that is the websocket message's own number
        vol.Optional("text"): vol.All(str, vol.Length(max=4000)),
        vol.Optional("key"): str,
        vol.Optional("on"): bool,
    })
    @websocket_api.require_admin
    @websocket_api.async_response
    async def ws_support(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
        s: Support | None = hass.data.get(f"{domain}_support")
        if not s:
            connection.send_error(msg["id"], "not_loaded", "Not set up")
            return
        a, res = msg["action"], {}
        if a == "send":
            res = await s.send(msg.get("note", ""), msg.get("images") or [])
        elif a == "reply":
            res = await s.reply(msg.get("report", ""), msg.get("text", ""))
        elif a == "hide":
            await s.hide(msg.get("key", ""))
        elif a == "share":
            await s.set_share(msg.get("on", True))
        connection.send_result(msg["id"], {**res, **(await s.status())})

    return ws_support


@callback
def get_support(hass: HomeAssistant, domain: str) -> Support | None:
    return hass.data.get(f"{domain}_support")


def _network(exc: BaseException) -> bool:
    """Home Assistant restarting or the network gone (502, timeout, no connection) - not a fault in the app."""
    import asyncio

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    try:
        import aiohttp
    except ImportError:
        return False
    if isinstance(exc, aiohttp.ClientResponseError):
        return exc.status >= 500
    return isinstance(exc, aiohttp.ClientConnectionError)
