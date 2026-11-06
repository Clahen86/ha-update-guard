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
    r"breaking[- ]changes?|\bbreaking:|⚠|💥|backward[- ]incompatible|no longer|deprecat|\bremov(?:e|ed|es|al)\b|"
    r"manual(?:ly)? (?:action|step|migrat)|migration (?:is )?required|must now|now requires?|requires? you",
    re.I,
)
# "breaking" on its own is often a verb ("avoid breaking on bad data"), so only these count as strong.
_STRONG_KEYWORD = re.compile(r"breaking[- ]changes?|\bbreaking:|⚠|💥|backward[- ]incompatible", re.I)
# Conventional commits (feat!: / fix(api)!:) and an upper-case BREAKING.
_BREAKING_MARK = re.compile(r"^\w+(?:\([^)]*\))?!:|\bBREAKING\b")
# Wording that means the user has to do something, even in a line about a fix.
_ACTION = re.compile(
    r"no longer|must|now requires?|requires? you|manual|breaking[- ]changes?|\bBREAKING\b|"
    r"deprecat\w* (?:\S+ ){0,3}?(?:actions?|services?|options?|sensors?|entit(?:y|ies)|attributes?|yaml|settings?)\b",
    re.I,
)

# Section headings: "## ⚠ BREAKING CHANGES", "**Bug fixes**", or a short line like "Breaking changes".
_MD_HEADING = re.compile(r"^\s{0,3}(?:#{1,6}\s+(.*?)[\s#]*|\*\*([^*]+)\*\*:?|__([^_]+)__:?)\s*$")
_PLAIN_HEADING = re.compile(
    r"^\W*(?:breaking changes?|backward[- ]incompatible changes?|bug ?fix(?:es)?|fixes|(?:new )?features?|"
    r"enhancements?|improvements?|other changes|what'?s changed|changes|new devices?|dependenc(?:y|ies)(?: updates?)?|"
    r"chores?|maintenance|documentation|highlights?|deprecations?)\W*$",
    re.I,
)
_BREAKING_SECTION = re.compile(r"breaking|backward[- ]incompatible|action required|upgrade notes?", re.I)
_MINOR_SECTION = re.compile(
    r"bug ?fix|\bfix(?:es|ed)?\b|chores?|dependenc|maintenance|internal|refactor|\bdocs?\b|documentation|"
    r"\bci\b|\bbuild\b|\btests?\b|translations?",
    re.I,
)
# "This release includes breaking changes, read them below": only a pointer to the section.
_POINTER = re.compile(
    r"(?:includes?|contains?|has|have|several|some|few|read|see|following|these)\b.{0,25}breaking changes?", re.I
)

# "No breaking changes", "non-breaking".
_NEGATED = re.compile(
    r"\bno(?:t| more)? (?:any )?(?:breaking|backward[- ]incompatible)|non[- ]breaking|without breaking", re.I
)
_BULLET = re.compile(r"^\s*(?:[-*+>]|\d+[.)])\s")
_FOOTER = re.compile(r"^\W*(?:full changelog|new contributors|documentation)\W*:", re.I)

# Changes for developers, not for the people using it.
_DEV_PREFIX = re.compile(r"^(?:docs?|chore|ci|build|tests?|refactor|perf|style|revert)(?:\([^)]*\))?:", re.I)
_DEV_VERB = re.compile(
    r"^(?:fix(?:e[sd])?|handle[sd]?|catch|avoid|prevent|guard|improve[sd]?|allow|add(?:ed|s)?|adapt|bump|update[sd]?|refactor|"
    r"clean ?up|tidy|revert|preserve|optimi[sz]e)\b",
    re.I,
)
_DEV_REMOVAL = re.compile(
    r"\bremov\w*\b.{0,60}?\b(?:unused|unnecessary|unneeded|un-?needed|uneeded|useless|redundant|obsolete|commented|dead|"
    r"debug|logging|logs?|tests?|hooks?|badges?|dependenc\w*|deps?|info\.md|lint\w*|tooling|code|variables?|"
    r"arguments?|functions?|class(?:es)?|checks?|warnings?|duplicates?|typos?|constants?|consts?|imports?|"
    r"hacs\.json|manifest\.json|readme)\b",
    re.I,
)
_DEV_DEPRECATION = re.compile(
    r"(?:fix|replac|handl|avoid|eliminat|clean ?up|catch)\w*\b.{0,50}?deprecat|using deprecated|"
    r"deprecation (?:warnings?|fix(?:es)?)|deprecated (?:\S+ ){0,2}?(?:constants?|consts?|apis?|functions?|"
    r"calls?|imports?|usage|code|methods?|propert(?:y|ies)|decorators?)\b",
    re.I,
)


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
    # What the optional AI check said about it.
    ai: str = ""
    # Does it touch this system? "yes" (proof found here), "maybe" (only the integration matches) or "no".
    affects: str = "maybe"
    # Proof from this system besides used_in: entities, attributes, YAML setup.
    evidence: list[str] = field(default_factory=list)

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
    """Lines in a free-form changelog that sound like action is needed.

    Everything in a "Breaking changes" section counts. Elsewhere a line needs a keyword, and changes for
    developers (removed unused code, fixed a deprecation warning) or lines in a bug fix section are skipped."""
    lines = _logical_lines(text)
    sections = [_section(line) for line in lines]
    has_breaking_section = "breaking" in sections
    findings = []
    section = ""
    for raw, heading in zip(lines, sections):
        if heading is not None:
            section = heading
            continue
        line = re.sub(r"^[\s>*#-]+", "", raw).strip()
        if _FOOTER.match(line) or len(re.sub(r"\W+", "", re.sub(r"https?://\S+|@\w+", "", line))) < 8:
            continue
        if section == "breaking":
            severe = True
        elif not (_KEYWORD.search(line) or _BREAKING_MARK.search(line)) or _harmless(line, section):
            continue
        else:
            severe = bool(_STRONG_KEYWORD.search(line) or _BREAKING_MARK.search(line))
            if severe and has_breaking_section and _POINTER.search(line):
                continue
        findings.append(
            Finding(
                title="",
                text=shorten(clean(line), 250),
                severe=severe,
                source="changelog",
                keywords=keywords(line),
            )
        )
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def _logical_lines(text: str | None) -> list[str]:
    """Lines of a changelog, with wrapped lines joined to their bullet and code blocks left out."""
    lines: list[str] = []
    in_code = False
    for line in (text or "").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code:
            continue
        if (
            lines
            and line.strip()
            and lines[-1].strip()
            and not _BULLET.match(line)
            and _section(line) is None
            and _section(lines[-1]) is None
        ):
            lines[-1] = f"{lines[-1].rstrip()} {line.strip()}"
        else:
            lines.append(line)
    return lines


