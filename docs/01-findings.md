# Findings

Every claim is marked **[verified]** (evidence in hand) or **[assumed]** (reasoned,
not proven). Preserve that distinction when adding to this file.

## Device

**[verified]** HiBy R1, firmware **v1.6** (the one test unit).
Ingenic X1600E, MIPS32r2, O32 ABI, little-endian, hard-float (`e_flags=0x70001005`
on every device binary). HiByOS = Linux 4.4.94, busybox 1.31.1. 64MB RAM.
2.4GHz WiFi only. The test unit had a ~239GB exFAT card.

## Port 4001 is a dead end — proven, not guessed

**[verified]** The single open TCP port is 4001. It is `/usr/bin/sys_server`,
started at boot by `/etc/init.d/S50sys_server`. Its full command vocabulary,
extracted from the binary:

```
WIFI:CONNECT  WIFI:SCAN  WIFI:LIST_NETWORK  WIFI:GETMACADDR  WIFI:SSID_CONNECT
WIFI:ON  WIFI:OFF  WIFI:DISCONNECT  WIFI:REMOVE  WIFI:STATUS  WIFI:AIRKISS
BT:SCAN  BT:LIST  BT:CANCEL_SCAN  BT:A2DPPROFILE
DLNA:TURN_ON  DLNA:TURN_OFF  DLNA:RESET
SHAIRPORT:TURN_ON  SHAIRPORT:TURN_OFF
MOUNT:MOUNT  MOUNT:UMOUNT  MOUNT:FORMAT  MOUNT:SETLUN
FINDABLE:START  FINDABLE:STOP
```

**There is not one file operation.** No list, no delete, no upload. `MOUNT:*`
controls the USB mass-storage LUN, not files. Reverse-engineering this protocol
could never have produced a sync transport. Do not revisit it.

Side effects worth knowing:
- Explains why probing 4001 got zero bytes: it expects a framed command and
  rejects anything else silently, with no error and no reset.
- Explains the SSDP silence: DLNA is **off** by default and must be switched on
  via `DLNA:TURN_ON`. The vendor's "DLNA/AirPlay support" is not active at rest.

## Network reconnaissance

**[verified]** Only 4001 open in the top-200 TCP range; 4000/4002/8080 refuse
cleanly, so 4001 is a real listener, not a SYN-proxy artifact. nmap's full
`--version-all` probe library got **zero bytes** back — no fingerprint at all.
An idle connection is held open 75s+ with no timeout.

The "connection reset by peer" in `reference/00-original-notes.md` does **not** reproduce;
plain `curl` now times out instead. Treat that note as stale.

**[verified]** The device answers neither unicast nor multicast SSDP, and
advertises nothing on mDNS. The only UPnP responders on the LAN are 4 Sonos
units; all `_airplay`/`_raop` instances were other devices on the LAN.

**[not done]** UDP port scan — needs root (`sudo nmap -sU`). Low value now.

## ADB exists and does what we need

**[verified]** `/usr/bin/adbd` is present: Ingenic's build of AOSP
android-tools 4.2.2. Compiled in: `file_sync_service.c` (= `adb push`/`pull`),
the shell service, `adb_auth_client.c`.

That combination satisfies the list+delete requirement:
`adb shell find` to enumerate, `adb shell rm` to delete, `adb push` to write.

### ADB over TCP — exact trigger condition

**[verified by disassembly]** In `adb_main` (see `scripts/flow.py`,
`scripts/ident.py`):

```
access("/dev/android_adb")      == 0  ->  usb_init()      [0x413824]
access("/dev/usb-ffs/adb/ep0")  == 0  ->  usb_init()      [0x413824]
otherwise                             ->  local_init(5555) [0x409a8c]
```

`0x409a8c` is `local_init`: it takes the port in `$a0` (loaded as `0x15b3` = 5555
in the `jal` delay slot) and spawns a thread via `pthread_create(&thr, attr,
0x408900, port)`. The socket error strings `"cannot bind to socket"` and
`"cannot rebind existing socket"` sit beside it in `.rodata`. `0x413824` opens
`/dev/usb-ffs/adb/ep0` — that is `usb_init`.

**So: if neither USB device node exists, adbd listens on TCP 5555.**

