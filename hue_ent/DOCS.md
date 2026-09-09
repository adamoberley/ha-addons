# Hue Entertainment

Streams LedFX effects to Philips Hue Zigbee bulbs paired to **zigbee2mqtt** (no
Hue Bridge) at 20–25 fps. The naive path — one MQTT `set` per bulb per frame —
tops out around 6 fps and floods the Zigbee queue. This app instead speaks the
reverse-engineered **Hue Entertainment** protocol: one compact Zigbee frame per
zone per tick, unicast to a single *proxy* bulb that re-broadcasts to the rest.
Bulbs interpolate between targets, so 20–25 fps looks continuous.

## Requirements

- zigbee2mqtt **2.1.1 or newer** (for the `zclcommand` passthrough; any recent
  version qualifies).
- Color-capable Philips Hue bulbs on recent firmware, paired to zigbee2mqtt.
- The LedFX app (or any DDP sender) running on the same host network.

## Zones — automatic

Zones build themselves: on start the app groups your **color-capable Philips
Hue bulbs by Home Assistant area** — one zone per room — and even picks up each
room's Adaptive Lighting switch as a pause entity. A zone is capped at **10**
bulbs (a hard limit of the Zigbee frame format); white-ambiance-only bulbs are
skipped automatically.

Then open the **sidebar panel** to fine-tune the parts only you can know:

- **Pixel order** — effects sweep 1 → N across the room, so order the lights
  along the room. Hit **Blink** on any row to identify which bulb it is, and
  use ↑/↓ to reorder.
- **Proxy** — the bulb that receives the stream and re-broadcasts it to the
  rest. Every other bulb in the zone must be in direct radio range of it, so
  pick a central, always-powered bulb.
- **Target fps** — 20 is a good default; 25 is the practical ceiling (also the
  rate a real Hue Bridge streams at). Lower still looks smooth.
- **Brightness** — a global dimmer for the streamed output.
- **Pause while streaming** — entities turned **off** while the zone streams
  and back **on** afterwards (your room's Adaptive Lighting switch is
  pre-filled when it can be detected; without it, adaptive lighting will fight
  the stream).
- **Enabled** — untick rooms you never want to stream.
- **Test stream** — arms the zone right there so you can check it end to end.
- **Live numbers** — each card reports what the zone is actually doing: the DDP
  frames arriving from LedFX, the Zigbee frames going out, and each bulb's
  **signal**. See below.

Changes save to the app's data folder, apply instantly (no restart), and update
the matching LedFX device. **Rescan rooms** picks up newly paired bulbs or area
changes. Each zone's DDP port is assigned once and remembered, so LedFX devices
never churn when rooms change.

### Manual zones (advanced)

Set `auto_zones: false` (or add zones alongside — a manual zone with the same
name replaces the auto one) and define everything in the app configuration:

```yaml
zones:
  - name: Living Room
    lights:            # zigbee2mqtt friendly names, in pixel order
      - hue_living_room_bulb_1
      - hue_living_room_bulb_2
      - hue_living_room_floor_lamp
    proxy: hue_living_room_bulb_1
    fps: 20
    ddp_port: 4048
    auto_start: true
    idle_timeout_s: 30
    brightness_scale: 1.0
    pause_entities:
      - switch.adaptive_lighting_living_room
```

## LedFX setup

**Automatic.** On start the app creates one matching **DDP** device per zone in
LedFX through its API — named **Hue \<zone\>**, with the right port, pixel
count, and frame rate — so there is nothing to mirror by hand. Just open LedFX
and put an effect on the zone's device. With `auto_start` on, the zone arms as
soon as frames flow and releases the lights after `idle_timeout_s` (default
30 s) once they stop. The same timeout applies to a zone armed by hand — the HA
switch or the panel's **Test stream** — so one turned on with nothing streaming
releases the bulbs (and its pause entities) instead of holding them.

Details and knobs:

- `ledfx_url` (default `http://127.0.0.1:8888`, the LedFX app on the same
  host) — set it to a remote LedFX instance, or to an **empty string** to
  disable auto-provisioning and manage devices yourself.
- `ledfx_ddp_target` (default `127.0.0.1`) — the address LedFX sends pixels
  to, i.e. where this app runs. Only change it if LedFX runs on a different
  machine.
- Provisioning is idempotent: a device that already matches its zone is left
  untouched (effect included). If you change a zone's lights, port, or fps, its
  LedFX device is recreated to match — re-pick the effect afterwards.
