# Update Guard

**Know what an update will break – before you install it.**

![Update Guard](docs/hero.png)

[English](#english) · [Dansk](#dansk)

## English

Every month Home Assistant ships changes that can break things, and so do apps (add-ons) and HACS integrations. Most people don't read the release notes – they update and hope. Update Guard reads them for you and compares them with *your* setup.

![Example of a repair from Update Guard (illustration)](docs/repair.png)

### What it checks

| Update | What Update Guard does |
| --- | --- |
| **Home Assistant Core** | Reads the *Backward-incompatible changes* of every monthly release between your version and the new one (also if you skipped a few months) and keeps only the ones for integrations you actually use. |
| **Built-in integrations** (MQTT, Hue, UniFi …) | They update with Core, so they're covered above. Actions, options and sensors named in the notes are looked up in your automations, scripts and dashboards: *"Used in: Automation: Hallway lights"*. |
| **Apps (add-ons)** | Reads the changelog from your version to the new one. Options you have set in the app (e.g. Zigbee2MQTT's `serial` → `adapter`) are compared with it, so a renamed or removed option you use is caught. |
| **HACS integrations** | Same changelog and option check as apps, plus: if the new version needs a newer Home Assistant than you run, you're told to update Home Assistant first. |
| **Firmware and everything else** with an update entity (ESPHome, Zigbee, …) | Changelog scan for words like *breaking*, *removed*, *deprecated*. |
| **What HA already warned about** | Log warnings like *"custom integration X … will stop working in Home Assistant 2026.11"* and repairs with a "breaks in" version are linked to the update that will actually break them. |

![How it works](docs/how.png)

### The verdict

- 🟢 **Safe** – nothing in the notes touches your setup.
- 🟡 **Check first** – something you use changes. Read the points before you update.
- 🔴 **Wait** – something you use is removed, renamed or needs a newer Home Assistant.

You see it in three places: the sensor, **Settings → Repairs** (one repair per risky update, with what to look at and a link to the release notes), and the attributes of the sensor for dashboards and automations.

### Installation

1. Open **HACS** → ⋮ (top right) → **Custom repositories**.
2. Repository: `https://github.com/Clahen86/ha-update-guard` · Type: **Integration** → **Add**.
3. Search for **Update Guard** in HACS → **Download**.
4. Restart Home Assistant.
5. **Settings → Devices & services → Add integration → Update Guard → Submit.** There is nothing to fill in.

That's it. It checks every 6 hours and right away whenever a new update shows up.

### Entities

Entity IDs follow your Home Assistant language. In English:

| Entity | What |
| --- | --- |
| `sensor.update_guard_assessment` | `safe`, `check`, `wait` or `none`. The `updates` attribute has the details for each update. |
| `sensor.update_guard_things_to_check` | Number of changes that touch your setup. |
| `button.update_guard_check_now` | Check again right away. |

### Example: get a notification

```yaml
triggers:
  - trigger: state
    entity_id: sensor.update_guard_assessment
    to: wait
actions:
  - action: notify.notify
    data:
      title: Wait with the update
      message: Update Guard found something that will break. See Settings → Repairs.
```

### Example: dashboard card

```yaml
type: markdown
content: >
  {% for u in state_attr('sensor.update_guard_assessment', 'updates') or [] %}
  **{{ u.name }}** {{ u.installed }} → {{ u.latest }}: {{ u.level }}
  {% for f in u.findings if not f.general %}
  - {{ f.title }} {{ f.text }}
  {% endfor %}
  {% else %}
  No pending updates.
  {% endfor %}
```

### FAQ

**Does it need AI or an API key?** No. Everything is read from the official release notes and changelogs. An optional AI explanation in your own language may come later, but it will never be required.

**Does it send my setup anywhere?** No. It only downloads public release notes from GitHub. Only option *names* are read, never their values, and nothing leaves your Home Assistant.

**Does it work without HA OS?** Yes. On Container and Core installs there are no apps, and the latest Core version is taken from GitHub.

**Can it be wrong?** Yes, sometimes:
- Core matching is by integration. "MQTT changed" means you use MQTT, not necessarily the exact feature that changed.
- App and HACS changelogs are free text, so they're scanned for keywords. That can give false alarms, and a change that isn't described can't be found.
- "Used in" only finds names written as code (`like_this`) in the notes.
- Integrations installed by hand (not via HACS) have no update entity, so only their log warnings are seen.

**What's next?** A before/after check that tells you what stopped working right after an update.

## Dansk

Hver måned kommer der ændringer i Home Assistant, apps og HACS-integrationer, som kan ødelægge noget. De færreste læser release notes. Update Guard læser dem for dig og holder dem op mod *din* opsætning.

### Det tjekker den

- **Home Assistant Core:** Den læser *Backward-incompatible changes* for alle månedlige udgivelser fra din version til den nye, også hvis du har sprunget måneder over. Den viser kun ændringer for integrationer, du faktisk bruger.
- **Indbyggede integrationer:** De bliver opdateret sammen med Core. Actions, indstillinger og sensorer, der nævnes i release notes, slår den op i dine automatiseringer, scripts og dashboards, fx *"Bruges i: Automatisering: Lys i gangen"*.
- **Apps (add-ons):** Den læser changelog og holder den op mod de indstillinger, du har sat i appen.
- **HACS-integrationer:** Den laver samme tjek som for apps. Derudover får du besked om at opdatere HA først, hvis den nye version kræver en nyere HA.
- **Firmware og alt andet** med en opdatering (ESPHome, Zigbee osv.): Den leder i changelog efter ord som *breaking*, *removed* og *deprecated*.
- **Det HA allerede har advaret om:** Advarsler i loggen og reparationer med en "går i stykker i"-version kobles til den opdatering, hvor de rent faktisk går i stykker.

### Vurderingen

- 🟢 **Sikker:** Intet i release notes rører din opsætning.
- 🟡 **Tjek først:** Noget, du bruger, bliver ændret.
- 🔴 **Vent:** Noget, du bruger, bliver fjernet eller omdøbt, eller opdateringen kræver en nyere HA.

Du ser vurderingen på sensoren og under **Indstillinger → Reparationer**.

### Installation

1. **HACS** → ⋮ (øverst til højre) → **Brugerdefinerede repositories**.
2. Repository: `https://github.com/Clahen86/ha-update-guard` · Type: **Integration** → **Tilføj**.
3. Søg efter **Update Guard** i HACS → **Download**.
4. Genstart Home Assistant.
5. **Indstillinger → Enheder og tjenester → Tilføj integration → Update Guard → Send.** Der er intet at udfylde.

Den tjekker hver 6. time og med det samme, når der kommer en ny opdatering.

På dansk hedder enhederne `sensor.update_guard_vurdering`, `sensor.update_guard_ting_at_tjekke` og `button.update_guard_tjek_nu`. Eksemplerne ovenfor virker også på dansk, når du skifter navnene ud.

Menuer og beskeder er på dansk. Selve teksten fra udviklerne er på engelsk.

**Kræver den AI?** Nej, og den sender ikke noget om din opsætning ud af huset.

## License

MIT