Three consequences:
1. `S440adb` creates `/dev/usb-ffs/adb`, and it never runs at boot (HiBy renamed
   it `T90adb` so it does not match `rcS`'s `S??*` glob). A custom init script
   that runs `adbd &` therefore lands on the TCP branch **by default**.
2. We never touch the USB gadget, so **mass storage keeps working** — the cable
   sync survives as a fallback.
3. `adbon` (easter egg) still flips adbd back to USB, giving a rescue shell.

**Gotcha:** Ingenic's build logs `"Using USB"` immediately *before* calling
`local_init(5555)`. The log string is mislabelled in their source. The code path
is unambiguous; ignore the console text.

### ADB authentication is not a problem

**[verified]** adbd has the auth client compiled in, but **no Android property
service is linked** (no `property_get`, no `__system_property`), so
`ro.adb.secure` cannot be read and auth defaults off.
**[verified]** Even if it were enforced, it reads keys from `/adb_keys` — and we
are repacking the rootfs anyway, so a public key can simply be placed there.

## Why a firmware flash is unavoidable

Two independent reasons. Either alone would force it.

### 1. ADB cannot be enabled on stock v1.6

**[verified]** `/usr/resource/set_functions.json` contains `{"about":0}` — the
About page is **disabled in stock v1.6**. No About page means no easter egg,
which means no way to reach `adbon`. The repo's own note confirms enabling it
requires a firmware edit.

There is therefore **no way to test any of this before flashing.** Accept that or
abandon the wireless route.

### 2. Nothing started by hand survives a power-off

**[verified]**
- Root filesystem is **read-only squashfs**.
- `rcS` runs only `/etc/init.d/S??*` and sources `/etc/profile.d/*.sh` — both on
  the read-only rootfs.
- `T90adb` was deliberately renamed by HiBy so it does **not** match. ADB is off
  at every boot by design.
- `crond` exists as a binary but is **never started**.
- The one writable persistent partition (`/usr/data`, ubifs, mounted by
  `S21mount_ubifs`) is read for **configuration only** — `wpa_supplicant.conf`,
  `macaddr.txt`, `disableadb`. **Nothing in it is ever executed.**

The device also powers off when idle, so anything manual dies quickly in practice.

## What the device does NOT have

**[verified]** No telnetd, no ftpd, no httpd in busybox 1.31.1 (applet list
checked). No dropbear/sshd. No rsync. `inetd`, `crond`, `thttpd`, `dmrd`,
`shairport`, `ntfs-3g`, `strace`, `lsof`, `netstat` binaries do exist.

This is why `rsync` has to be **added** to the rootfs rather than enabled.

## Firmware source

**[verified]** `github.com/hiby-modding/hiby_os_crack` — active, R1 is a
first-class target, ships stock `r1(v1.6).upt`.

Two distinct checksums, previously conflated in this file. **Corrected
2026-09-19:**

| artefact | size | md5 |
|---|---|---|
| `r1(v1.6).upt` (the ISO) | 41652224 | `494e7bfbd46d623ceb56938c042f576e` |
| `rootfs.squashfs.all` (72 chunks, reassembled) | 37507072 | `9c8b3a941dc2324ed6a641760928959c` |

`9c8b3a94…`/37507072 belongs to the **reassembled squashfs**, not the ISO. An
earlier version of this file attributed it to "the bundled image", which reads as
the `.upt` and caused a false tamper alarm during the stage-2 build.

What "vendor manifest" means, concretely: the ISO contains a zero-content marker
file named `ota_v0/ota_md5_rootfs.squashfs.9c8b3a941dc2324ed6a641760928959c` —
**HiBy's own** recorded md5 of the full squashfs, embedded in the package. The
reassembled squashfs matches it exactly.

Scope of that proof: it establishes **integrity** against HiBy's own manifest, not
**authenticity** — anyone repacking the ISO could rewrite the marker too.
Supporting evidence that it is nonetheless the real image: the repo blob is
byte-identical across all three paths it has occupied, unchanged since
2026-01-17 (`git cat-file` on each historical blob).

Unpacking on macOS does **not** need 7z — `bsdtar` reads the ISO directly.
See `scripts/unpack-firmware.sh`.

## Open unknowns

- ~~The SD card's runtime mount path.~~ **Resolved after flashing:**
  `/usr/data/mnt/sd_0` (see `docs/09-flash-and-verify.md` §2). The init script
  still discovers it from `/proc/mounts` rather than hardcoding it.
- **[unknown]** Whether the device stays awake while charging.
- **[unknown]** Real `rsync`-over-2.4GHz throughput. Incremental syncs will be
  fine; a large music addition may be slow.
