"""Release note parsing."""

from pathlib import Path

from custom_components.update_guard import notes

POST = (Path(__file__).parent / "fixtures" / "release-202610.markdown").read_text()


def test_months_between():
    assert notes.months_between("2026.10.4", "2026.10.5") == []
    assert notes.months_between("2026.10.4", "2026.11.0") == [(2026, 11)]
    assert notes.months_between("2025.11.1", "2026.2.0b1") == [(2025, 12), (2026, 1), (2026, 2)]
    assert notes.months_between("2026.11.0", "2026.10.0") == []


def test_post_slug():
    slug = notes.post_slug("https://www.home-assistant.io/blog/2026/10/07/release-202610/")
    assert slug == ("2026-10-07-release-202610", "https://www.home-assistant.io/blog/2026/10/07/release-202610/")
    assert notes.post_slug("nothing here") is None


def test_parse_breaking_changes():
    changes = notes.parse_breaking_changes(POST)
    titles = [c.title for c in changes]
    assert "MQTT" in titles and "Authentication" in titles
    mqtt = next(c for c in changes if c.title == "MQTT")
    assert mqtt.domains == ["mqtt"] and not mqtt.general
    assert "administrator" in mqtt.text and "{%" not in mqtt.text and "[@" not in mqtt.text
    auth = next(c for c in changes if c.title == "Authentication")
    assert auth.general
    both = next(c for c in changes if c.title == "Linode and Tank Utility")
    assert len(both.domains) == 2
    assert both.severe  # both integrations have been removed
    synology = next(c for c in changes if c.title == "Synology DSM")
    assert not synology.severe  # "shut down the NAS" is not the integration going away


def test_match_core():
    changes = notes.parse_breaking_changes(POST)
    relevant, ignored = notes.match_core(changes, {"mqtt", "sensor", "homeassistant"})
    titles = {c.title for c in relevant}
    assert "MQTT" in titles and "Authentication" in titles and "Xbox" not in titles
    assert ignored == len(changes) - len(relevant)
    assert notes.level_of(relevant) == "check"
    assert notes.level_of([c for c in relevant if c.general]) == "safe"


def test_scan_changelog():
    text = """## 3.2.0
- Bump base image
- ⚠️ Breaking: the `port` option was renamed to `listen_port`
- Removed support for armv7
- Fix typo
"""
    findings = notes.scan_changelog(text)
    assert len(findings) == 2
    assert findings[0].severe and not findings[1].severe
    assert notes.level_of(findings) == "wait"
    assert notes.scan_changelog("- Bump base image\n- Fix typo") == []


def test_keywords():
    changes = notes.parse_breaking_changes(POST)
    mqtt = next(c for c in changes if c.title == "MQTT")
    assert "mqtt.publish" in mqtt.keywords and "mqtt.dump" in mqtt.keywords
    assert notes.keywords("the `for` option and `port`") == []
