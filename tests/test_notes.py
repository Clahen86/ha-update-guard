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
    # Breaking, but nothing here shows you use it: check, not wait.
    for f in findings:
        notes.judge(f)
    assert findings[0].affects == "maybe" and notes.level_of(findings) == "check"
    # Proof from this system makes it wait.
    findings[0].used_in = ["automation: Lys"]
    notes.judge(findings[0])
    assert findings[0].affects == "yes" and notes.level_of(findings) == "wait"
    # A small change with no trace of it here is safe.
    assert notes.level_of([findings[1]]) == "safe"
    assert notes.scan_changelog("- Bump base image\n- Fix typo") == []


def test_judge_yaml_and_removed_integrations():
    yaml_only = notes.Finding(title="Foo", text="The YAML configuration of Foo was removed", domains=["foo"])
    notes.judge(yaml_only, {"sensor", "template"})
    assert yaml_only.affects == "no"
    notes.judge(yaml_in := notes.Finding(title="Foo", text="The YAML setup of foo changed", domains=["foo"]), {"foo"})
    assert yaml_in.affects == "yes" and yaml_in.evidence == ["yaml:foo"]
    removed = notes.Finding(title="Bar", text="x", domains=["bar"], severe=True)
    notes.judge(removed, set())
    assert removed.affects == "yes" and notes.level_of([removed]) == "wait"
    other = notes.Finding(title="Baz", text="Attribute changed", domains=["baz"])
    notes.judge(other, set())
    assert other.affects == "maybe" and notes.level_of([other]) == "check"


def test_scan_changelog_skips_developer_changes():
    text = """## 2.0.0
- Remove unused translations
- Fix deprecation warning related to device binding
- Replaced deprecated function `async_track_state_change`
- light: avoid breaking on bad rgbhsv data
- docs: remove onvif host environment variable
- No breaking changes in this release
- The `port` option was removed, use `listen_port`
- feat!: drop the legacy API
"""
    texts = [f.text for f in notes.scan_changelog(text)]
    assert texts == ["The `port` option was removed, use `listen_port`", "feat!: drop the legacy API"]
    assert [f.severe for f in notes.scan_changelog(text)] == [False, True]


def test_scan_changelog_sections():
    text = """This release includes breaking changes, read them below.

## ⚠ BREAKING CHANGES

* `spin` (to make the icon rotate) has
  been renamed to `rotate`
* The default theme changed

```yaml
type: custom:button-card
```

## Bug fixes

* Remove a check that was removed upstream
* Options are no longer saved twice

**Full Changelog**: https://github.com/x/y/compare/1...2
"""
    findings = notes.scan_changelog(text)
    assert [f.text for f in findings] == [
        "`spin` (to make the icon rotate) has been renamed to `rotate`",
        "The default theme changed",
    ]  # "Options are no longer saved twice" under Bug fixes describes a fix, not something to act on
    assert findings[0].severe and findings[1].severe


def test_parse_ai_answer():
    answer = '```json\n{"lines": [{"n": 1, "relevant": false, "reason": "Internal"}, {"n": 2, "relevant": true, '
    answer += '"severe": true, "reason": "Option renamed"}, {"n": 9, "relevant": true}, {"n": "x"}]}\n```'
    verdicts = notes.parse_ai_answer(answer, 2)
    assert verdicts == {
        1: {"relevant": False, "severe": False, "reason": "Internal"},
        2: {"relevant": True, "severe": True, "reason": "Option renamed"},
    }
    assert notes.parse_ai_answer({"lines": []}, 1) == {}
    for broken in ("no json", {"other": 1}, None):
        try:
            notes.parse_ai_answer(broken, 1)
        except ValueError:
            continue
        raise AssertionError(broken)


def test_keywords():
    changes = notes.parse_breaking_changes(POST)
    mqtt = next(c for c in changes if c.title == "MQTT")
    assert "mqtt.publish" in mqtt.keywords and "mqtt.dump" in mqtt.keywords
    assert notes.keywords("the `for` option and `port`") == []


def test_scan_options():
    keys = notes.option_keys(
        {"serial": {"port": "/dev/ttyUSB0", "adapter": "ember"}, "data_path": "/config/z2m", "ssl": False}
    )
    assert keys == {"serial", "port", "adapter", "data_path"}
    text = """## 2.0.0
- The `data_path` option has been renamed to `path`
- Add support for new devices with a data_path display
- Changed default `port` speed
- `ssl` was removed
"""
    findings = notes.scan_options(text, keys)
    assert [f.title for f in findings] == ["data_path", "port"]
    assert findings[0].severe and not findings[1].severe


def test_has_content():
    assert not notes.has_content(None)
    assert not notes.has_content("<ha-alert alert-type='info'>The system will reboot</ha-alert>")
    assert not notes.has_content("[**Read release announcement**](https://esphome.io/changelog/2026.10.0)")
    assert notes.has_content("- Keep TLS 1.3 working for audio streams")


def test_weather_radar_card_4_0_0():
    """Issue: a heading alone, fixes described with "no longer", and bold lead-ins."""
    from pathlib import Path

    body = (Path(__file__).parent / "fixtures" / "weather-radar-card-4.0.0.md").read_text()
    findings = notes.scan_changelog(body)
    texts = [f.text for f in findings]
    assert len(findings) == 3 and all(f.severe for f in findings)  # the three real breaking changes
    assert texts[0].startswith("Home Assistant 2025.3 or later.")  # caught, and no ** left
    assert not any("**" in t for t in texts)
    assert not any("Safari" in t or "Blank frames" in t or "streamlines" in t for t in texts)  # fixes are not findings
    assert not any(t.strip("⚠️ ").lower() == "breaking changes" for t in texts)  # no finding for a heading


def test_requires_ha_version_outside_a_section():
    assert notes.scan_changelog("- This release requires Home Assistant 2025.3 or later")
    assert notes.scan_changelog("## Bug fixes\n- Crash on start no longer happens") == []
