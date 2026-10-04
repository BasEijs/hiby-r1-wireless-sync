# Stage 2 — build the modified firmware

## Build it

On an x86_64 Linux host with Docker (your server is fine):

```
SERVER_IP=192.168.1.10 scripts/build-firmware.sh
```

| variable | meaning |
|---|---|
| `SERVER_IP` | **required.** The machine that runs the sync. The player's rsync daemon accepts connections from this address only, and sends its sync requests to `http://SERVER_IP:8787/sync` |
| `TIDAL_TRIGGER=0` | turn off the "open Tidal to sync" gesture — set this if you use Tidal on the player (`docs/08-triggering.md`) |

~10 minutes the first time, mostly compiling rsync. Re-runs reuse the
downloads and the rsync binary. The result is `build/R1.upt`.

What it does, in order — every step in a throwaway container, nothing
installed on the host:

1. Downloads the stock v1.6 image and HiBy's repack script from
   [hiby_os_crack](https://github.com/hiby-modding/hiby_os_crack), pinned to
   a commit, and the rsync 3.4.1 source. Checks all three against known
   checksums.
2. Builds static rsync (`docs/06-rsync-build.md`).
3. Writes your `SERVER_IP` into a copy of
   `firmware/rootfs-overlay/etc/init.d/S91netsync`.
4. Unpacks the stock image and checks rootfs and kernel against HiBy's own
   manifest (`scripts/firmware/extract.sh`).
5. Adds the three modifications and repacks
   (`scripts/firmware/stage-and-repack.sh`).
6. Re-extracts the new image the way the device will and checks it
   (`scripts/firmware/verify.sh`) — see "Round-trip verification" below.

**[verified]** on 2026-10-04, from an empty directory: the build reproduced
the rsync binary byte for byte, and the rootfs differed from the firmware
flashed on the test unit only in `S91netsync`'s comments.

**[assumed]** the container images (`muslcc/x86_64:mipsel-linux-musl`,
`ubuntu:22.04`) are not pinned by digest. If a future image breaks the build,
the checks in steps 4 and 6 should catch it before you get an image to flash.

**The server IP is baked in.** Moving the sync to another machine means a
rebuild and reflash. A DHCP reservation for the server avoids surprises.

## The three modifications

1. **`/usr/bin/rsync`** — the static mipsel binary from stage 1, 816868 bytes,
   `root:root`, mode 755.
2. **`/etc/init.d/S91netsync`** — new init script, `root:root`, mode 755.
   Source of truth is `firmware/rootfs-overlay/etc/init.d/S91netsync`; read
   it, it is commented for exactly this.
3. **`/usr/resource/set_functions.json`** — `{"about":0}` → `{"about":1}`,
   restoring the About page and therefore the easter-egg USB rescue path.

The kernel is **untouched** — byte-identical to stock, md5
`022410af2bb16150f9597d14098dfe42`.

## Boot placement

**[verified]** `rcS` globs `/etc/init.d/S??*` and runs `"$i start"`. Resulting
order:

```
... S50sys_server  S80_bt_init  S91netsync  S92_03_start_music_player
```

Two details that are easy to get wrong:

- **No `.sh` extension.** `rcS` *sources* anything matching `*.sh` in its own
  shell. A `.sh` name would have hung the boot.
- **The script returns immediately.** `rcS` is sequential, so the supervisor is
  detached with `&`. Otherwise every second spent waiting for WiFi would delay
  the music player starting.

## What S91netsync does

A supervisor loop, 15 s cycle:

1. Read the card's mount point from `/proc/mounts`. **Not hardcoded** —
   `sys_server` picks it at runtime.
2. Stop the daemon if the card is gone, a kill switch is present, or no `wlan*`
   interface has an IPv4 address.
3. Otherwise generate `/tmp/rsyncd.conf` and start `rsync --daemon --port=873`.
4. Watch for the sync gestures and, when one fires, ask the server for a sync
   (`docs/08-triggering.md`).

### Why it re-checks the mount every cycle

**This is the dangerous case.** When the player is plugged in as USB mass
storage the card is unmounted, and its mount point collapses into an empty
directory **on the internal flash**. A daemon still serving that path would
let a sync write a whole music library into a few MB of internal storage. The
supervisor kills the daemon the moment the mount disappears.

### Why `--port=873` is explicit

**[verified]** `/etc/services` exists on the device but has **no `rsync`
entry**, so `getservbyname("rsync")` would fail.

### Why numeric `uid`/`gid`

Static musl, no NSS. Name lookups would depend on `/etc/passwd` alone, so
`uid = 0` / `gid = 0` sidestep the question.

### Only two folders are reachable

`rsyncd.conf` declares exactly two modules, `music` and `podcasts`, pointing at
`<card>/Music` and `<card>/Podcasts`. rsyncd addresses **modules, not paths**,
so no client request can name any other folder on the card. `verify.sh` fails
the build if any other module appears.

### Two switches, both on the SD card

Reachable over USB mass storage without reflashing:

| file on card root | effect |
|---|---|
| `no_netsync` | do not run the rsync daemon at all |
| `enable_adb` | also start `adbd` (TCP 5555) |

## ADB is opt-in

`adbd` starts **only** if `enable_adb` exists on the card, and
`/data/disableadb` (HiBy's own opt-out) still wins.

Reason: `adbd` on TCP 5555 has no working authentication on this device
(findings §"ADB authentication is not a problem"), so starting it always would
mean **an unauthenticated root shell to anyone on the LAN**, permanently.
Opt-in keeps the rescue shell one USB cable away without leaving it open.

## The update file must be named `R1.upt`

Any other name gives *"operation failed, no firmware update file found"*.
The build already names its output `R1.upt`. The stock image, which HiBy ships
as `r1(v1.6).upt`, has to be renamed too before you can use it as a rollback.

The proof is in `docs/09-flash-and-verify.md` §1. An earlier reading of the
binary concluded `midi_r1.upt`; that was the *network* updater's name, and
it was wrong for the SD-card route.

## Round-trip verification

**[verified]** `verify.sh` re-extracts the new `.upt` and checks it the way
the device will. On the test build:

| check | result |
|---|---|
| chunks | 73 (stock: 72) |
| reassembled squashfs | 38002688 bytes |
| md5 vs its own `ota_md5_rootfs...` marker | **match** |
| kernel md5 vs stock | **identical** |
| `rsync` in repacked rootfs | ELF32 LSB **EXEC**, MIPS32r2, statically linked, stripped |
| modules declared | `[music]` `[podcasts]` only |

## Rootfs partition capacity — resolved

The rootfs grows **37507072 → 38002688 bytes, +495616 (+1.3 %)**. Whether the
NAND partition had that much slack could not be settled offline: partition
sizes live in `/proc/mtd` at runtime.

**[verified]** it fits: the image flashed and booted on the test unit. If a
future change makes it too big, the cheapest saving is `usr/resource/str/` —
ten language resource packs, of which one is needed.
