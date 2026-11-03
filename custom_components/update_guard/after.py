"""After an update: what stopped working?

A snapshot of what works is kept every 10 minutes while nothing is being installed. When an update entity shows a new
installed version (or Home Assistant itself starts on a new version), what worked before is checked twice, 5 and 30
minutes after the update and after Home Assistant has started. Only what is broken both times is reported, so a
restart or an app that needs a minute to come back is not. Things that belong to the update are told apart from
things that broke at the same time, which may be a coincidence.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, __version__ as HA_VERSION
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from . import notes
from .const import CONF_NOTIFY_LEVEL, DOMAIN, KIND_APP, KIND_CORE, KIND_HACS, KIND_OTHER, LABELS, NOTIFY_TEXT

if TYPE_CHECKING:
    from .coordinator import UpdateGuardCoordinator

_LOGGER = logging.getLogger(__name__)
BASELINE_EVERY = timedelta(minutes=10)
# Right after a start many things are still coming up: don't take that as "what works".
SETTLE = 600
CHECKS = (300, 1800)
_FAILED = {ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY, ConfigEntryState.MIGRATION_ERROR}
_LOGGER_DOMAIN = re.compile(r"(?:custom_components|homeassistant\.components)\.([a-z0-9_]+)")
_AUTOMATION_LOGGER = "homeassistant.components.automation."
MAX_NAMES = 8
# Apps (add-ons) and the integrations that talk to them.
_APP_DOMAINS = {
    "zigbee2mqtt": {"mqtt"},
    "mosquitto": {"mqtt"},
    "matter_server": {"matter"},
    "openthread_border_router": {"otbr", "thread"},
    "silabs_multiprotocol": {"zha", "otbr"},
    "mariadb": {"recorder"},
    "piper": {"wyoming"},
    "whisper": {"wyoming"},
    "openwakeword": {"wyoming"},
    "node_red": {"nodered"},
    "nodered": {"nodered"},
}


def app_domains(slug: str) -> set[str]:
    """Integrations that belong to an app, from its slug (e.g. 45df7312_zigbee2mqtt -> mqtt)."""
    name = re.sub(r"^(?:[0-9a-f]{8}|core|local)_", "", slug).replace("-", "_")
    return _APP_DOMAINS.get(name, {name})


class AfterCheck:
    """Keeps a snapshot of what works and compares with it after an update."""

    def __init__(self, hass: HomeAssistant, coordinator: UpdateGuardCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.after")
        self.baseline: dict[str, Any] | None = None
        self.versions: dict[str, str] = {}
        self.batch: dict[str, Any] | None = None
        # issue id -> what was broken, to remove the repair when it works again.
        self.reports: dict[str, dict[str, Any]] = {}
        self.started: float | None = None
        self._timer: CALLBACK_TYPE | None = None

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.baseline = data.get("baseline")
        self.versions = data.get("versions", {})
        self.batch = data.get("batch")
        self.reports = data.get("reports", {})
        core = data.get("core")
        if core and core != HA_VERSION and self.baseline:
            self._add({"kind": KIND_CORE, "entity_id": None, "name": "Home Assistant", "from": core, "to": HA_VERSION})
        self._save()

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Start once Home Assistant is running. Returns the function that stops it."""
        unsubs: list[CALLBACK_TYPE] = []

        @callback
        def _started(_hass: HomeAssistant) -> None:
            self.started = time.time()
            # A restart after the first check (e.g. to load a HACS update): start the checks over.
            if self.batch and self.batch["first"] is not None and self.batch.get("first_at", 0) < self.started:
                self.batch["first"] = None
            unsubs.append(async_track_time_interval(self.hass, self._tick, BASELINE_EVERY))
            self.async_scan()
            self._schedule()

        unsubs.append(async_at_started(self.hass, _started))

        @callback
        def _stop() -> None:
            for unsub in unsubs:
                unsub()
            if self._timer:
                self._timer()

        return _stop

    @callback
    def async_scan(self) -> None:
        """Notice installed updates: an update entity with a new installed version."""
        registry = er.async_get(self.hass)
        found = []
        for state in self.hass.states.async_all("update"):
            version = state.attributes.get("installed_version")
            entry = registry.async_get(state.entity_id)
            if not version or (entry and entry.unique_id.startswith("home_assistant_core_")):
                continue  # Core is seen by the version Home Assistant starts with.
            old = self.versions.get(state.entity_id)
            self.versions[state.entity_id] = version
            if old and old != version:
                found.append(self._describe(state, entry, old, version))
        for update in found:
            self._add(update)
        if found:
            self._schedule()
        self._save()

    def _describe(self, state, entry: er.RegistryEntry | None, old: str, new: str) -> dict[str, Any]:
        name = state.attributes.get("title") or state.attributes.get("friendly_name") or state.entity_id
        update = {"entity_id": state.entity_id, "name": name, "from": old, "to": new, "domains": [], "device": None}
        platform = entry.platform if entry else None
        if platform == "hassio" and entry and not entry.unique_id.startswith(("home_assistant_", "supervisor")):
            update["kind"] = KIND_APP
            update["domains"] = sorted(app_domains(entry.unique_id.removesuffix("_version_latest")))
        elif platform == "hacs" and entry:
            update["kind"] = KIND_HACS
            update["domains"] = [d] if (d := self.coordinator._hacs_domain(entry.unique_id)) else []
        else:
            update["kind"] = KIND_OTHER
            # Firmware of one device: that device's entities belong to it.
            if entry and entry.device_id and platform not in ("hassio", "hacs"):
                update["device"] = entry.device_id
            elif platform:
                update["domains"] = [platform]
        return update

    def _add(self, update: dict[str, Any]) -> None:
        if self.baseline is None:
            return  # Nothing known from before.
        _LOGGER.debug("Update installed: %s %s -> %s", update["name"], update["from"], update["to"])
        if self.batch is None:
            self.batch = {"updates": [], "before": self.baseline, "first": None}
        # Several updates close together are checked as one; the clock starts again with the last one.
        self.batch["updates"].append(update)
        self.batch["at"] = time.time()
        self.batch["first"] = None

    @callback
    def _tick(self, _now=None) -> None:
        self.async_scan()
        self._clean_reports()
        installing = any(s.attributes.get("in_progress") for s in self.hass.states.async_all("update"))
        if self.batch is None and not installing and self.started and time.time() - self.started >= SETTLE:
            self.baseline = snapshot(self.hass)
            self._save()

    @callback
    def _schedule(self) -> None:
        if self._timer:
            self._timer()
            self._timer = None
        if self.batch is None or self.started is None:
            return
        start = max(self.batch["at"], self.started)
        due = start + (CHECKS[1] if self.batch["first"] is not None else CHECKS[0])
        self._timer = async_call_later(self.hass, max(0, due - time.time()), self._check)

    async def _check(self, _now=None) -> None:
        self._timer = None
        if self.batch is None:
            return
        broken = find_broken(self.hass, self.batch["before"])
        if self.batch["first"] is None:
            self.batch["first"] = broken
            self.batch["first_at"] = time.time()
            self._save()
            self._schedule()
            return
        first = self.batch["first"]
        # Only what was broken at both checks.
        broken = {key: [x for x in broken[key] if x in first[key]] for key in broken}
        batch, self.batch = self.batch, None
        self.baseline = snapshot(self.hass) if self.started else self.baseline
        self._save()
        await self._report(batch, broken)

    async def _report(self, batch: dict[str, Any], broken: dict[str, list[str]]) -> None:
        language = self.hass.config.language.split("-")[0]
        labels = LABELS.get(language, LABELS["en"])
        text = NOTIFY_TEXT.get(language, NOTIFY_TEXT["en"])
        related, other = self._split(batch["updates"], broken)
        errors = _new_errors(self.hass, batch, None if related["everything"] else related["domains"])
        names = ", ".join(f"{u['name']} {u['to']}" for u in batch["updates"])
        count = len(related["entities"]) + len(related["entries"]) + len(other["entities"]) + len(other["entries"])
        options = dict(self.coordinator.config_entry.options)
        if not count and not errors:
            _LOGGER.info("Nothing stopped working after %s", names)
            if options.get(CONF_NOTIFY_LEVEL, "safe") == "safe":
                await self.coordinator.notifier.async_send(f"✅ {text['after_ok'].format(names=names)}", "", options)
            return
        lines = []
        for title, group in ((labels["after_related"], related), (labels["after_other"], other)):
            entries = [self._entry_name(i) for i in group["entries"]]
            entities = self._entity_names(group["entities"])
            if entries or entities:
                lines.append(f"**{title}**")
                lines += [f"- {labels['after_entry']} {e}" for e in entries] + [f"- {e}" for e in entities]
        if errors:
            lines.append(f"**{labels['after_errors']}**")
            lines += [f"- {e}" for e in errors]
        severe = bool(related["entities"] or related["entries"])
        issue_id = f"after_{int(batch['at'])}"
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR if severe else ir.IssueSeverity.WARNING,
            translation_key="after_broken",
            translation_placeholders={"names": names, "count": str(count or len(errors)), "findings": "\n".join(lines)},
        )
        self.reports[issue_id] = {
            "entities": related["entities"] + other["entities"],
            "entries": related["entries"] + other["entries"],
            "at": batch["at"],
        }
        self._save()
        icon = "🔴" if severe else "🟡"
        title = f"{icon} {text['after_broken'].format(names=names, n=count or len(errors))}"
        message = "\n".join(line.replace("**", "") for line in lines[: MAX_NAMES + 2])
        await self.coordinator.notifier.async_send(title, message, options)

    def _split(self, updates: list[dict[str, Any]], broken: dict[str, list[str]]):
        """What belongs to the installed updates, and what else broke at the same time."""
        everything = any(u["kind"] == KIND_CORE for u in updates)
        domains = {d for u in updates for d in u.get("domains", [])}
        devices = {u["device"] for u in updates if u.get("device")}
        entities = er.async_get(self.hass)
        related: dict[str, Any] = {"entities": [], "entries": [], "domains": domains, "everything": everything}
        other: dict[str, Any] = {"entities": [], "entries": []}
        for entity_id in broken["entities"]:
            entry = entities.async_get(entity_id)
            mine = everything or (entry is not None and (entry.platform in domains or entry.device_id in devices))
            (related if mine else other)["entities"].append(entity_id)
        device_entries = {
            e for d in devices if (dev := dr.async_get(self.hass).async_get(d)) for e in dev.config_entries
        }
        for entry_id in broken["entries"]:
            config_entry = self.hass.config_entries.async_get_entry(entry_id)
            mine = everything or entry_id in device_entries or (config_entry and config_entry.domain in domains)
            (related if mine else other)["entries"].append(entry_id)
        return related, other

    def _entity_names(self, entity_ids: list[str]) -> list[str]:
        """Names, one line per device with how many of its entities stopped working."""
        entities, devices = er.async_get(self.hass), dr.async_get(self.hass)
        groups: dict[str, int] = {}
        for entity_id in entity_ids:
            entry = entities.async_get(entity_id)
            device = devices.async_get(entry.device_id) if entry and entry.device_id else None
            if device:
                name = device.name_by_user or device.name or entity_id
            else:
                state = self.hass.states.get(entity_id)
                name = (state and state.attributes.get("friendly_name")) or entity_id
            groups[name] = groups.get(name, 0) + 1
        names = [f"{name} ({n})" if n > 1 else name for name, n in sorted(groups.items())]
        if len(names) > MAX_NAMES:
            names = names[:MAX_NAMES] + [f"+{len(names) - MAX_NAMES}"]
        return names

    def _entry_name(self, entry_id: str) -> str:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        return f"{entry.title} ({entry.domain})" if entry else entry_id

    @callback
    def _clean_reports(self) -> None:
        """Remove a repair once everything in it works again."""
        for issue_id, report in list(self.reports.items()):
            still = find_broken(self.hass, {"ok": report["entities"], "loaded": report["entries"]})
            if not still["entities"] and not still["entries"] or time.time() - report["at"] > 7 * 86400:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                del self.reports[issue_id]
                self._save()

    def _save(self) -> None:
        self.store.async_delay_save(
            lambda: {
                "baseline": self.baseline,
                "versions": self.versions,
                "core": HA_VERSION,
                "batch": self.batch,
                "reports": self.reports,
            },
            5,
        )


