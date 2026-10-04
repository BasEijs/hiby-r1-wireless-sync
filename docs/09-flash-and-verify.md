# Stage 3 — flash, verify, and the gotchas

Examples use `192.168.1.50` for the player and `192.168.1.10` for the server.
Use your own.

## Before you start

1. Give the player a **DHCP reservation**, so its address never changes.
2. Download the stock image as your rollback:
   `r1(v1.6).upt` from
   [hiby_os_crack](https://github.com/hiby-modding/hiby_os_crack/tree/main/r1/firmware/original),
   md5 `494e7bfbd46d623ceb56938c042f576e`. `build/stock-v1.6.upt` is the same
   file. Keep it somewhere that is not the card.
3. Charge the player. It powers off when idle; an update should not race the
   battery.

## Flash

Per the upstream
[install guide](https://github.com/hiby-modding/hiby_os_crack/blob/main/guides/INSTALLING_FIRMWARE.md):

1. Copy `build/R1.upt` to the **root of the SD card** — over USB, or with the
   card in a reader. Music can stay on the card. The name must be exactly
   `R1.upt` (§1 below).
2. On the player: *System settings → Firmware update → Via SD card → OK*.
3. It freezes for a few seconds, reboots into update mode, then boots
   normally on its own.

**If it hangs** (around 1/5 of the progress bar) **or does not boot
afterwards:** hold power to switch off, put a good image on the card as
`R1.upt` (the stock one, renamed), then hold **volume-up + power** until the
HiBy logo shows. **[assumed]** — this is the upstream failsafe; it was never
needed on the test unit, so it was never tested here.

## Check it worked

From the server, about a minute after the player has joined WiFi:

```
rsync rsync://192.168.1.50/
```

Expected — exactly two modules, nothing else:

```
music           music mirror
podcasts        podcast episodes
```

**[verified]** on the test unit after flashing:

| check | result |
|---|---|
| boots, WiFi reconnects | yes |
| port 873 (rsyncd) | open |
| port 4001 (sys_server) | open, unchanged |
| module list from the server | `music`, `podcasts` — nothing else |
| `rsync rsync://<player>/book/` | `@ERROR: Unknown module 'book'` |
| access from any other machine | `access denied` — `hosts allow` works |
| port 5555 (adbd) | closed, unless `enable_adb` is on the card |
| USB mass storage | still mounts as before |

Live `/tmp/rsyncd.conf` on the device:

```
[music]    path = /usr/data/mnt/sd_0/Music
[podcasts] path = /usr/data/mnt/sd_0/Podcasts
```

**If the module list does not answer,** connect the player over USB and read
`netsync.log` in the card root. The init script writes a boot report there —
mounts, addresses, and whether it found rsync — so a failure can be
diagnosed without a shell. For a shell, create an empty file `enable_adb` in
the card root, wait 15 s, and `adb connect 192.168.1.50:5555`. Delete
`enable_adb` afterwards: that shell is root, with no password.

**Afterwards,** delete `R1.upt` and `netsync.log` from the card.

## Gotchas found the hard way

### 1. The update file must be named `R1.upt`

**[verified by disassembly]** `hiby_player` builds the path
`sprintf(buf, "%s/sd_0/%s.upt", "/data/mnt", name)`. `name` comes from a
23-entry config getter called with **index 7**, which the JSON parser fills
from the **`device`** key of `/usr/resource/midi_config.json` — value `R1`.

Getter indices, from the jump table at `0x759440`:

| JSON key | global | getter index | value |
|---|---|---|---|
| `company` | +4672 | — | MiDi |
| **`device`** | **+4704** | **7** | **R1** |
| `ota_name` | +4728 | — | MiDi R1 |
| `firmware_name` | +5352 | 18 | midi_r1 |

Any other filename gives *"operation failed, no firmware update file found"*
(resource key `upgrade_no_file` in `exception.ini`). There is **no** wildcard
scan.

`midi_r1` is index 18 and belongs to a *different* function — the network
updater, which formats `%s:\%s.upt`. Do not confuse the two.

**The rollback image must be renamed too.** HiBy ships `r1(v1.6).upt`, which
does not match.

### 2. The card mounts at `/usr/data/mnt/sd_0`, not `/data/mnt/sd_0`

`sys_server` mounts using the literal string `/data/mnt/sd_0`, but `/data` is a
**symlink** to `/usr/data` and the kernel records the resolved path.
`/proc/mounts` therefore says `/usr/data/mnt/sd_0`.

This killed the first build: its card detection matched `^/data/mnt/sd` and
never fired, so the supervisor concluded "no card" every cycle and started
nothing. Detection is now by **filesystem type plus a `/mnt/sd` fragment**,
which holds either way. That first build is also why the boot report on the
card exists.

### 3. exFAT timestamps — the big one

**[verified]** exFAT stores wall-clock time with no timezone. Files written by
**macOS over USB** read back skewed on the device, and not by a uniform amount
(a 2 h window fixed only half of one test directory — consistent with DST).

Consequence: the first sync on the test unit wanted to re-send **all 2,989
files / 93 GB**.

But files **rsync itself writes round-trip exactly**: a probe pushed with
`-rt` came back reporting the identical mtime, and a second run transferred 0
files. So only the backlog written by another tool is affected, and only once.

**The fix is a one-time `--checksum` pass.** It compares contents instead of
times, and where only the time differs it fixes the time and moves no data
(itemised as `.f..t......`). Run it from the server, inside the sync
container so the paths match:

```
docker exec mp3sync rsync -rt --checksum --modify-window=2 --itemize-changes \
  --exclude=.DS_Store --exclude='._*' \
  /srv/music/ rsync://192.168.1.50/music/
```

No `--delete`: this pass only repairs, the normal sync does the rest. The
exact flags used on the test unit were not recorded; these are reconstructed
from the docs and the sync script. Add `--dry-run` first to see what it would
do. For podcasts, add
`--existing`, so it only repairs episodes already on the player rather than
copying the whole feed archive:

```
docker exec mp3sync rsync -rt --checksum --existing --modify-window=2 \
  /srv/podcasts/ rsync://192.168.1.50/podcasts/
```

**[verified]** on the test unit: 93 GB hashed in ~55 min at ~19 MB/s,
**2 files transferred** (the genuinely new ones), 54 MB sent instead of
93 GB. Afterwards a normal `--modify-window=2` run reported **0 to transfer,
0 to delete** across 2,989 files.

Keep the player on the charger for this — it is the heaviest thing the
player will ever do (see "Playback during a sync" below).

### 4. Filenames exFAT cannot store

**[verified]** `" * : < > ? \ |` are illegal on exFAT. The device's driver
rejects them at `mkstemp` with `Invalid argument (22)` and rsync exits 23.

On the test unit, two tracks had such names — and **neither had ever reached
the player under the old USB sync either**; it failed on them silently. The
sync now excludes the pattern, so one bad name cannot turn every run into a
reported failure. Rename such files at the source if you want them on the
player.

## Measured: playback during a sync

Under the checksum pass — the heaviest load this design ever produces — the
device shows **0% idle CPU** (36% usr / 63% sys), load 2.19, and 1.2 MB free RAM
with `kswapd` active. `hiby_player` keeps running alongside at ~9%.

**[assumed]** normal incremental syncs are much lighter (stat-only, few files)
and should not disturb playback. Not yet measured.

New files do not appear in the player until its media database is rescanned
(*Settings → update music database*).

## Other operational facts

- `max connections = 1` — only one rsync session at a time. A second attempt
  is refused, including a bare `rsync rsync://<player>/` listing. The sync
  server shares one lock between syncs, previews and listings for this reason.
- The device powers off when idle. Keep it on the charger for long operations.
