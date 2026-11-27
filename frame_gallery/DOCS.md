# REFRAMED Gallery

Curated **public-domain art on your Samsung Frame TV**, changed on its own
schedule — no Google/Bing, no automation, no pile-up, no repeats, and content
you control.

## Why this instead of the older art-changers

| Old art-changer | REFRAMED Gallery |
| --- | --- |
| **Unpredictable, sometimes mature** images from Google Art | Public-domain museum art + a keyword content filter + a search to shape the collection |
| The **same pieces** over and over | Remembers the last *N* shown; never repeats until the collection is exhausted, then repeats the longest-ago piece |
| Uploads **pile up** in the art library | You choose: one image swapped in place, the last *N* days kept, or every piece kept |
| Needed an **automation** to run | A long-running service with its own interval |

## How it works

At the daily switch time (or each interval) — or when you press **Show next** on
the panel — it:

1. asks its source for a batch of works: **[reframed.gallery](https://www.reframed.gallery)**'s
   curated, Frame-ready collections by default, or the **Art Institute of
   Chicago**'s public-domain catalogue;
2. filters them (public domain, keyword blocklist, hidden pieces, not shown
   recently);
3. downloads one, checks the image is whole (a damaged file is skipped), and fits
   it to your panel (cropped to fill, or matted like a framed print);
4. pushes it to the Frame, deleting its own oldest upload once the art library
   holds as many pieces as you asked it to keep (by default, one).

The push is Art-Mode-aware: if you're watching TV it just sets the next art
without interrupting; switch to Art Mode to see it. If a scheduled change finds
nothing usable (the source is down, say), it tries again 15 minutes later rather
than waiting a day.

## Setup

1. **Install** this app (you added the repo under *Settings → Apps → ⋮ →
   Repositories*).
2. Usually **nothing to configure** — it auto-discovers your Frame from the
   Samsung TV integration. Optionally set **Art search** (e.g. `landscape`).
3. **Start** it with the TV **on** and the remote handy, and accept on the TV:
   - the one-time *"Allow this device to connect?"* pairing prompt, and
   - the **Art Store / terms** prompt the first time (the TV blocks uploads
     until these are accepted — the usual cause of a first upload failing).
4. Put the TV in **Art Mode**. A new piece appears each interval.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| **Art source** (`source`) | `reframed` | `reframed` = reframed.gallery's curated, Frame-ready public-domain set (recommended); `artic` = the Art Institute of Chicago's full CC0 catalogue. |
| **Collection** (`collection`) | `seasonal` | reframed only. `seasonal` auto-tracks the date; `weather` tracks the weather entity below; `all` = whole catalogue; or a slug like `by-the-sea`, `golden-hour`, `nocturnes-moonlight`. |
| **Hemisphere** | `north` | Flips the `seasonal` calendar for the Southern hemisphere. |
| **Weather entity** (`weather_entity`) | *(blank)* | For the `weather` collection — an HA `weather.*` entity (e.g. `weather.home`). Its condition picks a matching collection; unknown conditions fall back to the season. |
| **Art search** (`query`) | *(blank)* | Free-text search that shapes the collection: `landscape`, `impressionism`, `ukiyo-e`, `Monet`… Blank = the whole collection. |
| **Public domain only** | on | Only show CC0 works (recommended — clean licensing). |
| **Excluded keywords** | *(mature-content terms)* | Comma-separated; any work whose title/artist/tags match a listed term is skipped. Blank to disable. |
| **Change interval** | 1440 | Minutes between pieces (used when Daily switch time is blank). |
| **Daily switch time** | `04:00` | Switch once a day at this local `HH:MM`. Blank = use the interval. |
| **Fit** | `crop` | `crop` fills the panel and trims the edges; `matte` frames the whole work on a mat (nothing cropped). |
| **Mat color** | `#141414` | Background behind matted art (hex). Dark avoids glare at night. |
| **TV matte** (`tv_matte`) | `none` | `none` keeps the in-image fit; or a Samsung matte id (e.g. `modern_apricot`, `shadowbox_polar`) to have the **TV render a real mat** (art sent full-bleed). Unsupported ids fall back to none. |
| **Pieces to keep on the TV** (`library_size`) | 1 | How many pieces stay in the TV's own art library. `1` replaces yesterday's art with today's (one image, no pile-up). `7` keeps a week you can browse back through with the remote, deleting the oldest as a new one arrives. `0` keeps every piece and never deletes. Only images this app uploaded are ever removed. |
| **No-repeat memory** | 2000 | Don't repeat the last *N* pieces (0 = allow repeats). When a collection is smaller than this and everything has been shown, the piece shown longest ago comes back. |
| **Active hours** | *(blank)* | Blank = 24/7, or a local-time window like `07:00-23:00`. |
| **Panel resolution** | 3840x2160 | Match your panel (1920x1080 for 32"/pre-2021). |
| **Frame TV IP(s)** | *(blank)* | Blank = auto-discover; or comma-separated IPs to override. |
| **Frame TV MAC(s)** (`tv_mac`) | *(blank)* | Optional. MAC(s) for a **Wake-on-LAN** nudge before a push retry, so a sleeping TV still updates. Comma-separated, paired with the IPs by position. |

The sidebar **REFRAMED Gallery** panel shows the current piece with its full
details (title · artist · year · medium · movement, with Wikipedia links), a
status pill with how many TVs were reached and when art last changed, chips for
the collection (with what `seasonal`/`weather` resolved to, e.g. *seasonal ·
fall*), and three buttons: **Show next** (pick a new piece), **Re-push to TV**
(re-send the current one, handy if a TV was off or got switched away) and
**Never show this** (below).

## Showing one specific piece

Found something on [reframed.gallery](https://www.reframed.gallery) you want up
*right now* — a birthday, a holiday, a room full of guests? Paste its link into
**Show a specific piece** at the bottom of the panel and press **Show this**:

```
https://www.reframed.gallery/robert-kelsey/the-golf-links-north-berwick
```

Any form of the link works (with or without `https://`/`www.`, or just
`/artist/artwork`), and a link that isn't a reframed.gallery artwork page is
refused on the spot rather than blanking the TV.

Because you asked for this piece by name, it skips the collection, the keyword
filter and the no-repeat window — but it *is* added to the no-repeat history, so
the random picker won't come straight back to it. It stays up until the next
scheduled change (by default 04:00 the next morning), so a link pushed today is
the art for the rest of the day.

There's a **Show link** text entity for the same thing from Home Assistant — set
it to a URL and that piece goes up. Handy in an automation:

```yaml
# Put a favourite piece up every year on a birthday
triggers:
  - trigger: calendar
    entity_id: calendar.birthdays
    event: start
actions:
  - action: text.set_value
    target:
      entity_id: text.reframed_gallery_show_link
    data:
      value: https://www.reframed.gallery/robert-kelsey/the-golf-links-north-berwick
```

## Retiring a piece you don't want

Curated doesn't mean *to your taste*. When something goes up that you'd rather
not look at for the rest of the day, press **Never show this** on the panel: the
piece is added to a hidden list and a replacement is picked immediately, so the
wall is fixed in one click. Nothing else changes — the collection, the schedule
and the keyword filters stay as they are.

- The list is **permanent and local**, kept in the app's `/data` alongside the
  no-repeat history, so it survives restarts and updates.
- The panel shows how many pieces are hidden, with **Un-hide all** next to it if
  you want them back (the pieces themselves are never deleted anywhere — the
  gallery just stops offering them).
- There's a **Hide current art** button entity for the same thing from Home
  Assistant, so a dashboard tile or a voice assistant can retire a piece:

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.reframed_gallery_hide
```

- Hiding is per *artwork*, not per artist or subject. To rule out a whole theme,
  use `exclude_keywords` (which matches title, artist and collection words) or
  pick a narrower `collection`.

## Keeping past days on the TV

By default each day's piece replaces yesterday's, so the Frame's art library
holds exactly one of this app's images — tidy, but there's nothing to flick back
to. Set **Pieces to keep on the TV** (`library_size`, on the app's Configuration
tab) to keep more:

| Setting | What stays on the TV |
| --- | --- |
| `1` (default) | Today's piece only; yesterday's is deleted. |
| `7`, `30`, … | The last 7 (or 30, …) pieces; the oldest is deleted as each new one arrives. |
| `0` | Every piece, forever. Nothing is deleted. |

Browse them on the TV with the remote in Art Mode. A 4K piece takes about 4 MB
of the TV's storage, so with `0` the library grows by roughly 1.5 GB a year; if
the TV runs out of space, uploads fail and the panel shows "No TVs reached".
Lowering the number later deletes the surplus on the next change. Your own
uploads and Samsung Art Store pieces are never touched — the app only ever
deletes images it uploaded itself.

## Home Assistant entities (MQTT)

With the Mosquitto broker app installed (auto-detected), REFRAMED Gallery
exposes these over MQTT discovery:

- **Current Art** sensor — the title, with `artist`, `year`, `medium`,
  `movement`, `description`, `collection`, `matte`, `credit`, and `source`
  attributes (great for a dashboard card or TTS).
- **Next** button — change to a fresh piece now.
- **Collection** select — switch collection (incl. `seasonal` / `weather`) live.
- **Matte** select — switch the TV-rendered matte live (`off` = no TV matte).
- **Show link** text — set a reframed.gallery artwork URL to put that exact piece
  on the TV now.
- **Hide current art** button — retire the piece that's showing (it never comes
  back) and put a fresh one up.

## TV-rendered mattes

Set **TV matte** (or the HA Matte select) to a Samsung matte id and the Frame
draws a real museum mat around the art instead of the flat in-image border — the
image is sent full-bleed so it isn't double-framed. Matte ids look like
`<style>_<color>` (e.g. `shadowbox_polar`, `modern_apricot`). Which ones a TV
supports varies by model/year; if the Frame rejects an id, the push automatically
falls back to no matte rather than failing.

## Weather-aware art

Set **Collection** to `weather` and pick a **Weather entity**, and each change
maps the current condition to a fitting reframed collection — rain → nocturnes,
snow → winter, sun → summer, fog → mountains, and so on — falling back to the
season for conditions it doesn't recognise. No LLM, no weather API, no key; it
just reads the condition Home Assistant already has.

## Content safety

Three layers, all under your control:

- **Public-domain only** keeps the pool to CC0 works.
- **Art search** lets you pick benign themes (landscapes, still lifes, a specific
  movement or artist) so the whole collection fits your room.
- **Excluded keywords** vetoes anything whose museum metadata (title, artist,
  department, classification, subject) matches a word you list.

This is metadata-based, not a content rating, so it isn't infallible on its own —
but combining a focused `query` with the keyword filter makes mature imagery
extremely unlikely. Tighten `query` if you want a guaranteed-tame collection.

## Troubleshooting

- **First upload fails / `ms.channel.timeOut` / `send_image error -2`** — accept
  the **Allow** and **Art Store terms** prompts on the TV (it blocks uploads
  until you do), then restart.
- **Image is set but the TV doesn't switch to it** — it uses Art-Mode-aware
  pushing; switch the TV to Art Mode to see it.
- **"no artwork found"** — your `query` is too narrow, or everything matched a
  blocked keyword or the hidden list; broaden or clear `query`. (A collection
  that has simply shown everything repeats its longest-ago piece instead.)
- **"damaged"** in the log — the source served a broken image file. The app
  skips that piece until it restarts; nothing to do.
- **TV not found** — set **Frame TV IP(s)** manually (the Samsung TV integration
  must be configured, or pass the IP).
- **Rate-limited source** — transient; it backs off and retries next cycle. Set
  **Log level** to `debug` to see source and TV steps.

## Credits

Talks to the TV with [`samsungtvws`](https://github.com/NickWaterton/samsung-tv-ws-api).
Art via [reframed.gallery](https://www.reframed.gallery) and the
[Art Institute of Chicago API](https://api.artic.edu/docs/) (public domain /
CC0). Not affiliated with either.
