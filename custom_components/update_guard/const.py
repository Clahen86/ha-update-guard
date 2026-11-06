"""Constants for Update Guard."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "update_guard"
SCAN_INTERVAL = timedelta(hours=6)

# Overall assessment, worst first.
LEVEL_WAIT = "wait"
LEVEL_CHECK = "check"
# No release notes could be read, so nothing is known. Never shown as safe.
LEVEL_UNKNOWN = "unknown"
LEVEL_SAFE = "safe"
LEVEL_NONE = "none"
LEVELS = [LEVEL_WAIT, LEVEL_CHECK, LEVEL_UNKNOWN, LEVEL_SAFE, LEVEL_NONE]

KIND_CORE = "core"
KIND_APP = "app"
KIND_HACS = "hacs"
KIND_OTHER = "other"

GITHUB_RELEASE_TAG = "https://api.github.com/repos/home-assistant/core/releases/tags/{tag}"
GITHUB_RELEASE_LATEST = "https://api.github.com/repos/home-assistant/core/releases/latest"
RAW_POST = "https://raw.githubusercontent.com/home-assistant/home-assistant.io/current/source/_posts/{slug}.markdown"
HACS_JSON = "https://raw.githubusercontent.com/{owner}/{repo}/{tag}/hacs.json"
USER_AGENT = "HomeAssistant-UpdateGuard"

# Keep state attributes small; the full text is in the release notes.
MAX_TEXT = 400
MAX_FINDINGS = 12

# Words inside repair texts that are built in code. Everything else is in translations/.
LABELS = {
    "en": {
        "log": "Warning in the log:",
        "repair": "Repair:",
        "hacs": "Needs",
        "option": "Your option",
        "used_in": "Used in",
        "automation": "Automation",
        "script": "Script",
        "dashboard": "Dashboard",
        "after_related": "Stopped working:",
        "after_other": "At the same time, maybe a coincidence:",
        "after_entry": "Integration could not start:",
        "after_errors": "New errors in the log:",
    },
    "da": {
        "log": "Advarsel i loggen:",
        "repair": "Reparation:",
        "hacs": "Kræver",
        "option": "Din indstilling",
        "used_in": "Bruges i",
        "automation": "Automatisering",
        "script": "Script",
        "dashboard": "Dashboard",
        "after_related": "Virker ikke længere:",
        "after_other": "Samtidig, måske tilfældigt:",
        "after_entry": "Integration kunne ikke starte:",
        "after_errors": "Nye fejl i loggen:",
    },
}

# Optional AI Task entity that double-checks lines found by keywords.
CONF_AI = "ai_task"
CONF_NOTIFY = "notify"
CONF_NOTIFY_LEVEL = "notify_level"
# What is announced: everything, everything that needs a look (incl. unknown), or only wait.
NOTIFY_ALL = "safe"
NOTIFY_LEVELS = ["safe", "check", "wait"]
NOTIFY_INCLUDES = {
    "safe": {LEVEL_WAIT, LEVEL_CHECK, LEVEL_UNKNOWN, LEVEL_SAFE},
    "check": {LEVEL_WAIT, LEVEL_CHECK, LEVEL_UNKNOWN},
    "wait": {LEVEL_WAIT},
}

# Notification texts (sent from code, so not in translations/).
NOTIFY_TEXT = {
    "en": {
        "wait": "Wait",
        "check": "Check first",
        "safe": "Safe",
        "unknown": "Unknown",
        "nothing": "Nothing in the release notes touches your setup.",
        "no_notes": "No release notes could be read. Check it yourself before you update.",
        "updates": "{n} updates",
        "used_in": "used in",
        "after_ok": "Everything still works after {names}",
        "after_broken": "After {names}: {n} stopped working",
        "v_wait": "Wait – {what}",
        "v_check": "Check first – {what}",
        "v_safe": "Update – nothing touches your system",
        "v_safe_n": "Update – {n} changes, none found in your system",
        "v_unknown": "Unknown – no release notes to read",
        "maybe": "maybe – not found in your system",
        "e_used": "used in {where}",
        "e_entity": "affects {where}",
        "e_yaml": "you set up {where} in YAML",
        "e_integration": "you use {where}",
        "e_option": "your option {where}",
        "e_ha": "Home Assistant itself warns",
    },
    "da": {
        "wait": "Vent",
        "check": "Tjek først",
        "safe": "Sikker",
        "unknown": "Ukendt",
        "nothing": "Intet i release notes rører din opsætning.",
        "no_notes": "Der var ingen release notes at læse. Tjek selv, før du opdaterer.",
        "updates": "{n} opdateringer",
        "used_in": "bruges i",
        "after_ok": "Alt virker stadig efter {names}",
        "after_broken": "Efter {names}: {n} virker ikke",
        "v_wait": "Vent – {what}",
        "v_check": "Tjek først – {what}",
        "v_safe": "Opdatér – intet rammer dit system",
        "v_safe_n": "Opdatér – {n} ændringer, ingen fundet i dit system",
        "v_unknown": "Ukendt – ingen release notes at læse",
        "maybe": "måske – ikke fundet i dit system",
        "e_used": "bruges i {where}",
        "e_entity": "rammer {where}",
        "e_yaml": "du har {where} i YAML",
        "e_integration": "du bruger {where}",
        "e_option": "din indstilling {where}",
        "e_ha": "Home Assistant advarer selv",
    },
}
