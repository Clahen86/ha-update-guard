"""Update safely, and go back again.

Safe update: refuses what Update Guard says to wait with (unless forced), checks free disk space, waits while
the things you chose are running (a washing machine, the car charging), and only takes a backup when the last
automatic backup doesn't already cover it. The check after the update then runs as usual.

Going back: an update entity that can install a given version gets the old version again (HACS can). An app goes
back by restoring the backup the Supervisor took of it before the update. Home Assistant itself is never rolled
back automatically - that needs a full restore, which you start yourself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.const import ATTR_SUPPORTED_FEATURES, STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_AUTO_SAFE, CONF_BLOCKERS, DOMAIN, KIND_APP, KIND_CORE, LEVEL_SAFE, LEVEL_WAIT, NOTIFY_TEXT

if TYPE_CHECKING:
    from .coordinator import UpdateGuardCoordinator

_LOGGER = logging.getLogger(__name__)
# A backup this new already covers an update (you take one every night).
BACKUP_FRESH = timedelta(hours=26)
MIN_FREE_GB = 2.0
# How long to keep waiting for the blocking devices before giving up.
WAIT_STEP = 600
WAIT_MAX = 6 * 3600
NIGHT_HOUR = 4
# States that mean "busy" for a blocker that isn't a simple on/off.
# A power or current sensor as a blocker: running from this many watts (a machine on standby draws a little).
BUSY_W = 10.0
_IDLE = {STATE_OFF, "idle", "standby", "off", "not_charging", "disconnected", "ready", "unavailable", "unknown"}


class UpdateRefused(HomeAssistantError):
    """Translated reason why Update Guard didn't install."""

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders)
        self.key = key