def snapshot(hass: HomeAssistant) -> dict[str, Any]:
    """What works right now: available entities and loaded integrations."""
    return {
        "time": time.time(),
        "ok": sorted(s.entity_id for s in hass.states.async_all() if s.state != STATE_UNAVAILABLE),
        "loaded": sorted(e.entry_id for e in hass.config_entries.async_entries() if e.state is ConfigEntryState.LOADED),
    }


def find_broken(hass: HomeAssistant, before: dict[str, Any]) -> dict[str, list[str]]:
    """What worked before and doesn't now. Disabled or deleted things are not broken."""
    registry = er.async_get(hass)
    entities = []
    for entity_id in before["ok"]:
        state = hass.states.get(entity_id)
        entry = registry.async_get(entity_id)
        if state is not None and state.state != STATE_UNAVAILABLE:
            continue
        if state is None and (entry is None or entry.disabled):
            continue
        entities.append(entity_id)
    entries = [
        entry_id
        for entry_id in before["loaded"]
        if (entry := hass.config_entries.async_get_entry(entry_id)) is not None and entry.state in _FAILED
    ]
    return {"entities": entities, "entries": entries}


def _new_errors(hass: HomeAssistant, batch: dict[str, Any], domains: set[str] | None) -> list[str]:
    """Errors logged for the first time after the update, by the updated integrations (None: any) or automations."""
    handler = hass.data.get("system_log")
    if handler is None:
        return []
    since = batch["before"]["time"]
    errors = []
    for record in handler.records.to_list():
        if record["level"] != "ERROR" or record.get("first_occurred", record["timestamp"]) < since:
            continue
        name = record["name"]
        domain = _LOGGER_DOMAIN.search(name)
        if name.startswith(_AUTOMATION_LOGGER) or (domain and (domains is None or domain[1] in domains)):
            errors.append(notes.shorten(record["message"][0] if record["message"] else name, 160))
    return errors[:MAX_NAMES]
