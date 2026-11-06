"""What GitHub knows: releases you skip, and what other people report after an update.

Without a token GitHub allows 60 calls an hour (10 a minute for search), shared with everything else on your
network, so every answer is kept for hours and a refused call just means "nothing known".
"""

from __future__ import annotations

from datetime import datetime
import logging
import re
import time
from typing import Any

import aiohttp
from awesomeversion import AwesomeVersion, AwesomeVersionException

from .const import USER_AGENT

_LOGGER = logging.getLogger(__name__)
API = "https://api.github.com"
_TIMEOUT = aiohttp.ClientTimeout(total=30)
KEEP = 6 * 3600
# Search queries may be at most 256 characters.
_QUERY_MAX = 250
GITHUB_URL = re.compile(r"github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?(?:/|$)")


def version(text: str | None) -> AwesomeVersion | None:
    try:
        v = AwesomeVersion(str(text or "").strip().lstrip("vV"))
        return v if v.valid else None
    except AwesomeVersionException:
        return None


class GitHub:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self._cache: dict[str, tuple[float, Any]] = {}
        # Rate limited until this time: don't ask before.
        self._blocked_until = 0.0

    async def _get(self, path: str, params: dict[str, str] | None = None, keep: float = KEEP) -> Any:
        key = path + repr(sorted((params or {}).items()))
        if (hit := self._cache.get(key)) and time.time() - hit[0] < keep:
            return hit[1]
        if time.time() < self._blocked_until:
            return hit[1] if hit else None
        data = None
        try:
            async with self.session.get(
                API + path,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (403, 429):
                    reset = resp.headers.get("X-RateLimit-Reset")
                    self._blocked_until = float(reset) if reset and reset.isdigit() else time.time() + 900
                    _LOGGER.debug("GitHub rate limit, waiting until %s", self._blocked_until)
                    return hit[1] if hit else None
                if resp.status == 200:
                    data = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("GitHub %s failed: %s", path, err)
            return hit[1] if hit else None
        self._cache[key] = (time.time(), data)
        return data

    def known(self, owner: str, repo: str) -> bool:
        """repo_info has a fresh answer, so asking costs nothing."""
        hit = self._cache.get(f"/repos/{owner}/{repo}" + repr([]))
        return bool(hit and time.time() - hit[0] < 24 * 3600)

    async def repo_info(self, owner: str, repo: str) -> dict[str, Any] | None:
        """archived and pushed_at of a repository, asked about once a day."""
        data = await self._get(f"/repos/{owner}/{repo}", keep=24 * 3600)
        return data if isinstance(data, dict) else None

    async def releases(self, owner: str, repo: str) -> list[dict[str, Any]]:
        data = await self._get(f"/repos/{owner}/{repo}/releases", {"per_page": "40"})
        return [r for r in data or [] if isinstance(r, dict) and not r.get("draft")]

    async def skipped_notes(self, owner: str, repo: str, installed: str, latest: str) -> tuple[str, list[str]]:
        """Release notes of every version after the installed one, up to the latest. (text, versions)"""
        low, high = version(installed), version(latest)
        if low is None or high is None:
            return "", []
        parts, tags = [], []
        for release in await self.releases(owner, repo):
            v = version(release.get("tag_name"))
            if v is None or not low < v <= high or (release.get("prerelease") and v != high):
                continue
            tags.append(release["tag_name"])
            parts.append(f"## {release['tag_name']}\n{release.get('body') or ''}")
        return "\n\n".join(parts), tags

    async def published(self, owner: str, repo: str, tag: str) -> datetime | None:
        for release in await self.releases(owner, repo):
            if release.get("tag_name") == tag and release.get("published_at"):
                return _date(release["published_at"])
        data = await self._get(f"/repos/{owner}/{repo}/releases/tags/{tag}")
        return _date((data or {}).get("published_at"))

    async def reports(self, owner: str, repo: str, tag: str) -> dict[str, Any] | None:
        """Issues opened since the release that name its version: other people having trouble with it."""
        since = await self.published(owner, repo, tag)
        if since is None:
            return None
        plain = tag.lstrip("vV")
        query = f'repo:{owner}/{repo} is:issue "{plain}" created:>={since.date().isoformat()}'
        data = await self._get("/search/issues", {"q": query, "per_page": "5", "sort": "created"})
        if data is None:
            return None
        items = [i for i in data.get("items", []) if "pull_request" not in i]
        return {
            "count": int(data.get("total_count", 0)),
            "titles": [i.get("title", "") for i in items[:3]],
            "url": f"https://github.com/{owner}/{repo}/issues?q=is%3Aissue+{plain}",
        }

    async def mentions(self, repos: list[tuple[str, str]], words: str, since: datetime) -> dict[str, int]:
        """Issues opened since a date in any of the repositories that name the words. {"owner/repo": count}"""
        counts: dict[str, int] = {}
        base = f'is:issue "{words}" created:>={since.date().isoformat()}'
        chunk: list[str] = []

        async def ask(names: list[str]) -> None:
            data = await self._get("/search/issues", {"q": base + " " + " ".join(names), "per_page": "100"})
            for item in (data or {}).get("items", []):
                if "pull_request" in item:
                    continue
                name = "/".join(item.get("repository_url", "").split("/")[-2:])
                counts[name.lower()] = counts.get(name.lower(), 0) + 1

        for owner, repo in repos:
            name = f"repo:{owner}/{repo}"
            if chunk and len(base) + len(" ".join([*chunk, name])) > _QUERY_MAX:
                await ask(chunk)
                chunk = []
            chunk.append(name)
        if chunk:
            await ask(chunk)
        return counts


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
