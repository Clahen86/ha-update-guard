"""Collect pending updates and assess them."""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp
from awesomeversion import AwesomeVersion, AwesomeVersionException

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.components.update.const import DATA_COMPONENT, DOMAIN as UPDATE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, __version__ as HA_VERSION
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_filtered, TrackStates
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import notes, usage
from .const import (
    HACS_JSON,
    LABELS,
    DOMAIN,
    GITHUB_RELEASE_LATEST,
    GITHUB_RELEASE_TAG,
    KIND_APP,
    KIND_CORE,
    KIND_HACS,
    KIND_OTHER,
    LEVEL_CHECK,
    LEVEL_NONE,
    LEVEL_WAIT,
    LEVELS,
    MAX_FINDINGS,
    RAW_POST,
    SCAN_INTERVAL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)
_CORE_TITLE = "Home Assistant Core"
_GITHUB_RELEASE = re.compile(r"github\.com/([^/]+)/([^/]+)/releases/(?:tag/)?([^/?#]+)")
_TIMEOUT = aiohttp.ClientTimeout(total=30)

type UpdateGuardConfigEntry = ConfigEntry[UpdateGuardCoordinator]


class UpdateGuardCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Looks at every pending update and says how risky it is."""

    config_entry: UpdateGuardConfigEntry

    def __init__(self, hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.session = async_get_clientsession(hass)
        # Release posts don't change once published: (year, month) -> (findings, url).
        self._posts: dict[tuple[int, int], tuple[list[notes.Finding], str] | None] = {}
        # Changelogs per (entity_id, latest_version).
        self._changelogs: dict[tuple[str, str], str | None] = {}
        # Minimum Home Assistant version of a HACS release: release url -> version.
        self._hacs_min: dict[str, str | None] = {}
        self.deprecations = usage.DeprecationLog(hass)
        self._index: list[tuple[str, str, str]] = []

    @callback
    def async_watch_updates(self) -> None:
        """Re-check when an update entity changes, e.g. a new version shows up."""

        @callback
        def _changed(event: Event[EventStateChangedData]) -> None:
            old, new = event.data["old_state"], event.data["new_state"]
            if (
                old is None
                or new is None
                or old.state != new.state
                or (old.attributes.get("latest_version") != new.attributes.get("latest_version"))
            ):
                self.hass.async_create_task(self.async_request_refresh())

        tracker = async_track_state_change_filtered(self.hass, TrackStates(False, set(), {UPDATE_DOMAIN}), _changed)
        self.config_entry.async_on_unload(tracker.async_remove)

    async def _async_update_data(self) -> dict[str, Any]:
        registry = er.async_get(self.hass)
        self._index = await usage.config_index(self.hass)
        updates: list[dict[str, Any]] = []
        core_seen = False

        for state in self.hass.states.async_all(UPDATE_DOMAIN):
            if state.state != STATE_ON:
                continue
            entry = registry.async_get(state.entity_id)
            platform = entry.platform if entry else None
            attrs = state.attributes
            if platform == "hassio" and entry.unique_id.startswith("home_assistant_core_"):
                core_seen = True
                updates.append(
                    await self._core(
                        attrs.get("installed_version") or HA_VERSION, attrs.get("latest_version"), state.entity_id
                    )
                )
                continue
            kind = (
                KIND_APP if platform == "hassio" and _is_app(entry) else KIND_HACS if platform == "hacs" else KIND_OTHER
            )
            slug = entry.unique_id.removesuffix("_version_latest") if kind == KIND_APP else None
            updates.append(await self._other(state, kind, slug))

        # Docker/Core installs have no core update entity: ask GitHub instead.
        if not core_seen and (latest := await self._latest_core()) and notes.months_between(HA_VERSION, latest):
            updates.append(await self._core(HA_VERSION, latest, None))

        updates.sort(key=lambda u: (LEVELS.index(u["level"]), u["kind"] != KIND_CORE, u["name"].lower()))
        level = updates[0]["level"] if updates else LEVEL_NONE
        self._sync_issues(updates)
        return {
            "level": level,
            "updates": updates,
            # General notes (not tied to an integration) are listed but not counted.
            "findings": sum(1 for u in updates for f in u["findings"] if not f["general"]),
            "checked": dt_util.utcnow().isoformat(),
        }

    async def _core(self, installed: str, latest: str | None, entity_id: str | None) -> dict[str, Any]:
        used = _used_domains(self.hass)
        findings: list[notes.Finding] = []
        ignored = 0
        missing: list[str] = []
        url = None
        for year, month in notes.months_between(installed, latest or ""):
            post = await self._post(year, month)
            if post is None:
                missing.append(f"{year}.{month}")
                continue
            changes, url = post
            # Copies, because matching narrows the domain list.
            relevant, skipped = notes.match_core([notes.Finding(**c.as_dict()) for c in changes], used)
            for finding in relevant:
                finding.title = f"{year}.{month}: {finding.title}"
            findings.extend(relevant)
            ignored += skipped
        if latest:
            # Things Home Assistant itself already warned about.
            findings.extend(self.deprecations.findings(installed, latest))
            findings.extend(await usage.repair_findings(self.hass, installed, latest))
        usage.mark_usage(findings, self._index)
        return _result(
            KIND_CORE, _CORE_TITLE, entity_id, installed, latest, findings, url, ignored=ignored, missing=missing
        )

    async def _other(self, state, kind: str, slug: str | None = None) -> dict[str, Any]:
        attrs = state.attributes
        latest = attrs.get("latest_version") or ""
        text = await self._changelog(state.entity_id, latest, attrs)
        findings = notes.scan_changelog(text or "")
        if kind == KIND_HACS and (needs := await self._hacs_needs(attrs.get("release_url"))):
            findings.insert(
                0,
                notes.Finding(title="", text=f"Home Assistant {needs}", severe=True, source="hacs", keywords=[]),
            )
        if slug and text:
            # Changes to options you have set in the app go first; drop the same line found by keywords.
            options = notes.scan_options(text, await self._app_options(slug))
            seen = {f.text for f in options}
            findings = options + [f for f in findings if f.text not in seen]
        usage.mark_usage(findings, self._index)
        name = attrs.get("title") or attrs.get("friendly_name") or state.entity_id
        result = _result(
            kind, name, state.entity_id, attrs.get("installed_version"), latest, findings, attrs.get("release_url")
        )
        result["has_notes"] = bool(text)
        return result

    async def _app_options(self, slug: str) -> set[str]:
        """Option names set in an app (add-on), via the Supervisor."""
        try:
            from homeassistant.components.hassio import get_supervisor_client

            info = await get_supervisor_client(self.hass).addons.addon_info(slug)
        except Exception:  # noqa: BLE001 - no Supervisor, or the app is gone
            _LOGGER.debug("No options for app %s", slug, exc_info=True)
            return set()
        return notes.option_keys(info.options)

    async def _hacs_needs(self, release_url: str | None) -> str | None:
        """The Home Assistant version a HACS release needs, if newer than the running one."""
        match = _GITHUB_RELEASE.search(release_url or "")
        if not match:
            return None
        if release_url not in self._hacs_min:
            owner, repo, tag = match.groups()
            text = await self._get_text(HACS_JSON.format(owner=owner, repo=repo, tag=tag))
            try:
                self._hacs_min[release_url] = notes.json_value(text, "homeassistant")
            except ValueError:
                self._hacs_min[release_url] = None
        minimum = self._hacs_min[release_url]
        try:
            return minimum if minimum and AwesomeVersion(minimum) > AwesomeVersion(HA_VERSION) else None
        except AwesomeVersionException:
            return None

    async def _changelog(self, entity_id: str, latest: str, attrs: dict) -> str | None:
        key = (entity_id, latest)
        if key not in self._changelogs:
            text = attrs.get("release_summary")
            component = self.hass.data.get(DATA_COMPONENT)
            entity = component.get_entity(entity_id) if component else None
            if entity and entity.supported_features & UpdateEntityFeature.RELEASE_NOTES:
                try:
                    text = await entity.async_release_notes() or text
                except Exception:  # noqa: BLE001 - a broken integration must not stop the check
                    _LOGGER.debug("No release notes for %s", entity_id, exc_info=True)
            self._changelogs[key] = text
        return self._changelogs[key]

    async def _post(self, year: int, month: int) -> tuple[list[notes.Finding], str] | None:
        if self._posts.get((year, month)) is None:
            self._posts[(year, month)] = await self._fetch_post(year, month)
        return self._posts[(year, month)]

    async def _fetch_post(self, year: int, month: int) -> tuple[list[notes.Finding], str] | None:
        release = await self._get_json(GITHUB_RELEASE_TAG.format(tag=f"{year}.{month}.0"))
        slug = notes.post_slug((release or {}).get("body", ""))
        if not slug:
            return None
        text = await self._get_text(RAW_POST.format(slug=slug[0]))
        if not text:
            return None
        return notes.parse_breaking_changes(text), slug[1]

    async def _latest_core(self) -> str | None:
        release = await self._get_json(GITHUB_RELEASE_LATEST)
        return (release or {}).get("tag_name")

    async def _get_json(self, url: str) -> dict | None:
        try:
            async with self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    _LOGGER.debug("%s gave HTTP %s", url, resp.status)
                    return None
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Could not fetch %s: %s", url, err)
            return None

    async def _get_text(self, url: str) -> str | None:
        try:
            async with self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
                return await resp.text() if resp.status == 200 else None
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Could not fetch %s: %s", url, err)
            return None

    @callback
    def _sync_issues(self, updates: list[dict[str, Any]]) -> None:
        """One repair per risky update, removed again when it's gone."""
        wanted = set()
        for update in updates:
            if update["level"] not in (LEVEL_WAIT, LEVEL_CHECK):
                continue
            issue_id = f"risk_{update['entity_id'] or 'core'}"
            wanted.add(issue_id)
            lines = [_line(f, self.hass.config.language) for f in update["findings"] if not f["general"]]
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.ERROR if update["level"] == LEVEL_WAIT else ir.IssueSeverity.WARNING,
                translation_key=f"update_{update['level']}",
                translation_placeholders={
                    "name": update["name"],
                    "installed": update["installed"] or "?",
                    "latest": update["latest"] or "?",
                    "findings": "\n".join(lines),
                },
                learn_more_url=update["release_url"],
            )
        for issue_id in [
            i for (d, i) in ir.async_get(self.hass).issues if d == DOMAIN and i.startswith("risk_") and i not in wanted
        ]:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)


