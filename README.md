# HiBy R1 wireless sync

Sync music and podcasts to a **HiBy R1** over WiFi, from a home server, with
real `rsync` — deletes included. No cable, no phone app.

What is in this repo:

- **Custom firmware.** Stock HiByOS v1.6 plus a static `rsync` daemon and an
  init script. Built by one script, verified against HiBy's own checksums.
- **A sync server.** A small Docker service that mirrors your music library,
  keeps a rolling window of podcast episodes, and has a phone-friendly web UI
  showing what a sync would push and delete.
- **The evidence.** Every claim in `docs/` is marked *verified* or *assumed*,
  including the dead ends — so you can check the reasoning before you flash.

## How it works, in one paragraph

The R1 is a Linux device, but its only open port (4001) is a control daemon
with no file operations, so it can never carry a sync. Stock v1.6 also has a
read-only root filesystem with no hook that survives a reboot — so a firmware
flash is unavoidable. Given that, the best use of the flash is to add a
**static `rsync` daemon**. The server then speaks real rsync to the player,
`--delete` and all. The daemon exposes only `Music` and `Podcasts`, so
nothing on the server can touch anything else on the card. To start a sync
you open the Tidal app on the player (one tap), or edit a playlist called
`SYNC`; the player asks the server, and the server syncs.

## Is this for you?

You need:

| | |
|---|---|
| player | a HiBy R1. Flashing installs modified **v1.6** whatever you run now |
| server | an always-on **x86_64 Linux** machine with Docker, that holds your music library locally (a NAS or home server) |
| network | 2.4 GHz WiFi, and a DHCP reservation for both the player and the server — the server IP is baked into the firmware |
| podcasts | a folder of episodes, one subfolder per show. [Podgrab](https://github.com/akhilrex/podgrab) fits; the extras assume it, the core sync does not |
| you | comfortable flashing firmware and reading a shell script |

It was built and tested on **one** R1. It works daily on that one. It has not
been tried on any other unit, firmware version or server.

## Risks — read before flashing

1. **Flashing can go wrong.** The test unit was flashed several times
   without incident. If an update fails, the upstream guide's failsafe
   (volume-up + power, with a good image on the card) reinstalls firmware.
   **[assumed]** that recovery works — it was never needed, so never tested.
2. **A HiBy firmware update wipes all of this.** Decline them, or
   rebuild after.
3. **The rsync daemon runs as root with no password.** It accepts connections
   from your server's IP only, and can write only to `Music` and `Podcasts`.
   On a LAN you trust that is fine; on someone else's WiFi, anyone who takes
   your server's IP can write to those two folders. The kill switch is a file
   called `no_netsync` on the card.
4. **ADB is a root shell with no authentication.** It is off unless you create
   `enable_adb` on the card. Remove it again when done.
5. **If your card was filled from a Mac,** the first sync will want to resend
   everything (exFAT timestamps). A one-time repair pass fixes it —
   `docs/09-flash-and-verify.md` §3. Never alternate USB and wireless syncs.

Not affiliated with HiBy. You flash at your own risk.

## Steps

1. **Read** `docs/01-findings.md`, at least the headings. ~10 min.
2. **Build** the firmware on your server (~10 min, mostly compiling rsync):
   ```
   SERVER_IP=192.168.1.10 scripts/build-firmware.sh
   ```
   Use `TIDAL_TRIGGER=0` if you actually use Tidal on the player.
   Result: `build/R1.upt`. Details: `docs/07-firmware-build.md`.
3. **Flash** it: copy `R1.upt` to the card root — the name must be exactly
   that — then *System settings → Firmware update → Via SD card*.
   Then check it worked: `docs/09-flash-and-verify.md`.
4. **Run the server:**
   ```
   cd server/mp3sync
   cp .env.example .env      # set PLAYER, MUSIC_DIR, PODCAST_DIR
   docker compose up -d --build
   ```
   Open `http://<server>:8787/` and press **Preview**. Details:
   `server/mp3sync/README.md`.
5. **First sync:** read the preview. If it wants to resend your whole library,
   do the timestamp repair first (`docs/09-flash-and-verify.md` §3).
6. **From then on:** open Tidal on the player, wait ~15 s.

## Map

| | |
|---|---|
| `docs/01-findings.md` | what the R1 is, and what was proven about it |
| `docs/02-plan.md` | the design, and the alternatives it beat |
| `docs/03-usb-sync.md` | coming from a USB sync: the timestamp trap |
| `docs/04-known-issues.md` | open issues and ideas |
| `docs/05-server.md` | what the server needs |
| `docs/06-rsync-build.md` | stage 1: static mipsel `rsync` |
| `docs/07-firmware-build.md` | stage 2: the modified firmware |
| `docs/08-triggering.md` | how a sync gets asked for |
| `docs/09-flash-and-verify.md` | stage 3: flashing, checking, and the gotchas |
| `firmware/rootfs-overlay/` | the init script added to the player |
| `scripts/` | firmware build, unpack, and binary analysis |
| `server/mp3sync/` | the sync server and its web UI |
| `server/podgrab-prune/` | age-based retention for Podgrab (optional) |
| `reference/` | the macOS USB sync this replaced |

## Credits

- [hiby-modding/hiby_os_crack](https://github.com/hiby-modding/hiby_os_crack)
  — the stock image, the repack script, and the install guide this builds on.
- [rsync](https://rsync.samba.org/), 3.4.1, built static for MIPS.
