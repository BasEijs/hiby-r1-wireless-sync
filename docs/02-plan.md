# The design

Written as a plan before anything was built; updated to match what was built.
Where the build deviated, the stage docs say so.

## Why a firmware flash

The player is a USB mass storage device with no useful network service. Two
routes were weighed:

| | Pi + USB dock | **Firmware flash + rsync daemon** |
|---|---|---|
| Brick risk | none | real, recoverable via TF card |
| Testable before committing | yes | **no** (see findings §"Why a firmware flash is unavoidable") |
| Sync mechanism | real rsync on block device | real rsync over TCP |
| Speed | USB 2.0 | 2.4GHz WiFi |
| Survives a HiBy update | yes | **no**, wiped |
| Needs player awake | no | yes |
| Extra hardware | a Pi, a dock, a cable left plugged in | none |

The Pi route is the zero-risk option, and still a reasonable choice. It was
rejected here because it costs about as much as the R1 itself, and because a
player tethered to a dock is not really wireless.

## Why rsync rather than `adb push`

The rootfs gets repacked anyway, so any static MIPS binary can be added. An
`rsync` daemon on the device means the server speaks *actual rsync* to it —
`--delete`, incremental, the whole protocol. An existing rsync-based sync
script survives nearly intact instead of being rewritten around `adb push` +
`shell rm`.

Same flash, same risk, materially better result. ADB over TCP is still
included, as an opt-in rescue shell.

## Stage 1 — static `rsync` for mipsel

Target: **MIPS32r2, O32, little-endian**. Built **static** so the device's
glibc 2.22 is irrelevant, with a musl cross toolchain in a container. Result
and the two build mistakes to avoid: `docs/06-rsync-build.md`.

## Stage 2 — repack the firmware

Into the stock v1.6 rootfs:

1. `/usr/bin/rsync` — the static binary from stage 1.
2. `/etc/init.d/S91netsync` — new init script. It:
   - waits for a WiFi address and **discovers the SD card mount path**, then
     generates `/tmp/rsyncd.conf` from it
   - starts `rsync --daemon`, and stops it if the card or WiFi goes away
   - starts `adbd` only if `enable_adb` exists on the card
   - watches for the on-device sync gestures (`docs/08-triggering.md`)
   - is named `S91*` so `rcS` picks it up, after the WiFi init scripts
3. `rsyncd` modules — **only** `music` and `podcasts`. `hosts allow` limited
   to the server's IP. No module may reach anything else on the card.
4. `/usr/resource/set_functions.json`: `{"about":0}` → `{"about":1}`, so the
   easter egg gives a USB rescue shell if the WiFi side misbehaves.

Details: `docs/07-firmware-build.md`.

### Everything else on the card protects itself

rsyncd exposes **modules**, not paths. If the only modules are `music` and
`podcasts`, no client request can address any other folder at all — the test
unit keeps audiobooks in a `book` folder that the server can never see. This
is structural, not a filter: strictly safer than `--exclude`, which is one
typo from failing. **Keep this property.** Do not add a module that points at
the card root.

## Stage 3 — flash

Via the SD card, using the player's own updater. Keep the stock v1.6 image as
the rollback. Details and gotchas: `docs/09-flash-and-verify.md`.

Only after the flash do you learn whether it all works — the static analysis
was strong, but the flash is the first real proof.

## Stage 4 — server side

A container holding the rsync client plus the sync logic: `server/mp3sync/`.
Mirrors music with `--delete`; keeps podcasts to a rolling window. The player
asks for syncs itself.

The music sync is, at heart:

```
rsync -rtv --modify-window=2 --delete /srv/music/ rsync://<player-ip>/music/
```

`--modify-window=2` matters: exFAT stores timestamps at 2-second granularity,
and without it rsync may decide to recopy everything. **Always dry-run
first.**

## Porting a macOS sync script

The sync logic started life as a macOS script (`reference/mp3sync.sh`). If you
are porting your own, the macOS-specific parts were:

- `stat -f '%m %N'` (BSD) → `stat -c '%Y %n'` (GNU).
- `osascript` notifications → Home Assistant, Gotify, or nothing.
- `dot_clean` → unnecessary on Linux. Keep `--exclude='._*'` and
  `--exclude='.DS_Store'` anyway if a Mac has ever written to the card.
