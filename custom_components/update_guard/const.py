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
KIND_OTHER = "other"

GITHUB_RELEASE_TAG = "https://api.github.com/repos/home-assistant/core/releases/tags/{tag}"
GITHUB_RELEASE_LATEST = "https://api.github.com/repos/home-assistant/core/releases/latest"
RAW_POST = "https://raw.githubusercontent.com/home-assistant/home-assistant.io/current/source/_posts/{slug}.markdown"
USER_AGENT = "HomeAssistant-UpdateGuard"

# Keep state attributes small; the full text is in the release notes.
MAX_TEXT = 400
MAX_FINDINGS = 12