def _section(line: str) -> str | None:
    """The kind of section a heading starts ("breaking", "minor", "feature" or ""), or None if not a heading."""
    if match := _MD_HEADING.match(line):
        heading = next(g for g in match.groups() if g is not None)
    elif _PLAIN_HEADING.match(line):
        heading = line
    else:
        return None
    if _BREAKING_SECTION.search(heading):
        return "breaking"
    if _MINOR_SECTION.search(heading):
        return "minor"
    return "feature" if _FEATURE_SECTION.search(heading) else ""


def _harmless(line: str, section: str) -> bool:
    """A keyword line that is not something to act on, e.g. "Remove unused code" or "Fix deprecation warning"."""
    if _NEGATED.search(line):
        return True
    if _STRONG_KEYWORD.search(line) or _BREAKING_MARK.search(line):
        return False
    start = re.sub(r"^(?:#\d+|\[[^\]]*\]|\w+(?:\([^)]*\))?:)\s*", "", line)
    if _DEV_PREFIX.match(line) or _DEV_REMOVAL.search(line) or _DEV_DEPRECATION.search(line):
        return True
    return (bool(_DEV_VERB.match(start)) or section == "minor") and not _ACTION.search(line)


def has_content(text: str | None) -> bool:
    """Release notes with actual text, not just a link or a reboot notice."""
    text = re.sub(r"<[^>]+>|\[([^\]]*)\]\([^)]*\)|https?://\S+", " ", text or "")
    return len(re.sub(r"\W+", "", text)) >= 30


# Sources that are facts about this system: Home Assistant's own warnings, a needed version, your own options.
FACT_SOURCES = {"log", "repair", "hacs", "option"}
_YAML = re.compile(r"\byaml\b", re.I)


def judge(finding: Finding, yaml_domains: set[str] | None = None) -> None:
    """Set finding.affects from what was found in this system."""
    if finding.general or finding.affects == "no":
        finding.affects = "no"
    elif finding.source in FACT_SOURCES or finding.used_in or finding.evidence:
        finding.affects = "yes"
    elif finding.source == "release" and finding.severe and finding.domains:
        # An integration that is removed or stops working, and it is loaded here.
        finding.evidence = [f"integration:{d}" for d in finding.domains]
        finding.affects = "yes"
    elif yaml_domains is not None and finding.domains and _YAML.search(finding.text):
        # A change to YAML setup only matters if you set the integration up in YAML.
        used = sorted(d for d in finding.domains if d in yaml_domains)
        if used:
            finding.evidence = [f"yaml:{d}" for d in used]
            finding.affects = "yes"
        else:
            finding.affects = "no"
    else:
        finding.affects = "maybe"


# A fix for a security hole.
SECURITY = re.compile(
    r"\bCVE-\d{4}-\d+|\bGHSA-|vulnerabilit|security (?:fix|issue|update|patch|advisory|release|hole|problem)|"
    r"fix(?:es|ed)? (?:a |an |the )?(?:\w+ )?security|\bXSS\b|remote code execution",
    re.I,
)
_FEATURE_SECTION = re.compile(r"feature|enhancement|improvement|highlight|what'?s new|\bnew\b|added", re.I)
_NEWS_START = re.compile(r"^(?:feat(?:\([^)]*\))?:|add(?:ed|s)?\b|new\b|support(?:s|ed)? for\b|now supports?\b)", re.I)


