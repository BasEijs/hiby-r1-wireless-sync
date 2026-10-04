# Scripts

## `build-firmware.sh` — build the modified firmware

```
SERVER_IP=192.168.1.10 scripts/build-firmware.sh [build-dir]
```

The one you need. Runs everything below in throwaway containers on an x86_64
Linux host with Docker, and leaves `R1.upt` in `build/`. Full explanation:
`docs/07-firmware-build.md`.

`firmware/` holds the steps it runs inside containers. You should not need to
call them directly:

| script | container | does |
|---|---|---|
| `build-rsync-mipsel.sh` | `muslcc/x86_64:mipsel-linux-musl` | static rsync for the R1 |
| `extract.sh` | `ubuntu:22.04` | unpack the stock image, check it against HiBy's manifest |
| `stage-and-repack.sh` | same | add rsync, `S91netsync`, the About flag; repack |
| `verify.sh` | same | re-extract the result and check it |

## `unpack-firmware.sh`

For exploring, not building: downloads stock R1 v1.6, verifies it against the vendor manifest, and unpacks the
squashfs root. Read-only; never touches the device.

```
./unpack-firmware.sh ./fw      # rootfs lands in ./fw/rootfs
```

Needs `brew install squashfs` (LZO support). `bsdtar` handles the ISO, so no 7z.

## Binary analysis (`analyze_adbd.py`, `flow.py`, `ident.py`)

These produced the ADB-over-TCP proof in `docs/01-findings.md`. They expect
`rootfs/usr/bin/adbd` relative to the working directory, so run them from
wherever `unpack-firmware.sh` put `rootfs/`.

Need capstone in a venv (macOS python is PEP 668 managed):

```
python3 -m venv venv && ./venv/bin/pip install capstone
./venv/bin/python flow.py
```

- `flow.py` — annotated disassembly of `adb_main`'s USB-vs-TCP decision, with
  `.rodata` strings resolved inline. **This is the one that shows the proof.**
- `ident.py` — identifies `local_init` (0x409a8c) and `usb_init` (0x413824).
- `analyze_adbd.py` — finds the literal 5555 and scans nearby immediates.

Careful: do **not** name any script in this directory `dis.py`. It shadows the
stdlib `dis` module that capstone imports, and capstone fails with a confusing
circular-import error.