def _result(
    kind: str,
    name: str,
    entity_id: str | None,
    installed: str | None,
    latest: str | None,
    findings: list[notes.Finding],
    url: str | None,
    **extra: Any,
) -> dict[str, Any]:
    # Things to act on first, general notes last.
    findings.sort(key=lambda f: (not f.severe, f.general, not f.used_in))
    return {
        "kind": kind,
        "name": name,
        "entity_id": entity_id,
        "installed": installed,
        "latest": latest,
        "level": notes.level_of(findings),
        "release_url": url,
        "findings": [f.as_dict() for f in findings[:MAX_FINDINGS]],
        **extra,
    }


def _line(finding: dict[str, Any], language: str) -> str:
    """One finding as a markdown bullet for the repair, in the user's language."""
    labels = LABELS.get(language.split("-")[0], LABELS["en"])
    prefix = labels.get(finding["source"], "")
    title = finding["title"]
    head = " ".join(p for p in (prefix, f"**{title}**" if title else "") if p)
    line = f"- {head} {finding['text']}" if head else f"- {finding['text']}"
    if finding["used_in"]:
        places = [labels.get(kind, kind) + ":" + name for kind, name in (u.split(":", 1) for u in finding["used_in"])]
        line += f"\n  {labels['used_in']}: " + ", ".join(places)
    return line


def _is_app(entry: er.RegistryEntry | None) -> bool:
    """Supervisor apps (add-ons), not the OS or Supervisor itself."""
    return bool(entry and entry.unique_id and not entry.unique_id.startswith(("home_assistant_", "supervisor")))


def _used_domains(hass: HomeAssistant) -> set[str]:
    """Integrations that are loaded, incl. platforms like sensor.template."""
    return {part for component in hass.config.components for part in component.split(".")}
