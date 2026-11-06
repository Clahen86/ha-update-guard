"""Collect pending updates and assess them."""

from __future__ import annotations

from datetime import timedelta
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
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_filtered, TrackStates
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import notes, usage
from .after import AfterCheck
from .ai import AiReview
from .github import GITHUB_URL, GitHub
from .install import Installer, disk_free, MIN_FREE_GB
from .notifier import NOTIFY_TEXT, Notifier, reason, verdict
from .const import (
    CONF_AI,
    CONF_AUTO_SAFE,
    CONF_WAIT_FIX,
    DEAD_DAYS,
    REPORTS_MIN,
    STORE_PLATFORMS,
    WAIT_FIX_DAYS,
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
    LEVEL_SAFE,
    LEVEL_UNKNOWN,
    LEVEL_WAIT,
    LEVELS,
    MAX_FINDINGS,
    RAW_POST,
    SCAN_INTERVAL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)
DEAD_PER_CHECK = 8
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
        self._yaml: set[str] | None = None
        self._post_text: dict[tuple[int, int], str] = {}
        self.notifier = Notifier(hass)
        self.ai = AiReview(hass)
        self.after = AfterCheck(hass, self)
        self.github = GitHub(self.session)
        self.installer = Installer(hass, self)

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
                or (old.attributes.get("installed_version") != new.attributes.get("installed_version"))
            ):
                self.hass.async_create_task(self.async_request_refresh())

        tracker = async_track_state_change_filtered(self.hass, TrackStates(False, set(), {UPDATE_DOMAIN}), _changed)
        self.config_entry.async_on_unload(tracker.async_remove)

    async def _async_update_data(self) -> dict[str, Any]:
        self.after.async_scan()
        registry = er.async_get(self.hass)
        self._index = await usage.config_index(self.hass)
        self._yaml = await usage.yaml_domains(self.hass)
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
                KIND_APP
                if platform == "hassio" and _is_app(entry)
                else KIND_HACS
                if platform in STORE_PLATFORMS
                else KIND_OTHER
            )
            updates.append(await self._other(state, kind, entry))

        # Docker/Core installs have no core update entity: ask GitHub instead.
        if not core_seen and (latest := await self._latest_core()) and notes.months_between(HA_VERSION, latest):
            updates.append(await self._core(HA_VERSION, latest, None))

        if ai_entity := self.config_entry.options.get(CONF_AI):
            await self.ai.async_review(ai_entity, updates)

        for update in updates:
            update["verdict"] = verdict(update, self.hass.config.language)
        # Within a level: Home Assistant first, then security fixes.
        updates.sort(
            key=lambda u: (LEVELS.index(u["level"]), u["kind"] != KIND_CORE, not u.get("security"), u["name"].lower())
        )
        level = _overall(updates)
        dead = await self._dead_projects()
        await self._auto_install(updates)
        self._sync_issues(updates)
        await self.notifier.async_notify(updates, dict(self.config_entry.options))
        return {
            "level": level,
            "updates": updates,
            # General notes (not tied to an integration) are listed but not counted.
            "findings": sum(1 for u in updates for f in u["findings"] if f.get("affects") != "no"),
            "checked": dt_util.utcnow().isoformat(),
            "dead": dead,
            "disk_free": disk_free(self.hass),
            "planned": self.installer.planned_for(),
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
        news: list[str] = []
        for year, month in notes.months_between(installed, latest or "")[-1:]:
            if post := self._post_text.get((year, month)):
                news = notes.core_news(post, used - _PLATFORM_DOMAINS)
        if latest:
            # Things Home Assistant itself already warned about.
            findings.extend(self.deprecations.findings(installed, latest))
            findings.extend(await usage.repair_findings(self.hass, installed, latest))
            findings.extend(await self._core_extra(latest))
        usage.mark_usage(findings, self._index)
        usage.mark_entities(findings, usage.entity_terms(self.hass, {d for f in findings for d in f.domains}))
        for finding in findings:
            notes.judge(finding, self._yaml)
        return _result(
            KIND_CORE,
            _CORE_TITLE,
            entity_id,
            installed,
            latest,
            findings,
            url,
            notes_missing=bool(missing),
            ignored=ignored,
            missing=missing,
            news=news,
        )

    async def _other(self, state, kind: str, entry: er.RegistryEntry | None) -> dict[str, Any]:
        attrs = state.attributes
        latest = attrs.get("latest_version") or ""
        text = await self._changelog(state.entity_id, latest, attrs)
        repo = _repo(attrs.get("release_url"))
        skipped: list[str] = []
        if repo and attrs.get("installed_version"):
            # Several versions at once: read them all, not only the newest.
            every, skipped = await self.github.skipped_notes(*repo, attrs["installed_version"], latest)
            if len(skipped) > 1:
                text = every
        findings = notes.scan_changelog(text or "")
        if repo and (tag := _tag(attrs.get("release_url"))):
            findings.extend(self._report_findings(await self.github.reports(*repo, tag), tag))
        if kind == KIND_HACS and (needs := await self._hacs_needs(attrs.get("release_url"))):
            findings.insert(
                0,
                notes.Finding(title="", text=f"Home Assistant {needs}", severe=True, source="hacs", keywords=[]),
            )
        if text and (keys := await self._option_keys(kind, entry)):
            # Changes to options you have set go first; drop the same line found by keywords.
            options = notes.scan_options(text, keys)
            seen = {f.text for f in options}
            findings = options + [f for f in findings if f.text not in seen]
        usage.mark_usage(findings, self._index)
        terms = self._own_terms(kind, entry)
        usage.mark_entities(findings, terms)
        for finding in findings:
            notes.judge(finding)
        name = attrs.get("title") or attrs.get("friendly_name") or state.entity_id
        news_terms = {k for k in terms if "." not in k} | self._device_models(entry)
        return _result(
            kind,
            name,
            state.entity_id,
            attrs.get("installed_version"),
            latest,
            findings,
            attrs.get("release_url"),
            notes_missing=not notes.has_content(text),
            security=bool(notes.SECURITY.search(text or "")),
            skipped=skipped if len(skipped) > 1 else [],
            news=notes.scan_news(text or "", news_terms),
            category=self._category(entry),
        )

    async def _option_keys(self, kind: str, entry: er.RegistryEntry | None) -> set[str]:
        """Names of the options you have set in the app or HACS integration being updated."""
        if entry is None:
            return set()
        if kind == KIND_APP:
            return await self._app_options(entry.unique_id.removesuffix("_version_latest"))
        if kind == KIND_HACS and (domain := self._hacs_domain(entry.unique_id, entry)):
            keys: set[str] = set()
            for config_entry in self.hass.config_entries.async_entries(domain):
                keys |= notes.option_keys(dict(config_entry.data)) | notes.option_keys(dict(config_entry.options))
            return keys
        return set()

    def _report_findings(self, report: dict[str, Any] | None, version: str) -> list[notes.Finding]:
        """Other people's issues about this version."""
        if not report or report["count"] < REPORTS_MIN:
            return []
        text = self._text("f_reports").format(n=report["count"], version=version)
        if report["titles"]:
            text += ": " + " · ".join(f"“{t}”" for t in report["titles"][:2])
        return [notes.Finding(title="", text=notes.shorten(text, 250), source="reports", affects="maybe")]

    async def _core_extra(self, latest: str) -> list[notes.Finding]:
        """Wait for .1, free disk space, and HACS projects that people say break with this version."""
        found: list[notes.Finding] = []
        major = notes.parse_version(latest)
        published = await self.github.published("home-assistant", "core", latest)
        if (
            self.config_entry.options.get(CONF_WAIT_FIX)
            and major
            and latest.endswith(".0")
            and published
            and (dt_util.utcnow() - published).days < WAIT_FIX_DAYS
        ):
            until = dt_util.as_local(published + timedelta(days=WAIT_FIX_DAYS)).strftime("%d/%m")
            found.append(
                notes.Finding(
                    title="",
                    text=self._text("f_wait_fix").format(version=f"{major[0]}.{major[1]}", date=until),
                    source="policy",
                    affects="yes",
                    evidence=["policy:wait_for_fix"],
                )
            )
        if (free := disk_free(self.hass)) is not None and free < MIN_FREE_GB:
            found.append(
                notes.Finding(title="", text=self._text("f_disk").format(free=f"{free:.1f}"), severe=True,
                              source="policy", affects="yes", evidence=["policy:disk"])
            )
        if major and published:
            words = f"{major[0]}.{major[1]}"
            repos = [(r["owner"], r["repo"]) for r in self.store_repos() if r["category"] != "theme"]
            counts = await self.github.mentions(repos, words, published)
            for r in self.store_repos():
                if (n := counts.get(f"{r['owner']}/{r['repo']}".lower(), 0)) >= 1:
                    found.append(
                        notes.Finding(
                            title=r["name"],
                            text=self._text("f_compat").format(n=n, version=words),
                            source="reports",
                            affects="yes",
                            evidence=[f"entity:{r['entity_id']}"],
                        )
                    )
        return found

    def _text(self, key: str) -> str:
        return NOTIFY_TEXT.get(self.hass.config.language.split("-")[0], NOTIFY_TEXT["en"])[key]

    def store_repos(self) -> list[dict[str, Any]]:
        """Everything installed from HACS or the marketplace: name, GitHub repo and category."""
        registry, devices = er.async_get(self.hass), dr.async_get(self.hass)
        repos = []
        for entry in registry.entities.values():
            if entry.domain != UPDATE_DOMAIN or entry.platform not in STORE_PLATFORMS:
                continue
            state = self.hass.states.get(entry.entity_id)
            repo = _repo(state.attributes.get("release_url")) if state else None
            if repo is None:
                continue
            device = devices.async_get(entry.device_id) if entry.device_id else None
            repos.append({
                "entity_id": entry.entity_id,
                "name": (device and (device.name_by_user or device.name)) or state.name,
                "owner": repo[0],
                "repo": repo[1],
                "category": self._category(entry) or "",
            })
        return repos

    def _category(self, entry: er.RegistryEntry | None) -> str | None:
        """integration, plugin (card), theme ... - HACS keeps it as the device model."""
        if entry is None or entry.platform not in STORE_PLATFORMS or not entry.device_id:
            return None
        device = dr.async_get(self.hass).async_get(entry.device_id)
        return (device.model or "").lower() or None if device else None

    def _device_models(self, entry: er.RegistryEntry | None) -> set[str]:
        """Models of your devices from the integration (or the device) being updated."""
        if entry is None:
            return set()
        devices = dr.async_get(self.hass)
        if entry.platform not in STORE_PLATFORMS and entry.device_id and (device := devices.async_get(entry.device_id)):
            return {device.model} if device.model and len(device.model) >= 4 else set()
        domain = self._hacs_domain(entry.unique_id, entry) if entry.platform in STORE_PLATFORMS else None
        if not domain:
            return set()
        models = set()
        for config_entry in self.hass.config_entries.async_entries(domain):
            for device in dr.async_entries_for_config_entry(devices, config_entry.entry_id):
                if device.model and len(device.model) >= 4:
                    models.add(device.model)
        return models

    async def _dead_projects(self) -> list[dict[str, Any]]:
        """HACS projects that are archived or haven't changed for years. Asked about once a day."""
        dead = []
        asked = 0
        for r in self.store_repos():
            if not self.github.known(r["owner"], r["repo"]):
                # Spread the questions over several checks: GitHub allows 60 an hour without a token.
                if asked >= DEAD_PER_CHECK:
                    continue
                asked += 1
            info = await self.github.repo_info(r["owner"], r["repo"])
            if not info:
                continue
            pushed = info.get("pushed_at") or ""
            old = pushed[:4] if pushed and (dt_util.utcnow() - dt_util.parse_datetime(pushed)).days > DEAD_DAYS else ""
            if info.get("archived") or old:
                why = self._text("dead_archived") if info.get("archived") else self._text("dead_old").format(year=old)
                dead.append({"name": r["name"], "entity_id": r["entity_id"], "why": why,
                             "url": f"https://github.com/{r['owner']}/{r['repo']}"})
        return dead

    async def _auto_install(self, updates: list[dict[str, Any]]) -> None:
        """Safe cards and themes are installed tonight, when that is switched on."""
        if not self.config_entry.options.get(CONF_AUTO_SAFE):
            return
        for update in updates:
            if (
                update["level"] == LEVEL_SAFE
                and update["kind"] == KIND_HACS
                and update.get("category") in ("plugin", "theme")
                and update["entity_id"] not in self.installer.planned
            ):
                await self.installer.async_safe_update(update["entity_id"], "tonight")

    def _own_terms(self, kind: str, entry: er.RegistryEntry | None) -> dict[str, str]:
        """Entities of what is being updated: the HACS integration, or the device for firmware."""
        if entry is None:
            return {}
        if kind == KIND_HACS:
            domain = self._hacs_domain(entry.unique_id, entry)
            return usage.entity_terms(self.hass, {domain}) if domain else {}
        if kind == KIND_OTHER and entry.device_id:
            return usage.entity_terms(self.hass, device_id=entry.device_id)
        return {}

    def _hacs_domain(self, repository_id: str, entry: er.RegistryEntry | None = None) -> str | None:
        """Integration domain of a HACS (or marketplace) repository; None for cards, themes etc."""
        try:
            data = self.hass.data["hacs"].repositories.get_by_id(repository_id).data
            return data.domain if data.category == "integration" else None
        except (KeyError, AttributeError):
            pass
        # The marketplace: find the custom integration whose links point to the same GitHub repository.
        entry = entry or next(
            (e for e in er.async_get(self.hass).entities.values()
             if e.unique_id == repository_id and e.platform in STORE_PLATFORMS and e.domain == UPDATE_DOMAIN),
            None,
        )
        state = self.hass.states.get(entry.entity_id) if entry else None
        repo = _repo(state.attributes.get("release_url")) if state else None
        if repo is None or self._category(entry) not in (None, "integration"):
            return None
        return self._custom_domains().get(f"{repo[0]}/{repo[1]}".lower())

    def _custom_domains(self) -> dict[str, str]:
        """{"owner/repo": domain} for loaded custom integrations, from their documentation and issue links."""
        from homeassistant.loader import DATA_CUSTOM_COMPONENTS

        found: dict[str, str] = {}
        custom = self.hass.data.get(DATA_CUSTOM_COMPONENTS)
        for domain, integration in (custom if isinstance(custom, dict) else {}).items():
            for url in (integration.documentation, integration.issue_tracker):
                if repo := _repo(url):
                    found.setdefault(f"{repo[0]}/{repo[1]}".lower(), domain)
        return found

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
        self._post_text[(year, month)] = text
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
            lines = [_line(f, self.hass.config.language) for f in update["findings"] if f.get("affects") != "no"]
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
                    "findings": "\n".join([f"**{update['verdict']}**", "", *lines]),
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
    notes_missing: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    # Things to act on first, general notes last.
    findings.sort(key=notes.sort_key)
    level = notes.level_of(findings)
    if notes_missing and level == LEVEL_SAFE:
        # Nothing found because nothing could be read: that is not safe.
        level = LEVEL_UNKNOWN
    return {
        "kind": kind,
        "name": name,
        "entity_id": entity_id,
        "installed": installed,
        "latest": latest,
        "level": level,
        "notes_missing": notes_missing,
        "ai_checked": False,
        "release_url": url,
        "findings": [f.as_dict() for f in findings[:MAX_FINDINGS]],
        # Changes found that don't touch this system.
        "not_you": sum(f.affects == "no" and not f.general for f in findings) + extra.get("ignored", 0),
        **extra,
    }


def _line(finding: dict[str, Any], language: str) -> str:
    """One finding as a markdown bullet for the repair, in the user's language."""
    labels = LABELS.get(language.split("-")[0], LABELS["en"])
    prefix = labels.get(finding["source"], "")
    title = finding["title"]
    head = " ".join(p for p in (prefix, f"**{title}**" if title else "") if p)
    line = f"- {head} {finding['text']}" if head else f"- {finding['text']}"
    if not finding["used_in"]:
        line += f" _({reason(finding, NOTIFY_TEXT.get(language.split('-')[0], NOTIFY_TEXT['en']))})_"
    if finding["used_in"]:
        places = [labels.get(kind, kind) + ":" + name for kind, name in (u.split(":", 1) for u in finding["used_in"])]
        line += f"\n  {labels['used_in']}: " + ", ".join(places)
    if finding.get("ai"):
        line += f"\n  🤖 {finding['ai']}"
    return line


# Entity platforms: "sensor" is loaded everywhere, so news about it isn't news about you.
_PLATFORM_DOMAINS = {
    "sensor", "binary_sensor", "switch", "light", "cover", "climate", "fan", "button", "number", "select", "text",
    "update", "event", "image", "camera", "media_player", "lock", "scene", "script", "automation", "notify",
    "device_tracker", "weather", "calendar", "todo", "vacuum", "valve", "water_heater", "siren", "time", "date",
    "datetime", "homeassistant", "default_config", "frontend", "http", "config", "person", "zone", "sun",
}


def _overall(updates: list[dict[str, Any]]) -> str:
    """The worst level. Firmware without release notes (most of it) doesn't make everything Unknown."""
    counted = [
        u for u in updates
        if not (u["level"] == LEVEL_UNKNOWN and u["kind"] == KIND_OTHER and u.get("notes_missing"))
    ]
    if counted:
        return counted[0]["level"]
    return updates[0]["level"] if updates else LEVEL_NONE


def _repo(url: str | None) -> tuple[str, str] | None:
    match = GITHUB_URL.search(url or "")
    return (match[1], match[2]) if match else None


def _tag(url: str | None) -> str | None:
    match = _GITHUB_RELEASE.search(url or "")
    return match[3] if match else None


def _is_app(entry: er.RegistryEntry | None) -> bool:
    """Supervisor apps (add-ons), not the OS or Supervisor itself."""
    return bool(entry and entry.unique_id and not entry.unique_id.startswith(("home_assistant_", "supervisor")))


def _used_domains(hass: HomeAssistant) -> set[str]:
    """Integrations that are loaded, incl. platforms like sensor.template."""
    return {part for component in hass.config.components for part in component.split(".")}
