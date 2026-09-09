# Changelog

## 0.6.0 — 2026-09-08

- **Ignore faces that aren't people.** A camera pointed at a room sees faces that
  never move — a poster, a photo frame, a paused TV, the artwork on an arcade
  cabinet — and every one of them filled *Recent sightings* with unknowns
  ([#13](https://github.com/adamoberley/ha-addons/issues/13)). Open the sighting
  (or capture the face deliberately) and hit **Ignore**: from then on it's
  matched and then dropped — no sighting, no sensor change, no notification —
  and it shows in the live view as a grey box labelled *ignored* so you can see
  it's deliberate.
  - Ignoring a face also **clears its existing sightings** out of the log, so the
    history you were cleaning up goes with it.
  - The list holds **as many entries as you like**, each with several patterns:
    hit *Ignore* on the same object from another angle and it's added to that
    label. A new **Ignored faces** card lists them, with **Stop ignoring**.
  - A label that's already an enrolled person is refused, so a member of the
    household can't be ignored by accident.
- Camera tiles now read e.g. `2 faces (+1 ignored)`, and each camera's sensor
  gained an `ignored_faces` attribute. Ignored faces no longer count toward
  `faces` or push a camera into the `unknown` state.
- Added tests for the ignore list and the recognition pipeline
  (`python -m pytest local_faces/tests`).
