# Changelog – Update Guard

Newest first. Each version lists what changed since the one before.

## 0.11.2 – 2026-11-22

- No more warning in Home Assistant's log at start-up (the version was read from disk in the event loop)

## 0.11.1 – 2026-11-16

- A new safe update no longer stops the check when it is planned for tonight

## 0.11.0 – 2026-11-16

- Store and update links open right inside Home Assistant
- Error reports: a translated message shown on purpose (a refusal) is not reported as an error
- Support: version from Home Assistant's loader, no blocking read in the event loop
- Power sensors as blockers, failed installs told, safer night runs, plans kept over restart, no double install, app backups, auto-update warning, clearer messages

## 0.10.0 – 2026-11-14

- How it is set up goes with the daily question (no names unless 'Share my setup' is on)

## 0.9.0 – 2026-11-14

- Update card (new version, your error fixed) and the version in the daily question

## 0.8.1 – 2026-11-14

- Files under a new address for every version, so a browser never mixes old and new files

## 0.8.0 – 2026-11-14

- Suggestions of the other apps (fits your home, from the same developer)

## 0.7.2 – 2026-11-14

- Errors from Home Assistant restarting or the network (502, timeout, no connection) are not reported

## 0.7.1 – 2026-11-14

- Help sends again (the websocket field 'id' clashed with the message's own)

## 0.7.0 – 2026-11-14

- Help - get help, answers from the developer, errors sent anonymously

## 0.6.5 – 2026-11-11

- The 'does not work after update' message can be closed without going back (HA gives no Ignore button on fixable repairs)

## 0.6.4 – 2026-11-11

- After-check no longer reports what was off before the update (integration without a single working entity, fresh image at shutdown), 'at the same time' only after a restart, the verdict 'unknown' is now called 'unclear' so it can be used in automations

## 0.6.3 – 2026-11-07

- Bug fix sections ('X no longer happens') are not findings, ** removed everywhere in the line, 'requires Home Assistant 2025.3' is caught, 'something you use' only when proven (thanks to the report about weather-radar-card 4.0.0)

## 0.6.2 – 2026-11-06

- Settings in the panel, saved immediately
- Update Guard 0.6.2

## 0.6.1 – 2026-11-06

- Icon for the safe_update service (hassfest)
- Repair with a way back has its own text key (hassfest)
- Update Guard 0.6.1

## 0.6.0 – 2026-11-06

- More precise: only evidence from your own system gives Wait, and one line with the verdict
- Update Guard 0.6.0: panel, update safely, go back, others' error reports, skipped versions, wait for .1, dead projects, security and news for you, marketplace

## 0.5.0 – 2026-11-03

- Update Guard 0.5.0: tjek efter opdateringen

## 0.4.0 – 2026-11-03

- Update Guard 0.4.0: fewer false alarms and optional AI check

## 0.3.1 – 2026-11-02

- Update Guard 0.3.1: missing release notes give Unknown, not Safe

## 0.3.0 – 2026-11-02

- Tjek app-indstillinger mod changelog
- Also check HACS integrations' settings against the changelog
- Update Guard 0.3.0: phone notification on new updates

## 0.2.0 – 2026-11-02

- Update Guard 0.2.0: log warnings, repairs, HACS requirements and use in your own setup

## 0.1.0 – 2026-11-02

- Update Guard 0.1.0: check updates for breaking changes before installing
