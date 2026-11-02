"""Parse release notes. Pure functions, no Home Assistant imports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re

from .const import LEVEL_CHECK, LEVEL_SAFE, LEVEL_WAIT, MAX_FINDINGS, MAX_TEXT

_SECTION = re.compile(r"^## Backward-incompatible changes\s*$(.*?)(?=^## |\Z)", re.M | re.S)
_DETAILS = re.compile(r'{%\s*details\s+"([^"]+)"\s*%}(.*?){%\s*enddetails\s*%}', re.S)
_INTEGRATION_LINK = re.compile(r"/integrations/([a-z0-9_]+)")
_LINK_DEF = re.compile(r"^\[[^\]]+\]:\s*\S+\s*$", re.M)
_CREDITS = re.compile(r"^\(\[@.*$", re.M)
_TERM = re.compile(r'{%\s*term\s+"?([^"%]+?)"?(?:\s+"([^"]+)")?\s*%}')
_LIQUID = re.compile(r"{%.*?%}", re.S)
_MD_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]|\[([^\]]+)\]\([^)]*\)")
_BLOG = re.compile(r"home-assistant\.io/blog/(\d{4})/(\d{2})/(\d{2})/([a-z0-9-]+)")
_VERSION = re.compile(r"^(\d{4})\.(\d{1,2})")
# `mqtt.publish`, `hours_priced_equal_or_lower`, `sensor.x_y`; plain words like `for` are too common.
_CODE = re.compile(r"`([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)`")

# The integration itself goes away or stops working: don't update yet.
_SEVERE = re.compile(
    r"integrations? (?:have|has) been (?:removed|disabled)|integrations? (?:was|were|is|are) (?:removed|disabled)|"
    r"no longer (?:works|starts?|available|supported|functional)|stopped working",
    re.I,
)
# Words that point at something you have to act on in an app/HACS/firmware changelog.
_KEYWORD = re.compile(
    r"breaking|⚠|backward[- ]incompatible|no longer|deprecat|\bremov(?:e|ed|es|al)\b|"
    r"\bmigrat|manual(?:ly)? (?:action|step)|must now|now requires?|requires? you",
    re.I,
)
_STRONG_KEYWORD = re.compile(r"breaking|⚠|backward[- ]incompatible", re.I)


@dataclass
class Finding:
    """One thing the user should look at."""

    title: str
    text: str
    domains: list[str] = field(default_factory=list)
    general: bool = False
    severe: bool = False
    # release, changelog, repair, log or hacs
    source: str = "release"
    # Names from the text (actions, options, sensors) to look for in your config.
    keywords: list[str] = field(default_factory=list)
    used_in: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def parse_version(version: str | None) -> tuple[int, int] | None:
    """Return (year, month) of a Home Assistant version like 2026.10.4 or 2026.11.0b2."""
    match = _VERSION.match(version or "")
    return (int(match[1]), int(match[2])) if match else None


def months_between(installed: str, latest: str) -> list[tuple[int, int]]:
    """Monthly releases after the installed one, up to and including the latest."""
    start, end = parse_version(installed), parse_version(latest)
    if not start or not end or end <= start:
        return []
    result = []
    year, month = start
    while (year, month) < end:
        month += 1
        if month > 12:
            year, month = year + 1, 1
        result.append((year, month))
    return result


def post_slug(release_body: str) -> tuple[str, str] | None:
    """(raw file slug, blog url) of the release post linked from a GitHub release."""
    match = _BLOG.search(release_body or "")
    if not match:
        return None
    y, m, d, name = match.groups()
    return f"{y}-{m}-{d}-{name}", f"https://www.home-assistant.io/blog/{y}/{m}/{d}/{name}/"


def clean(text: str) -> str:
    """Release post markdown to short plain text."""
    return shorten(plain(text))


def plain(text: str) -> str:
    """Release post markdown to plain text."""
    text = _LINK_DEF.sub("", text)
    text = _CREDITS.sub("", text)
    text = _TERM.sub(lambda m: m[2] or m[1], text)
    text = _LIQUID.sub("", text)
    text = _MD_LINK.sub(lambda m: m[1] or m[2], text)
    return re.sub(r"\s+", " ", text).strip()


def keywords(text: str) -> list[str]:
    """Code names in backticks that are specific enough to search for."""
    found = {m for m in _CODE.findall(text) if len(m) >= 6 and ("." in m or "_" in m)}
    return sorted(found)[:10]


def shorten(text: str, limit: int = MAX_TEXT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def parse_breaking_changes(post: str) -> list[Finding]:
    """All backward-incompatible changes in a monthly release post."""
    section = _SECTION.search(post or "")
    if not section:
        return []
    findings = []
    for title, body in _DETAILS.findall(section[1]):
        domains = sorted(set(_INTEGRATION_LINK.findall(body)))
        text = plain(body)
        findings.append(
            Finding(
                title=title.strip(),
                text=shorten(text),
                domains=domains,
                general=not domains,
                severe=bool(_SEVERE.search(text)),
                keywords=keywords(text),
            )
        )
    return findings


def match_core(changes: list[Finding], used: set[str]) -> tuple[list[Finding], int]:
    """Changes that touch integrations in use, plus general ones. Returns (findings, ignored)."""
    relevant = [c for c in changes if c.general or used.intersection(c.domains)]
    for change in relevant:
        change.domains = sorted(used.intersection(change.domains))
    return relevant, len(changes) - len(relevant)


def scan_changelog(text: str) -> list[Finding]:
    """Lines in a free-form changelog that sound like action is needed."""
    findings = []
    for line in (text or "").splitlines():
        line = re.sub(r"^[\s>*#-]+", "", line).strip()
        if len(line) < 8 or not _KEYWORD.search(line):
            continue
        findings.append(
            Finding(
                title="",
                text=shorten(clean(line), 250),
                severe=bool(_STRONG_KEYWORD.search(line)),
                source="changelog",
                keywords=keywords(line),
            )
        )
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def level_of(findings: list[Finding]) -> str:
    """Overall level for one update."""
    if any(f.severe and not f.general for f in findings):
        return LEVEL_WAIT
    if any(not f.general for f in findings):
        return LEVEL_CHECK
    return LEVEL_SAFE


def json_value(text: str | None, key: str) -> str | None:
    """A string value from a JSON document, e.g. hacs.json. Raises ValueError if broken."""
    if not text:
        return None
    value = json.loads(text).get(key)
    return str(value) if value else None
