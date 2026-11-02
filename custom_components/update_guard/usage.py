"""Your own setup: what you use, and what Home Assistant already warned about."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations

from . import notes
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# "Detected that custom integration 'x' ... This will stop working in Home Assistant 2026.11"
_BREAKS_IN = re.compile(
    r"(?:stop(?:s)? working|(?:will )?be removed|break(?:s)?|no longer work)\s+in\s+(?:Home Assistant\s+)?(\d{4}\.\d{1,2})",
    re.I,
)
_INTEGRATION = re.compile(r"integration '([a-z0-9_]+)'")
_LOGGER_DOMAIN = re.compile(r"(?:custom_components|homeassistant\.components)\.([a-z0-9_]+)")
_KEEP_DAYS = 30


class DeprecationLog(logging.Handler):
    """Remembers 'will stop working in X' warnings, also across restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(logging.WARNING)
        self.hass = hass
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.deprecations")
        self.seen: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        self.seen = (await self.store.async_load() or {}).get("seen", {})
        cutoff = time.time() - _KEEP_DAYS * 86400
        self.seen = {k: v for k, v in self.seen.items() if v["last"] >= cutoff}
        # Warnings logged before we were set up are still in the system log.
        if (handler := self.hass.data.get("system_log")) is not None:
            for entry in handler.records.to_list():
                for message in entry["message"]:
                    self._add(entry["name"], message, entry["timestamp"])
        self._save()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging
            return
        if "in Home Assistant" in message or " be removed in " in message:
            # Any thread can log; keep all changes on the event loop.
            try:
                self.hass.loop.call_soon_threadsafe(self._record, record.name, message, record.created)
            except RuntimeError:
                pass  # loop closed during shutdown

    @callback
    def _record(self, name: str, message: str, when: float) -> None:
        if self._add(name, message, when):
            self._save()

    def _add(self, name: str, message: str, when: float) -> bool:
        match = _BREAKS_IN.search(message)
        if not match:
            return False
        domain = _INTEGRATION.search(message) or _LOGGER_DOMAIN.search(name)
        key = f"{domain[1] if domain else name}:{match[1]}:{message[:120]}"
        self.seen[key] = {
            "domain": domain[1] if domain else None,
            "breaks": match[1],
            "message": notes.shorten(message, 300),
            "last": when,
        }
        return True

    @callback
    def _save(self) -> None:
        self.store.async_delay_save(lambda: {"seen": self.seen}, 10)

    def findings(self, installed: str, target: str) -> list[notes.Finding]:
        """Warnings about things that break after the installed version, up to the target."""
        result = []
        for item in self.seen.values():
            if _breaks_by(item["breaks"], installed, target):
                result.append(
                    notes.Finding(
                        title=item["domain"] or "",
                        text=item["message"],
                        domains=[item["domain"]] if item["domain"] else [],
                        severe=True,
                        source="log",
                    )
                )
        return result


async def repair_findings(hass: HomeAssistant, installed: str, target: str) -> list[notes.Finding]:
    """Repairs that Home Assistant says break after the installed version, up to the target."""
    issues = [
        issue
        for issue in ir.async_get(hass).issues.values()
        if issue.domain != DOMAIN
        and issue.breaks_in_ha_version
        and _breaks_by(issue.breaks_in_ha_version, installed, target)
    ]
    if not issues:
        return []
    texts = await async_get_translations(hass, hass.config.language, "issues", {i.domain for i in issues})
    result = []
    for issue in issues:
        key = f"component.{issue.domain}.issues.{issue.translation_key}.title"
        title = texts.get(key) or issue.translation_key or issue.issue_id
        try:
            title = title.format(**(issue.translation_placeholders or {}))
        except (KeyError, IndexError, ValueError):
            pass
        result.append(
            notes.Finding(
                title=issue.domain,
                text=f"{title} ({issue.breaks_in_ha_version})",
                domains=[issue.domain],
                severe=True,
                source="repair",
            )
        )
    return result


async def config_index(hass: HomeAssistant) -> list[tuple[str, str, str]]:
    """(kind, name, lowercase json) for every automation, script and dashboard."""
    index = []
    for kind in ("automation", "script"):
        component = hass.data.get(kind)
        for entity in getattr(component, "entities", []):
            raw = getattr(entity, "raw_config", None)
            if raw:
                name = entity.name or entity.entity_id
                index.append((kind, str(name), json.dumps(raw, default=str).lower()))
    lovelace = hass.data.get("lovelace")
    for url_path, dashboard in (getattr(lovelace, "dashboards", None) or {}).items():
        try:
            config = await dashboard.async_load(False)
        except Exception:  # noqa: BLE001 - empty or broken dashboards are skipped
            continue
        name = (dashboard.config or {}).get("title") or url_path or "Overview"
        index.append(("dashboard", str(name), json.dumps(config, default=str).lower()))
    return index


def mark_usage(findings: list[notes.Finding], index: list[tuple[str, str, str]]) -> None:
    """Fill used_in for findings whose keywords appear in your config."""
    for finding in findings:
        used = []
        for keyword in finding.keywords:
            needle = keyword.lower()
            used.extend(f"{kind}: {name}" for kind, name, text in index if needle in text)
        finding.used_in = sorted(set(used))[:8]


def _breaks_by(breaks: str, installed: str, target: str) -> bool:
    b, i, t = (notes.parse_version(v) for v in (breaks, installed, target))
    return bool(b and i and t and i < b <= t)
