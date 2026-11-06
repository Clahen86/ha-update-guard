"""Optional AI check of keyword findings: is a changelog line really something you have to act on?

Only lines found by keywords (changelog and app/HACS options) are sent, never Core notes, log warnings or repairs.
Each update version is asked about once; the answer is kept across restarts.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import sys
import time
from typing import Any

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store

from . import notes
from .const import DOMAIN, LEVEL_CHECK, LEVEL_SAFE, LEVEL_UNKNOWN, LEVEL_WAIT

_LOGGER = logging.getLogger(__name__)
# Findings that come from a keyword search. Core notes are matched on integrations, the rest are facts.
_SOURCES = {"changelog", "option"}
_RETRY_AFTER = 3600
_TIMEOUT = 120
_LANGUAGES = {"da": "Danish", "en": "English", "de": "German", "sv": "Swedish", "nb": "Norwegian", "nl": "Dutch"}


class AiReview:
    """Asks an AI Task entity which flagged lines matter, and remembers the answers."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.ai")
        # "entity_id@version" -> finding text -> {"relevant", "severe", "reason"}
        self.answers: dict[str, dict[str, dict[str, Any]]] = {}
        self._failed: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        self.answers = (await self.store.async_load() or {}).get("answers", {})

    async def async_review(self, entity_id: str, updates: list[dict[str, Any]]) -> None:
        """Check the flagged lines of every risky update and change its verdict in place."""
        pending = {_key(u) for u in updates}
        self.answers = {k: v for k, v in self.answers.items() if k in pending}
        for update in updates:
            lines = _candidates(update)
            if update["level"] not in (LEVEL_WAIT, LEVEL_CHECK) or not lines:
                continue
            key = _key(update)
            async with self._lock:
                if key not in self.answers and time.monotonic() - self._failed.get(key, -_RETRY_AFTER) >= _RETRY_AFTER:
                    if (answer := await self._ask(entity_id, update, lines)) is None:
                        self._failed[key] = time.monotonic()
                    else:
                        self.answers[key] = answer
                        self._failed.pop(key, None)
            if key in self.answers:
                _apply(update, self.answers[key])
        self.store.async_delay_save(lambda: {"answers": self.answers}, 5)

    async def _ask(self, entity_id: str, update: dict[str, Any], lines: list[dict[str, Any]]) -> dict | None:
        prompt = build_prompt(update, lines, self._facts(lines), self.hass.config.language)
        try:
            async with asyncio.timeout(_TIMEOUT):
                response = await self.hass.services.async_call(
                    "ai_task",
                    "generate_data",
                    {"entity_id": entity_id, "task_name": "Update Guard", "instructions": prompt},
                    blocking=True,
                    return_response=True,
                )
            verdicts = notes.parse_ai_answer((response or {}).get("data"), len(lines))
        except Exception as err:  # noqa: BLE001 - a broken AI must not stop the check
            _LOGGER.warning(
                "AI check of %s %s failed, using the normal verdict: %s", update["name"], update["latest"], err
            )
            return None
        return {line["text"]: verdicts[n] for n, line in enumerate(lines, 1) if n in verdicts}

    def _facts(self, lines: list[dict[str, Any]]) -> list[str]:
        """What the AI needs to know about you: versions, and only the integrations and devices the lines name."""
        text = " ".join(line["text"] for line in lines).lower()
        words = set(re.findall(r"[a-z0-9_]+", text.replace(" ", "_")) + re.findall(r"[a-z0-9_]+", text))
        integrations = sorted({c.split(".")[0] for c in self.hass.config.components} & words)
        devices = set()
        for device in dr.async_get(self.hass).devices.values():
            for model in (device.model, device.model_id):
                if model and len(model) >= 4 and model.lower() in text:
                    devices.add(f"{device.manufacturer or ''} {model}".strip())
        options = sorted({k for line in lines if line["source"] == "option" for k in line["keywords"]})
        used = sorted({u for line in lines for u in line["used_in"]})
        facts = [
            f"- Home Assistant {HA_VERSION} on {platform.machine()} (64-bit: {sys.maxsize > 2**32})",
            f"- Integrations named in the lines that the user has: {', '.join(integrations) or 'none'}",
            f"- The user's devices named in the lines: {', '.join(sorted(devices)) or 'none'}",
            f"- Options the user has set in it: {', '.join(options) or 'none of the ones mentioned'}",
        ]
        if used:
            facts.append(
                f"- Names from the lines used in the user's automations, scripts or dashboards: {', '.join(used)}"
            )
        return facts


def build_prompt(update: dict[str, Any], lines: list[dict[str, Any]], facts: list[str], language: str) -> str:
    """The question for the AI. Only names (options, devices, integrations) are sent, never values."""
    numbered = "\n".join(f"{n}. {line['text']}" for n, line in enumerate(lines, 1))
    reply_in = _LANGUAGES.get(language.split("-")[0], language)
    return (
        f'You help a Home Assistant user decide if it is safe to update "{update["name"]}" '
        f"from {update['installed']} to {update['latest']}.\n"
        "A keyword search flagged the changelog lines below. For each line decide:\n"
        "- relevant: true if the user may have to do something or something they use may stop working, "
        "false if it is internal or developer work, a bug fix, a new feature, documentation, "
        "or about hardware, platforms, versions or devices the user does not have.\n"
        "- severe: true only if something the user uses is removed, renamed or stops working and they must act. "
        "Cosmetic changes (icons, names, colours) and future deprecations are not severe.\n"
        "- reason: at most 12 words, in " + reply_in + ".\n"
        "When unsure, say relevant.\n\n"
        "What is known about the user:\n" + "\n".join(facts) + "\n\n"
        f"Lines:\n{numbered}\n\n"
        'Answer only with JSON: {"lines": [{"n": 1, "relevant": true, "severe": false, "reason": "..."}]}'
    )


def _candidates(update: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in update["findings"] if f["source"] in _SOURCES and not f["general"]]


def _apply(update: dict[str, Any], answer: dict[str, dict[str, Any]]) -> None:
    """Move lines the AI found irrelevant to the general notes and work out the verdict again."""
    for finding in update["findings"]:
        if finding["source"] not in _SOURCES or (verdict := answer.get(finding["text"])) is None:
            continue
        finding["ai"] = verdict["reason"]
        finding["severe"] = verdict["relevant"] and verdict["severe"]
        finding["general"] = not verdict["relevant"]
        if finding["general"]:
            finding["affects"] = "no"
    update["findings"].sort(key=notes.sort_key)
    level = notes.level_of([notes.Finding(**f) for f in update["findings"]])
    update["level"] = LEVEL_UNKNOWN if level == LEVEL_SAFE and update["notes_missing"] else level
    update["ai_checked"] = True


def _key(update: dict[str, Any]) -> str:
    return f"{update['entity_id'] or 'core'}@{update['latest']}"
