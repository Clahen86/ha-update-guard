# Update Guard

**Know what an update will break – before you install it.**

[English](#english) · [Dansk](#dansk)

## English

Every month Home Assistant ships backward-incompatible changes, and most people never read them. Update Guard reads them for you and compares them with *your* setup.

- **Home Assistant Core:** reads the "Backward-incompatible changes" of every monthly release between your version and the new one (also if you skipped a few months) and keeps only the ones for integrations you actually use.
- **Apps (add-ons), HACS and firmware:** scans the changelog of every pending update for words like *breaking*, *removed*, *deprecated* and *migrate*.
- **What HA already warned about:** log warnings like *"custom integration X … will stop working in Home Assistant 2026.11"* and repairs with a "breaks in" version are matched to the update that will actually break them. Log warnings are remembered across restarts.
- **HACS needs a newer HA:** if a HACS update needs a newer Home Assistant than you run, you're told to update Home Assistant first.
- **Your own setup:** actions, options and sensors named in the release notes are looked up in your automations, scripts and dashboards, so you see *"Used in: Automation: Hallway lights"*.
- **Clear verdict:** 🟢 Safe · 🟡 Check first · 🔴 Wait – as a sensor and as a repair under **Settings → Repairs**, with what to look at and a link to the release notes.
- Works on HA OS, Supervised, Container and Core. Without Supervisor there are no apps, and the latest Core version comes from GitHub.
- No account, no API key and no AI needed.

### Install

1. HACS → ⋮ → **Custom repositories** → `https://github.com/Clahen86/ha-update-guard` (type *Integration*).
2. Install **Update Guard** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Update Guard.**

### Entities

| Entity | What |
| --- | --- |
| `sensor.update_guard_assessment` | `safe`, `check`, `wait` or `none`. The `updates` attribute has the details for each update. |
| `sensor.update_guard_things_to_check` | Number of changes that touch your setup. |
| `button.update_guard_check_now` | Check again right away (it also checks every 6 hours and whenever a new update shows up). |

Example automation: send a notification when the assessment turns to `wait`.

### Good to know

- Core matching is by integration. "MQTT changed" means you use MQTT, not necessarily the exact feature that changed.
- Changes not tied to one integration (e.g. automations or authentication) are listed in the attributes but don't change the verdict.
- Changelog scanning of apps and HACS is keyword-based and can give false alarms.
- "Used in" only finds names written in backticks in the release notes, so it can miss some.
- Coming: a before/after check (what stopped working after the update) and optional AI explanations in your own language.

## Dansk

Hver måned kommer der ændringer i Home Assistant, som kan ødelægge noget, og de færreste læser dem. Update Guard læser dem for dig og holder dem op mod *din* opsætning.

- **Home Assistant Core:** læser "Backward-incompatible changes" for alle månedlige udgivelser fra din version til den nye (også når du har sprunget måneder over) og viser kun dem for integrationer, du faktisk bruger.
- **Apps (add-ons), HACS og firmware:** gennemgår changelog for alle ventende opdateringer og leder efter ord som *breaking*, *removed*, *deprecated* og *migrate*.
- **Det HA allerede har advaret om:** advarsler i loggen som *"custom integration X … will stop working in Home Assistant 2026.11"* og reparationer med en "går i stykker i"-version kobles til den opdatering, hvor de rent faktisk går i stykker.
- **HACS kræver nyere HA:** kræver en HACS-opdatering en nyere Home Assistant, får du besked om at opdatere HA først.
- **Din egen opsætning:** actions, indstillinger og sensorer, der nævnes i release notes, slås op i dine automatiseringer, scripts og dashboards, så du ser *"Bruges i: Automatisering: Lys i gangen"*.
- **Klar besked:** 🟢 Sikker · 🟡 Tjek først · 🔴 Vent. Den kommer som en sensor og under **Indstillinger → Reparationer** med det, du skal kigge på, og et link til release notes.
- Virker på HA OS, Supervised, Container og Core.
- Kræver ingen konto, nøgle eller AI.

### Installation

1. HACS → ⋮ → **Brugerdefinerede repositories** → `https://github.com/Clahen86/ha-update-guard` (type *Integration*).
2. Installér **Update Guard**, og genstart Home Assistant.
3. **Indstillinger → Enheder og tjenester → Tilføj integration → Update Guard.**

Menuer og beskeder er på dansk, når HA er sat til dansk. Selve teksten fra udviklerne i release notes er på engelsk.

## License

MIT
