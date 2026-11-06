"""Send a phone notification when a new update shows up, with the verdict."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_NOTIFY,
    CONF_NOTIFY_LEVEL,
    DOMAIN,
    LEVEL_CHECK,
    LEVEL_SAFE,
    LEVEL_UNKNOWN,
    LEVEL_WAIT,
    LEVELS,
    NOTIFY_ALL,
    NOTIFY_INCLUDES,
    NOTIFY_TEXT,
)

_LOGGER = logging.getLogger(__name__)
_ICON = {LEVEL_WAIT: "🔴", LEVEL_CHECK: "🟡", LEVEL_UNKNOWN: "⚪", LEVEL_SAFE: "🟢"}
_REPAIRS = "/config/repairs"


class Notifier:
    """Remembers which update versions were already announced, also across restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.notified")
        self.sent: dict[str, str] = {}

    async def async_load(self) -> None:
        self.sent = (await self.store.async_load() or {}).get("sent", {})

    async def async_notify(self, updates: list[dict[str, Any]], options: dict[str, Any]) -> None:
        targets = options.get(CONF_NOTIFY) or []
        pending = {_key(u): u for u in updates}
        # Forget installed updates, so a later version is announced again.
        self.sent = {k: v for k, v in self.sent.items() if k in pending}
        # A version is announced once, and again only if the verdict gets worse.
        new = [
            u for k, u in pending.items() if k not in self.sent or LEVELS.index(u["level"]) < LEVELS.index(self.sent[k])
        ]
        for update in new:
            self.sent[_key(update)] = update["level"]
        self.store.async_delay_save(lambda: {"sent": self.sent}, 5)

        wanted = NOTIFY_INCLUDES.get(options.get(CONF_NOTIFY_LEVEL, NOTIFY_ALL), NOTIFY_INCLUDES[NOTIFY_ALL])
        new = [u for u in new if u["level"] in wanted]
        if not targets or not new:
            return
        title, message = build_message(new, self.hass.config.language)
        await self.async_send(title, message, options)

    async def async_send(self, title: str, message: str, options: dict[str, Any]) -> None:
        """Send one message to every chosen phone. Tapping it opens Repairs."""
        for target in options.get(CONF_NOTIFY) or []:
            domain, _, service = target.partition(".")
            if not service:
                domain, service = "notify", target
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {
                        "title": title,
                        "message": message,
                        "data": {"url": _REPAIRS, "clickAction": _REPAIRS, "tag": DOMAIN},
                    },
                    blocking=True,
                )
            except Exception:  # noqa: BLE001 - one broken phone must not stop the others
                _LOGGER.warning("Could not send notification with %s", target, exc_info=True)


def build_message(updates: list[dict[str, Any]], language: str) -> tuple[str, str]:
    """Title and text for one or more updates, worst first."""
    text = NOTIFY_TEXT.get(language.split("-")[0], NOTIFY_TEXT["en"])
    updates = sorted(updates, key=lambda u: LEVELS.index(u["level"]))
    if len(updates) == 1:
        update = updates[0]
        title = f"{_ICON[update['level']]} {update['name']} {update['latest']} – {text[update['level']]}"
        return title, "\n".join([verdict(update, language), *_points(update, text, 3)[1:]])
    counts = " · ".join(
        f"{_ICON[level]} {n}"
        for level in (LEVEL_WAIT, LEVEL_CHECK, LEVEL_UNKNOWN, LEVEL_SAFE)
        if (n := sum(u["level"] == level for u in updates))
    )
    title = f"{text['updates'].format(n=len(updates))}: {counts}"
    lines = []
    for update in updates:
        lines.append(f"{_ICON[update['level']]} {update['name']} {update['latest']}")
        lines.append(f"   {verdict(update, language)}")
    return title, "\n".join(lines)


def verdict(update: dict[str, Any], language: str) -> str:
    """One short line: update or not, and the reason from this system."""
    text = NOTIFY_TEXT.get(language.split("-")[0], NOTIFY_TEXT["en"])
    level = update["level"]
    if level == LEVEL_UNKNOWN:
        return text["v_unknown"]
    if level == LEVEL_SAFE:
        n = update.get("not_you", 0) + sum(f.get("affects", "maybe") == "maybe" for f in update["findings"])
        return text["v_safe_n"].format(n=n) if n else text["v_safe"]
    top = next((f for f in update["findings"] if f.get("affects", "maybe") != "no"), None)
    if top is None:
        return text["v_check"].format(what="?")
    return text[f"v_{level}"].format(what=f"{_short(top['title'] or top['text'], 60)} ({reason(top, text)})")


def reason(finding: dict[str, Any], text: dict[str, str]) -> str:
    """Why a finding touches this system, in a few words."""
    if finding.get("affects", "maybe") != "yes":
        return text["maybe"]
    if finding["used_in"]:
        return text["e_used"].format(where=finding["used_in"][0].split(":", 1)[1].strip())
    if finding["source"] in ("log", "repair"):
        return text["e_ha"]
    if finding["source"] == "option":
        return text["e_option"].format(where=finding["title"])
    kind, _, where = (finding.get("evidence") or [":"])[0].partition(":")
    key = {"entity": "e_entity", "yaml": "e_yaml", "integration": "e_integration"}.get(kind)
    return text[key].format(where=where) if key else finding["text"][:40]


def _short(line: str, limit: int) -> str:
    return line if len(line) <= limit else line[: limit - 1].rsplit(" ", 1)[0] + "…"


def _points(update: dict[str, Any], text: dict[str, str], limit: int) -> list[str]:
    points = []
    for finding in [f for f in update["findings"] if f.get("affects", "maybe") != "no"][:limit]:
        line = f"{finding['title']}: {finding['text']}" if finding["title"] else finding["text"]
        line = line if len(line) <= 120 else line[:119].rsplit(" ", 1)[0] + "…"
        points.append(f"{line} ({reason(finding, text)})")
    return points


def _key(update: dict[str, Any]) -> str:
    return f"{update['entity_id'] or 'core'}@{update['latest']}"