- If you remove a zone, delete its old `Hue <zone>` device in LedFX yourself.
- Managing devices manually instead: any DDP sender works — point it at the
  zone's `ddp_port` with pixel count = number of lights.

## Home Assistant control

Each zone appears as a switch — named after the zone, so it shows up as
**Hue Entertainment \<zone\>** (e.g. *Hue Entertainment Living Room*) — via MQTT
discovery. Turning it on arms the zone (captures each bulb's current state,
pauses `pause_entities`, starts streaming); turning it off stops streaming and
**restores every bulb to its pre-session state**. Only one zone streams at a
time; arming a second zone stops the first.

**Off means off.** If you switch a zone off by hand while LedFX is still
sending, it stays off — it won't immediately re-arm from the live stream. It
arms again automatically only once that stream stops and a *new* one begins (or
when you turn the switch back on). So you can silence a room mid-song without
fighting the auto-start.

Stopping or restarting the app disarms every zone cleanly first, restoring the
bulbs — they won't get stranded mid-effect.

Automation ideas: turn the switch on when your media player starts and off when
it stops, or expose it on a dashboard next to your LedFX panel.

## Reading the numbers

Every zone card carries one line of live state, which is usually the whole
diagnosis:

| The line says | It means |
| --- | --- |
| `in 43.9 fps · out 24.6 fps · 19,122 frames received` | Working. LedFX is streaming and the bulbs are being driven at the target rate. |
| `no DDP yet on :4049 — point a LedFX device here` | Nothing has *ever* arrived on this zone's port. Its LedFX device is missing, disabled, or aimed at the wrong port/host. |
| `idle — last frame 74s ago` | LedFX streamed earlier and stopped (effect off, or nothing playing). Normal. |
| `armed for 12s, no DDP` | The zone is armed but nothing is arriving; it releases the bulbs after `idle_timeout_s`. |

Each bulb also shows its **signal** — the Zigbee link quality zigbee2mqtt last
reported, with a ★ on the strongest in the room. Use it as a *starting point*
when picking the proxy: link quality is measured to the coordinator rather than
between bulbs, so the strongest bulb is usually well-placed, but the proxy's real
job is reaching the *other* bulbs in the room. If a zone stutters, try the ★ bulb
as proxy, then a more central one.

Numbers update every few seconds, and a card you're editing is never
re-rendered mid-edit — unsaved changes survive the refresh.

## Troubleshooting

- **No rooms in the panel.** The panel says which of these it is:
  - *Waiting for zigbee2mqtt* — the app hasn't seen `zigbee2mqtt/bridge/devices`
    yet. Check the Z2M base topic and MQTT credentials.
  - *None of your Philips lights is assigned to an area* — assign the bulbs (or
    their light entities) to areas in **Settings → Areas**, then **Rescan rooms**.
  - *Rooms could not be read* — the Home Assistant API call failed; the app log
    has the error. **Rescan rooms** retries.
  - *Auto zones are off* — turn on `auto_zones`, or define manual `zones:`.
- **A room is missing one bulb.** White-ambiance-only bulbs can't render color
  streams, so they're listed as skipped rather than added. A zone also stops at
  10 bulbs (a hard limit of the frame format).
- **Only some rooms appear.** Discovery skips device registry entries it cannot
  read and logs them (`skipped N unreadable device registry entr(ies)`) — if one
  of your Hue bulbs is in that list, please open an issue with the log line.
- **Nothing moves.** Check the zone's live line (above). `no DDP yet` is a LedFX
  problem (wrong device/port), while `in … fps` with no `out … fps` is a Zigbee
  one — look at the proxy bulb and its signal.
- **It stutters.** Lower **Target fps** to 20, and try the ★ (strongest signal)
  bulb as the proxy. A proxy that can't reach the rest of the room drops frames
  for the whole zone.

## How it works / limits

- Uses zigbee2mqtt as a dumb relay (`zclcommand` on `<friendly_name>/set`) —
  cluster 0xFC01, manufacturer 0x100B (Signify). No custom Z2M fork, no special
  coordinator firmware; verified on a TI CC2652 (Z-Stack 3).
- ~25 updates/sec is the protocol's practical ceiling — coarser than a WLED
  strip but plenty for music-reactive room lighting.
- While a zone streams, normal commands to those bulbs still get through and
  will fight the stream — hence `pause_entities` and the state restore.
- White-ambiance-only bulbs cannot render color streams; leave them out.