class Installer:
    """Installs updates the safe way, now or tonight."""

    def __init__(self, hass: HomeAssistant, coordinator: UpdateGuardCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        # entity_id -> cancel function of a planned install.
        self.planned: dict[str, CALLBACK_TYPE] = {}
        # The plans themselves, kept over a restart: entity_id -> {at, force, auto, since, version}.
        self.plans: dict[str, dict[str, Any]] = {}
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.plans")

    async def async_load(self) -> None:
        """Plans made before a restart are made again (one whose time has passed runs in a minute)."""
        data = await self.store.async_load() or {}
        soon = dt_util.utcnow() + timedelta(minutes=1)
        for entity_id, plan in (data.get("plans") or {}).items():
            at = dt_util.parse_datetime(plan.get("at") or "") or soon
            since = dt_util.parse_datetime(plan["since"]) if plan.get("since") else None
            self._plan(entity_id, max(at, soon), bool(plan.get("force")), since, bool(plan.get("auto")), plan.get("version"))

    def _save(self) -> None:
        self.store.async_delay_save(lambda: {"plans": self.plans}, 5)

    @callback
    def async_stop(self) -> None:
        for cancel in self.planned.values():
            cancel()
        self.planned.clear()

    def _text(self, key: str) -> str:
        return NOTIFY_TEXT.get(self.hass.config.language.split("-")[0], NOTIFY_TEXT["en"])[key]

    def _tell(self, key: str, **values: str) -> None:
        """What happened to a planned or started install - not only in the log."""
        from homeassistant.components import persistent_notification

        persistent_notification.async_create(
            self.hass, self._text(key).format(**values), title="Update Guard", notification_id=f"{DOMAIN}_{values.get('id', key)}"
        )

    def _update(self, entity_id: str) -> dict[str, Any]:
        for update in (self.coordinator.data or {}).get("updates", []):
            if update["entity_id"] == entity_id:
                return update
        raise UpdateRefused("not_pending", entity_id=entity_id)

    async def async_safe_update(
        self, entity_id: str, when: str = "now", force: bool = False, auto: bool = False, update: dict[str, Any] | None = None
    ) -> str:
        """Install one update the safe way. Returns what was done: installed or planned.

        auto: planned by Update Guard itself (safe cards and themes) - then it must still be safe when the time comes.
        update: the update itself, from a check that isn't saved yet (the night plan is made during the check)."""
        update = update or self._update(entity_id)
        if update["level"] == LEVEL_WAIT and not force:
            self.coordinator.after.count("refused", "is_wait")
            raise UpdateRefused("is_wait", name=update["name"], verdict=update.get("verdict", ""))
        if when == "tonight":
            self._plan(entity_id, _tonight(), force, auto=auto, version=update["latest"])
            return "planned"
        if busy := self.busy():
            self._plan(entity_id, dt_util.utcnow() + timedelta(seconds=WAIT_STEP), force, dt_util.utcnow())
            _LOGGER.info("Waiting with %s while %s is running", update["name"], ", ".join(busy))
            return "waiting"
        await self._install(update)
        return "installed"

    def busy(self) -> list[str]:
        """The chosen devices that are running right now."""
        names = []
        for entity_id in self.coordinator.config_entry.options.get(CONF_BLOCKERS) or []:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            on = state.state == STATE_ON if state.domain in ("binary_sensor", "switch", "input_boolean") else (
                _running(state) if _number(state.state) is not None else state.state.lower() not in _IDLE
            )
            if on:
                names.append(state.attributes.get("friendly_name") or entity_id)
        return names

    @callback
    def _plan(
        self, entity_id: str, at: datetime, force: bool, since: datetime | None = None, auto: bool = False,
        version: str | None = None,
    ) -> None:
        if cancel := self.planned.pop(entity_id, None):
            cancel()
        self.plans[entity_id] = {"at": at.isoformat(), "force": force, "auto": auto, "version": version,
                                 "since": since.isoformat() if since else None}
        self._save()

        async def _run(_now: datetime) -> None:
            self.planned.pop(entity_id, None)
            self.plans.pop(entity_id, None)
            self._save()
            try:
                update = self._update(entity_id)
            except UpdateRefused:
                return  # installed in the meantime
            name = update["name"]
            if update["level"] == LEVEL_WAIT and not force:
                _LOGGER.info("Not installing %s: it is now marked to wait", name)
                self._tell("plan_wait", name=name, id=entity_id)
                return
            if auto and (
                update["level"] != LEVEL_SAFE
                or not self.coordinator.config_entry.options.get(CONF_AUTO_SAFE)
                or (version and update["latest"] != version)
            ):
                # Planned by Update Guard itself: only what is still safe, still switched on, and the same version.
                _LOGGER.info("Not installing %s tonight: it is no longer the safe update that was planned", name)
                return
            if self.busy():
                start = since or dt_util.utcnow()
                if (dt_util.utcnow() - start).total_seconds() < WAIT_MAX:
                    self._plan(entity_id, dt_util.utcnow() + timedelta(seconds=WAIT_STEP), force, start, auto, version)
                else:
                    _LOGGER.warning("Gave up installing %s: %s kept running", name, ", ".join(self.busy()))
                    self._tell("plan_busy", name=name, busy=", ".join(self.busy()), id=entity_id)
                return
            try:
                await self._install(update)
            except HomeAssistantError as err:
                _LOGGER.warning("Planned update of %s failed: %s", name, err)
                self._tell("install_failed", name=name, error=str(err), id=entity_id)

        self.planned[entity_id] = async_track_point_in_time(self.hass, _run, at)

    @callback
    def cancel_auto(self) -> None:
        """Automatic installs switched off: the plans Update Guard made itself go too."""
        for entity_id in [e for e, p in self.plans.items() if p.get("auto")]:
            if cancel := self.planned.pop(entity_id, None):
                cancel()
            self.plans.pop(entity_id, None)
        self._save()

    def planned_for(self) -> list[str]:
        return sorted(self.planned)

    async def _install(self, update: dict[str, Any]) -> None:
        free = disk_free(self.hass)
        if free is not None and free < MIN_FREE_GB:
            self.coordinator.after.count("refused", "disk")
            raise UpdateRefused("disk", free=f"{free:.1f}")
        entity_id = update["entity_id"]
        if entity_id is None:
            raise UpdateRefused("no_entity", name=update["name"])
        state = self.hass.states.get(entity_id)
        if state is not None and state.attributes.get("in_progress"):
            raise UpdateRefused("in_progress", name=update["name"])  # Home Assistant is installing it already
        data: dict[str, Any] = {"entity_id": entity_id}
        if self.backup_needed(update) and _supports(self.hass, entity_id, UpdateEntityFeature.BACKUP):
            data["backup"] = True
        _LOGGER.info("Installing %s %s (backup: %s)", update["name"], update["latest"], data.get("backup", False))
        # Runs on behind the button (an update can take many minutes), but its end is followed: a failed backup or
        # update is told, not only logged. The check after the update starts by itself when the new version shows up.
        self.hass.async_create_background_task(self._async_run(update, data), f"{DOMAIN} install {entity_id}")

    async def _async_run(self, update: dict[str, Any], data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call("update", "install", data, blocking=True)
        except Exception as err:  # noqa: BLE001 - the backup or the update failed
            _LOGGER.warning("Installing %s failed: %s", update["name"], err)
            self.coordinator.after.count("failed", update["kind"])
            self._tell("install_failed", name=update["name"], error=str(err) or type(err).__name__, id=data["entity_id"])
            return
        self.coordinator.after.count("installed", update["kind"])
        if data.get("backup"):
            self.coordinator.after.count("backups")

    def backup_needed(self, update: dict[str, Any]) -> bool:
        """A backup only when the last automatic one doesn't cover this update."""
        if update["kind"] not in (KIND_CORE, KIND_APP):
            return False  # a card or integration goes back by installing the old version
        last = last_backup(self.hass)
        if last is None or dt_util.utcnow() - last > BACKUP_FRESH:
            return True
        # An app: only when the automatic backup takes it (all apps, or this one) - else it has its own first.
        return update["kind"] == KIND_APP and not backs_up_app(self.hass, update.get("slug"))

    async def async_rollback(self, entity_id: str, version: str, kind: str, slug: str | None = None) -> None:
        """Go back to the version before the update."""
        if _supports(self.hass, entity_id, UpdateEntityFeature.SPECIFIC_VERSION):
            await self.hass.services.async_call(
                "update", "install", {"entity_id": entity_id, "version": version}, blocking=True
            )
            self.coordinator.after.count("rolled_back", kind)
            return
        if kind == KIND_APP and slug and (backup := await app_backup(self.hass, slug, version)):
            await self.hass.services.async_call(
                "hassio", "restore_partial", {"slug": backup, "addons": [slug]}, blocking=True
            )
            self.coordinator.after.count("rolled_back", kind)
            return
        raise UpdateRefused("no_rollback")


def can_roll_back(hass: HomeAssistant, entity_id: str | None, kind: str) -> bool:
    if not entity_id:
        return False
    return kind == KIND_APP or _supports(hass, entity_id, UpdateEntityFeature.SPECIFIC_VERSION)


def app_slug(hass: HomeAssistant, entity_id: str) -> str | None:
    entry = er.async_get(hass).async_get(entity_id)
    return entry.unique_id.removesuffix("_version_latest") if entry and entry.platform == "hassio" else None


async def app_backup(hass: HomeAssistant, slug: str, version: str) -> str | None:
    """The newest backup with the app at the old version (the Supervisor makes one before an app update)."""
    try:
        from homeassistant.components.hassio import get_supervisor_client

        client = get_supervisor_client(hass)
        backups = sorted(await client.backups.list(), key=lambda b: b.date, reverse=True)
        for backup in backups:
            if slug not in backup.content.addons:
                continue
            info = await client.backups.backup_info(backup.slug)
            if any(a.slug == slug and a.version == version for a in info.addons):
                return backup.slug
    except Exception:  # noqa: BLE001 - no Supervisor or no backups
        _LOGGER.debug("No backup of %s %s found", slug, version, exc_info=True)
    return None


def last_backup(hass: HomeAssistant) -> datetime | None:
    """When the last automatic backup finished, if it is the last one that was tried (i.e. it didn't fail)."""
    try:
        from homeassistant.components.backup import async_get_manager

        data = async_get_manager(hass).config.data
    except Exception:  # noqa: BLE001 - backups not set up
        return None
    done, tried = data.last_completed_automatic_backup, data.last_attempted_automatic_backup
    if done is None or (tried is not None and tried > done):
        return None  # never, or the last one failed
    return done


def backs_up_app(hass: HomeAssistant, slug: str | None) -> bool:
    """The automatic backup takes this app: all apps, or this one by name."""
    try:
        from homeassistant.components.backup import async_get_manager

        create = async_get_manager(hass).config.data.create_backup
    except Exception:  # noqa: BLE001 - backups not set up
        return False
    return bool(create.include_all_addons or (slug and slug in (create.include_addons or [])))


def _number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _running(state: Any) -> bool:
    """A power (W/kW) or current sensor reads as running above a little standby use."""
    value = _number(state.state) or 0.0
    unit = str(state.attributes.get("unit_of_measurement") or "").lower()
    watts = value * 1000 if unit == "kw" else value * 230 if unit == "a" else value
    return watts >= BUSY_W


def disk_free(hass: HomeAssistant) -> float | None:
    """Free disk space in GB (Home Assistant OS / Supervised only)."""
    if "hassio" not in hass.config.components:
        return None
    try:
        from homeassistant.components.hassio import get_host_info

        return float(get_host_info(hass).get("disk_free"))
    except Exception:  # noqa: BLE001
        return None


def _supports(hass: HomeAssistant, entity_id: str, feature: UpdateEntityFeature) -> bool:
    state = hass.states.get(entity_id)
    return bool(state and int(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)) & feature)


def _tonight() -> datetime:
    now = dt_util.now()
    at = now.replace(hour=NIGHT_HOUR, minute=30, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)

