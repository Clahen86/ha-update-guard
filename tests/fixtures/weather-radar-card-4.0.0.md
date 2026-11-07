**4.0 puts Home Assistant's own maps under the radar.** The card can now show HA's vector map, the map of HA's own map cards. Place names stay readable above the rain, the map is sharp at every zoom, and it follows your light or dark theme. 4.0 also adds view presets and buttons that show or hide overlays. New features are off until you turn them on. [Upgrading to 4.0](https://github.com/jpettitt/weather-radar-card/blob/main/docs/upgrading-to-4.0.md) lists what changes.

## ⚠️ Breaking changes

- **Home Assistant 2025.3 or later.** 3.13 needs 2024.1. On older Home Assistant, stay on 3.13.0.
- **Re-centre with a tracked marker.** The button now switches between the tracked marker and Default, the configured centre. Before, it moved to the configured centre until the tracked entity moved again. Now Default holds, with tracking paused, until the next press or until `preset_timeout` idle minutes (default 5) return the map to the tracked marker. Set `preset_timeout: 0` to hold Default until the next press. Cards without a tracked marker re-centre as before.
- **Manual installs need a second file.** Copy `weather-radar-card-maplibre.js` and its `.gz` into the same folder as `weather-radar-card.js`. The card loads it only for the vector map and for Satellite labels. HACS does this for you.

## What's new: maps

- **`map_style: MapTilesVector`.** Home Assistant 2026.10's vector map under the radar. Place names are drawn above the radar and above every overlay, so they stay readable through rain. The map is sharp at every zoom and follows HA's light or dark theme. Without WebGL2, or in `low_power_mode`, the card shows `MapTiles` instead.
- **`vector_style`.** One of the six styles of HA's map cards, or `classic`: the colours of the classic OpenStreetMap map, with a dark version tuned by hand.
- **`theme_mode: auto | light | dark`.** Forces the light or dark version of `MapTilesVector`, `Auto` and `MapTiles`.
- **Satellite labels above the radar.** On HA 2026.10 or later, `Satellite` draws place and street names from HA's map tiles above the radar. You do not need a CARTO key for them.
- **`extra_labels` on the vector map and Satellite.** Each kind of label shows one zoom level earlier, smaller and closer together.
- **Dark tile maps are greyer.** The inverted map keeps less of its colour, so forests and roads do not compete with the radar.

## What's new: views and controls

- **View presets.** `presets` turns the re-centre button into a rotation: the tracked marker, Default, then each saved view. A preset is a fixed location or an entity that the map follows, each with its own zoom. The preset's name shows beside the button. After `preset_timeout` idle minutes, the map goes back by itself. The editor's *Presets* page edits presets on the preview map. See [View presets](https://github.com/jpettitt/weather-radar-card/blob/main/docs/configuration.md#view-presets).
- **Layer toggles.** `show_layer_toggles` adds buttons in the top-right corner of the map that hide or show NWS alerts, wind, wildfires and lightning. A hidden overlay stops fetching. With `viewer_layer_control`, the card saves the choices of each user. See [Turning overlays on and off](https://github.com/jpettitt/weather-radar-card/blob/main/docs/overlays.md#turning-overlays-on-and-off).
- **Editor.** The Display toggles are in four groups. The map settings show only the fields that the selected style uses. The preview card has the same size as on the dashboard.
- **Smooth DWD radar edges.** With `dwd_interpolation: bilinear` (editor: **Smooth Radar Edges**), DWD's server smooths its 1 km grid before it applies its colour scale. When you zoom in, rain areas have smooth edges instead of squares, in DWD's own colours. Small areas of heavy rain look smaller. The option is off by default. ([#326](https://github.com/jpettitt/weather-radar-card/issues/326))

## Fixed since 3.13.0

- **Tile requests that do not answer.** Each tile request now stops after 30 seconds and tries again. Before, a tile whose connection hung waited until the browser stopped it (75 seconds in Chrome), and the frames after it waited too. On RainViewer, the card then read the error as a rate limit.
- **DWD wind showed an old forecast.** The card read the oldest model run that DWD keeps, which can be 39 hours old. It now reads the newest run that has the time shown. Wind always shows the model time step closest to now.
- **iPhone Safari ran out of memory.** Each radar tile had its own buffer at device resolution, up to 730 MB for a 13-frame loop, and iOS closed the page on a pinch. Tiles and hidden frames no longer keep buffers, and the overlays wait while the map zooms.
- **NWS alerts.** Zone outlines are simplified, only alerts in view are drawn, and the card fetches zone shapes 24 at a time, with a backoff when NWS blocks a burst. Expired alerts, and alerts that a later alert of the same event replaces, are hidden. A popup stays open until you close it. A banner shows fetch failures.
- **Blank frames after a view change.** At most three radar frames fetch at a time, in playback order from the shown frame. A zoom jump of two or more levels no longer requests a full set of tiles at the old zoom.
- **Requests that do not answer.** A frame list, alert, wildfire or wind request that did not answer stopped the radar updates or the overlay. The card now stops waiting and tries again.
- **Wind streamlines made the page stop for a moment every ten seconds.** The animation no longer makes garbage on each frame.
- **A full code review before 4.0.0** fixed problems in the radar player, the alerts, wildfire and marker layers, the editor, and Cast. The [changelog](https://github.com/jpettitt/weather-radar-card/blob/main/CHANGELOG.md) lists each fix.

## Internal

- The vector map code (MapLibre) is in its own file. The card loads it only for the vector map and Satellite labels, so other cards do not download it.
- The card is built and released on Node 24, and tested on Node 22 and 24.

## Configuration example

```yaml
type: custom:weather-radar-card
map_style: MapTilesVector
vector_style: classic
theme_mode: auto
show_recenter: true
show_layer_toggles: true
show_alerts: true
dwd_wind: barbs
markers:
  - entity: person.alex
    track: entity
presets:
  - name: Work
    latitude: 48.14
    longitude: 11.58
    zoom: 11
  - entity: device_tracker.car
    zoom: 12
preset_timeout: 5
```

## How to update

HACS shows 4.0.0 as an update. To go back, open the card in HACS, select 3.13.0 and install it. Before you go back, change `map_style: MapTilesVector` to another style, because 3.13 does not know it. Report problems at https://github.com/jpettitt/weather-radar-card/issues.

The 4.0 pre-releases had the same features: [alpha1](https://github.com/jpettitt/weather-radar-card/releases/tag/v4.0.0-alpha1) to [rc4](https://github.com/jpettitt/weather-radar-card/releases/tag/v4.0.0-rc4).

**Full Changelog**: https://github.com/jpettitt/weather-radar-card/compare/v3.13.0...v4.0.0

