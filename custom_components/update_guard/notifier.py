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
    LEVEL_WAIT,
    LEVELS,
    NOTIFY_ALL,
    NOTIFY_TEXT,
)

_LOGGER = logging.getLogger(__name__)
_ICON = {LEVEL_WAIT: "🔴", LEVEL_CHECK: "🟡", LEVEL_SAFE: "🟢"}
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

        minimum = options.get(CONF_NOTIFY_LEVEL, NOTIFY_ALL)
        new = [u for u in new if LEVELS.index(u["level"]) <= LEVELS.index(minimum)]
        if not targets or not new:
            return
        title, message = build_message(new, self.hass.config.language)
        for target in targets:
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
        return title, "\n".join(_points(update, text, 3)) or text["nothing"]
    counts = " · ".join(
        f"{_ICON[level]} {n}"
        for level in (LEVEL_WAIT, LEVEL_CHECK, LEVEL_SAFE)
        if (n := sum(u["level"] == level for u in updates))
    )
    title = f"{text['updates'].format(n=len(updates))}: {counts}"
    lines = []
    for update in updates:
        lines.append(f"{_ICON[update['level']]} {update['name']} {update['latest']}")
        lines.extend(f"   {p}" for p in _points(update, text, 1))
    return title, "\n".join(lines)


def _points(update: dict[str, Any], text: dict[str, str], limit: int) -> list[str]:
    points = []
    for finding in [f for f in update["findings"] if not f["general"]][:limit]:
        line = f"{finding['title']}: {finding['text']}" if finding["title"] else finding["text"]
        line = line if len(line) <= 120 else line[:119].rsplit(" ", 1)[0] + "…"
        if finding["used_in"]:
            line += f" ({text['used_in']}: {finding['used_in'][0].split(':', 1)[1].strip()})"
        points.append(line)
    return points


def _key(update: dict[str, Any]) -> str:
    return f"{update['entity_id'] or 'core'}@{update['latest']}"
