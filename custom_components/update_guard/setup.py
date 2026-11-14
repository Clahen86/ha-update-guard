"""How Update Guard is used, for the developer (sent with the daily question when sharing is on - see support.py):
which kinds of updates it watches (by integration), what it found, what was installed, refused and rolled back.
Never names, versions of single items or entity IDs."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import entity_registry as er

from .const import CONF_AI, CONF_AUTO_SAFE, CONF_BLOCKERS, CONF_NOTIFY, CONF_WAIT_FIX


def setup_info(coordinator: Any) -> dict[str, Any]:
    hass = coordinator.hass
    reg = er.async_get(hass)
    data = coordinator.data if isinstance(coordinator.data, dict) else {}
    updates = data.get("updates") or []
    groups: dict[str, dict[str, Any]] = {}
    for u in updates:
        ent = reg.async_get(u["entity_id"]) if u.get("entity_id") else None
        plat = (ent.platform if ent else None) or str(u.get("kind") or "other")
        g = groups.setdefault(plat, {"kind": "update", "platform": plat, "extra": {"pending": 0}})
        g["extra"]["pending"] += 1
        lvl = str(u.get("level") or "none")
        g["extra"][lvl] = int(g["extra"].get(lvl) or 0) + 1
        if u.get("notes_missing"):
            g["extra"]["no_notes"] = int(g["extra"].get("no_notes") or 0) + 1
    watched = [s.entity_id for s in hass.states.async_all("update")]
    for e in watched:
        ent = reg.async_get(e)
        plat = ent.platform if ent else "?"
        g = groups.setdefault(plat, {"kind": "update", "platform": plat, "extra": {"pending": 0}})
        g["extra"]["watched"] = int(g["extra"].get("watched") or 0) + 1
    st = getattr(coordinator.after, "stats", {}) or {}
    flat = lambda v: sum(v.values()) if isinstance(v, dict) else int(v or 0)  # noqa: E731
    for kind, n in (st.get("installed") or {}).items():
        g = groups.setdefault(f"kind:{kind}", {"kind": "update", "platform": f"kind:{kind}", "extra": {}})
        g["extra"]["installed"] = n
        g["extra"]["rolled_back"] = (st.get("rolled_back") or {}).get(kind, 0)
        g["ok"] = not (st.get("rolled_back") or {}).get(kind)
    o = coordinator.config_entry.options
    return {
        "devices": sorted(groups.values(), key=lambda g: -(g["extra"].get("watched") or 0))[:30],
        "counts": {"watched": len(watched), "pending": len(updates), "installed": flat(st.get("installed")),
                   "refused": flat(st.get("refused")), "rolled_back": flat(st.get("rolled_back")),
                   "backups": flat(st.get("backups")), "broken_after": flat(st.get("broken"))},
        "features": {"ai": bool(o.get(CONF_AI)), "notify": bool(o.get(CONF_NOTIFY)), "wait_for_fix": bool(o.get(CONF_WAIT_FIX)),
                     "auto_safe": bool(o.get(CONF_AUTO_SAFE)), "blockers": bool(o.get(CONF_BLOCKERS))},
    }
