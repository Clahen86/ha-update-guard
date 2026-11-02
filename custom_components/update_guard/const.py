"""Constants for Update Guard."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "update_guard"
SCAN_INTERVAL = timedelta(hours=6)

# Overall assessment, worst first.
LEVEL_WAIT = "wait"
LEVEL_CHECK = "check"
LEVEL_SAFE = "safe"
LEVEL_NONE = "none"
LEVELS = [LEVEL_WAIT, LEVEL_CHECK, LEVEL_SAFE, LEVEL_NONE]

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
    },
}

CONF_NOTIFY = "notify"
CONF_NOTIFY_LEVEL = "notify_level"
# Lowest verdict that is announced: everything, or only check/wait, or only wait.
NOTIFY_ALL = "safe"
NOTIFY_LEVELS = ["safe", "check", "wait"]

# Notification texts (sent from code, so not in translations/).
NOTIFY_TEXT = {
    "en": {
        "wait": "Wait",
        "check": "Check first",
        "safe": "Safe",
        "nothing": "Nothing in the release notes touches your setup.",
        "updates": "{n} updates",
        "used_in": "used in",
    },
    "da": {
        "wait": "Vent",
        "check": "Tjek først",
        "safe": "Sikker",
        "nothing": "Intet i release notes rører din opsætning.",
        "updates": "{n} opdateringer",
        "used_in": "bruges i",
    },
}