def scan_news(text: str, terms: set[str], limit: int = 5) -> list[str]:
    """New features that name something you have (an entity, device model, option or integration)."""
    if not text or not terms:
        return []
    patterns = [re.compile(rf"(?<![\w.]){re.escape(t)}(?![\w])", re.I) for t in sorted(terms) if len(t) >= 4]
    found: list[str] = []
    section = ""
    for raw in _logical_lines(text):
        if (heading := _section(raw)) is not None:
            section = heading
            continue
        line = re.sub(r"^[\s>*#-]+", "", raw).strip()
        if section != "feature" and not _NEWS_START.match(line):
            continue
        if section in ("breaking", "minor") or _DEV_PREFIX.match(line):
            continue
        if any(p.search(line) for p in patterns):
            item = shorten(clean(line), 160)
            if item not in found:
                found.append(item)
        if len(found) >= limit:
            break
    return found


def core_news(post: str, used: set[str], limit: int = 5) -> list[str]:
    """Paragraphs of a release post before the breaking changes that are about integrations you use."""
    head = (post or "").split("## Backward-incompatible changes")[0]
    found = []
    for block in re.split(r"\n\s*\n", head):
        domains = set(_INTEGRATION_LINK.findall(block)) & used
        if not domains or block.lstrip().startswith(("#", "[", "<", "{%")):
            continue
        text = shorten(plain(block), 200)
        if len(text) > 40:
            found.append(text)
        if len(found) >= limit:
            break
    return found


def level_of(findings: list[Finding]) -> str:
    """Overall level for one update, from what touches this system.

    Wait: something severe, and proof that you use it. Check: severe without proof, a change you are proven to
    use, a Core change to an integration you have, or a line that asks you to act. Other changelog lines with no
    trace of them here are listed, but don't stop the update."""
    if any(f.severe and f.affects == "yes" and not f.general for f in findings):
        return LEVEL_WAIT
    if any(
        not f.general and (f.affects == "yes" or (f.affects == "maybe" and (f.severe or f.source in ("release", "reports") or _ACTION.search(f.text))))
        for f in findings
    ):
        return LEVEL_CHECK
    return LEVEL_SAFE


def sort_key(finding: Finding | dict) -> tuple:
    """Proven and severe first, general last."""
    f = finding if isinstance(finding, dict) else finding.as_dict()
    return ({"yes": 0, "maybe": 1}.get(f.get("affects"), 2), not f["severe"], f["general"])


def parse_ai_answer(data: object, count: int) -> dict[int, dict]:
    """The AI's verdict per line number (1..count). Raises ValueError if the answer can't be read."""
    if isinstance(data, str):
        match = re.search(r"\{.*\}", data, re.S)
        if not match:
            raise ValueError("no JSON in the answer")
        data = json.loads(match.group(0))
    items = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("no lines in the answer")
    verdicts = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("relevant"), bool):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= count:
            reason = shorten(str(item.get("reason") or ""), 120)
            verdicts[n] = {"relevant": item["relevant"], "severe": item.get("severe") is True, "reason": reason}
    return verdicts


def json_value(text: str | None, key: str) -> str | None:
    """A string value from a JSON document, e.g. hacs.json. Raises ValueError if broken."""
    if not text:
        return None
    value = json.loads(text).get(key)
    return str(value) if value else None


# A line that changes an option: renamed, removed, new default, ...
_OPTION_CHANGE = re.compile(
    r"renam|remov|deprecat|no longer|replac|changed?|moved?|default|now (?:requires?|must)|must be|breaking", re.I
)
_OPTION_SEVERE = re.compile(r"renam|remov|no longer|replac|breaking|must be", re.I)


# Container names that show up in almost every changelog.
_GENERIC_OPTIONS = {
    "options",
    "config",
    "configuration",
    "settings",
    "active",
    "enabled",
    "name",
    "type",
    "value",
    "data",
}


def option_keys(options: dict) -> set[str]:
    """Names of the options you have set, also nested ones."""
    keys = set()
    for key, value in (options or {}).items():
        if value in (None, "", [], {}, False):
            continue
        if str(key).lower() not in _GENERIC_OPTIONS:
            keys.add(str(key))
        if isinstance(value, dict):
            keys |= option_keys(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    keys |= option_keys(item)
    return keys


def scan_options(text: str, keys: set[str]) -> list[Finding]:
    """Changelog lines that change an option you have set."""
    # Short names like `ssl` or `port` only count in backticks.
    patterns = {
        key: re.compile(rf"`{re.escape(key)}`" if len(key) < 5 and "_" not in key else rf"\b{re.escape(key)}\b", re.I)
        for key in keys
    }
    findings = []
    for line in (text or "").splitlines():
        line = re.sub(r"^[\s>*#-]+", "", line).strip()
        if not _OPTION_CHANGE.search(line):
            continue
        hits = sorted(key for key, pattern in patterns.items() if pattern.search(line))
        if hits:
            findings.append(
                Finding(
                    title=", ".join(hits),
                    text=shorten(clean(line), 250),
                    severe=bool(_OPTION_SEVERE.search(line)),
                    source="option",
                    keywords=keywords(line),
                )
            )
        if len(findings) >= MAX_FINDINGS:
            break
    return findings
