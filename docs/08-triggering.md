# How a sync is triggered

## The short version

**Open the Tidal app on the player.** Within ~15 s it asks the server for a
sync. Editing the `SYNC` playlist works too.

Connecting to WiFi does **not** sync. That was the original design, replaced
on 2026-09-21: joining a network is not a request to sync.

## The buttons

`hiby_player` is a closed 4.8 MB MIPS binary with **no plugin or scripting
layer** (verified: no lua/plugin/script strings). `set_functions.json` only
toggles features that already exist. A real menu entry would mean hand-patching
MIPS assembly — weeks of work, high brick risk, and lost on any firmware
update.

So instead, `S91netsync` watches for side effects of things the user does
anyway.

### 1. Opening Tidal — one tap (primary)

**[verified on device]** hiby_player touches `/data/tat` whenever the Tidal
app is opened. The contents never change, only the mtime; confirmed three
times (21:18 → 21:23 → 21:24). The file was identified because it sits beside
`/data/tidal_info` in the binary's string table.

**This works only if you never use Tidal on the player.** For someone who
does, it fires on every visit. Build with `TIDAL_TRIGGER=0` to switch it off;
the playlist gesture below still works.

### 2. Editing the `SYNC` playlist — several taps deep

**[verified on device]** the player writes each playlist to its own file,
`<card>/playlist_data/<name>.m3u`, using the firmware's `a:\` card-root
convention internally:

```
a:\Music\Artist\01. Track.flac
```

The trigger fired 29 s after a track was added, while a WiFi reconnect
seconds earlier did nothing.

### What did NOT work, and why

**HiBy Link persists nothing to disk.** Toggling it changed no file, no
process and no listening port. `/data/menu_cfg` does contain `hiby_link`, but
that file is the **pull-down menu layout**, not toggle state — it listed
`hiby_link` while the feature was off. Misreading it cost a round trip.

**DLNA/AirPlay** would have been cleaner still, since `dmrd` and `shairport`
are real daemons whose presence is trivially detectable — but neither was
observed starting during testing.

### Which gestures write the file

**[verified]** Adding a track and saving rewrites the `.m3u` — this triggers.

**[unproven]** Deleting a track appeared not to rewrite the file — after one
was deleted it was byte-identical, same 37 bytes and same mtime, and no sync
fired. But the save step was not confirmed on that attempt, so this may simply
have been an unsaved edit rather than a property of deletion. Do not rely on
it either way.

### Implementation notes

- The stamp lives in `/tmp`, a tmpfs, so it is absent at boot: the first pass
  records the current state **without** triggering. Otherwise every power-on
  would sync, which is the thing this replaces.
- The device has no `stat`, so freshness is tested with `find -newer`.
- The playlist sits at the card root, outside the `music` and `podcasts`
  modules, so only the device can see it. The server never can.

### The other paths

`AUTO_SYNC=0` stops the server's poller firing when the player appears; it
still polls, but only to show presence in the UI. The UI's **Sync now** button
and `GET /sync` both still work.

### Both funnel into one runner

`trigger.py` holds an in-process lock and `sync.sh` additionally takes
`mkdir /config/sync.lock`. Two triggers arriving together cannot produce two
concurrent syncs. This preserves behaviour 5 of `docs/03-usb-sync.md`.

## Endpoints

| path | effect |
|---|---|
| `GET /sync` | run a sync now, ignoring the cooldown |
| `GET /status` | `sync=idle\|running player=up\|down` |

## Feedback

Optional push notifications through **Home Assistant** — set `HA_URL`,
`HA_TOKEN` and `HA_SERVICE` (e.g. `notify.mobile_app_<your_phone>`). Which
events notify is configured in the web UI; see `server/mp3sync/README.md`.
**[verified]** a failing notifier cannot fail the sync (tested with a
deliberately invalid token).

Why Home Assistant: its companion app is a straightforward iOS route.
**Gotify has no iOS app**, and the alternatives (iGotify, ntfy) route
notifications through a third-party APNs relay. On Android, any of them works;
adding another notifier means a function next to the HA one in `trigger.py`.

## What is deliberately NOT a trigger

- **A timer.** The player is off most of the time; a schedule would mostly fire
  at nothing, and when it did fire it might catch the player mid-listen.
- **Home Assistant presence.** Was planned as an upgrade; not
  needed once the device asks for itself.
