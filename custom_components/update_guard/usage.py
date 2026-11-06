"""Your own setup: what you use, and what Home Assistant already warned about."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
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


# Attributes almost every entity has: a changelog naming them says nothing about you.
_COMMON_ATTRIBUTES = {
    "friendly_name", "unit_of_measurement", "device_class", "state_class", "supported_features", "entity_picture",
    "attribution", "assumed_state", "last_reset", "restored", "options", "editable",
}


def entity_terms(hass: HomeAssistant, domains: set[str] | None = None, device_id: str | None = None) -> dict[str, str]:
    """Names to look for -> the entity they belong to, for the integrations (or the device) being updated.

    Entity IDs, translation keys (what a changelog calls "the `battery_level` sensor") and attribute names.
    Only what exists in this system, so the same changelog gives different answers in different homes."""
    registry = er.async_get(hass)
    terms: dict[str, str] = {}
    for entry in registry.entities.values():
        if entry.disabled_by:
            continue
        if not ((domains and entry.platform in domains) or (device_id and entry.device_id == device_id)):
            continue
        terms.setdefault(entry.entity_id.lower(), entry.entity_id)
        if entry.translation_key and len(entry.translation_key) >= 6:
            terms.setdefault(entry.translation_key.lower(), entry.entity_id)
        if state := hass.states.get(entry.entity_id):
            for attribute in state.attributes:
                name = str(attribute).lower()
                if len(name) >= 6 and "_" in name and name not in _COMMON_ATTRIBUTES:
                    terms.setdefault(name, entry.entity_id)
    return terms


def mark_entities(findings: list[notes.Finding], terms: dict[str, str]) -> None:
    """Add the entities a finding names (by ID, key or attribute) to its evidence."""
    if not terms:
        return
    for finding in findings:
        found = {f"entity:{terms[k.lower()]}" for k in finding.keywords if k.lower() in terms}
        if found:
            finding.evidence = sorted(set(finding.evidence) | found)[:8]


async def yaml_domains(hass: HomeAssistant) -> set[str] | None:
    """Integrations set up in YAML here: top-level keys and `platform:` entries. None if it can't be read.

    Only the names are kept, never values."""
    from homeassistant.config import async_hass_config_yaml

    try:
        config = await async_hass_config_yaml(hass)
    except Exception:  # noqa: BLE001 - a broken YAML file must not stop the check
        _LOGGER.debug("Could not read the YAML configuration", exc_info=True)
        return None
    domains: set[str] = set()
    for key, value in config.items():
        domain = str(key).split(" ")[0]
        domains.add(domain)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and isinstance(item.get("platform"), str):
                domains.add(item["platform"])
    return domains


def _breaks_by(breaks: str, installed: str, target: str) -> bool:
    b, i, t = (notes.parse_version(v) for v in (breaks, installed, target))
    return bool(b and i and t and i < b <= t)
