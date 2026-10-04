# HiBy R1 wireless sync — working instructions

## What this project is

Custom firmware that adds an `rsync` daemon to a HiBy R1 music player, plus a
Docker service that syncs a music library and podcasts to it over WiFi. See
`README.md` for the overview and `docs/` for the evidence behind every step.

Personal addresses and setup, if present, are in `CLAUDE.local.md`
(gitignored). Never copy anything from it into a tracked file.

## Hard constraints — do not violate

1. **Never write to the player's `book` folder.** The design makes this
   structurally impossible: rsyncd exposes only the `music` and `podcasts`
   modules. Keep it that way rather than relying on `--exclude`. Never add a
   module that points at the card root.
2. **A solution without list + delete is not acceptable.** The music mirror
   uses `rsync --delete`; podcast cleanup removes old episodes. Upload-only
   transports were rejected for this reason — do not resurrect them.
3. **Never run a USB sync and the wireless sync against the same card.** They
   disagree about exFAT timestamps and undo each other's work
   (`docs/03-usb-sync.md`).
4. **Be honest about dead ends.** "Not feasible, here's why" is a good outcome.

## Things a new session must know

1. **The firmware file on the card must be named `R1.upt`.** Any other name
   gives "no firmware update file found". The stock rollback image needs
   renaming too. Proof in `docs/09-flash-and-verify.md`.
2. **ADB is opt-in.** Create `enable_adb` on the card to get a root shell on
   TCP 5555 (no authentication — remove it afterwards). No reboot needed; the
   supervisor checks every 15 s.
3. **The server IP is baked into the firmware** at build time
   (`SERVER_IP=... scripts/build-firmware.sh`). Changing servers means a
   rebuild and reflash.
4. **`max connections = 1` on the player.** Anything that talks to it —
   previews, listings, probes — must share the sync's lock.

## Working style

- Verify claims against the firmware or the device; do not trust vendor docs.
  Vendor docs claim DLNA and AirPlay — both are inactive in practice.
- The firmware is the source of truth and can be re-extracted offline at any
  time (`scripts/unpack-firmware.sh`). Reading it costs nothing.
- Prefer evidence over inference, and say which one you have. The `docs/`
  files mark every claim as verified or assumed — preserve that distinction.
