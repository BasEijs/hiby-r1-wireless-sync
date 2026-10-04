# Stage 1 — static `rsync` for mipsel

`scripts/build-firmware.sh` does this as its first step; you do not need to
run it separately. This page explains what it builds and why the flags are
what they are.

## Artefact

| | |
|---|---|
| path | `build/rsync-mipsel` |
| rsync | 3.4.1, protocol 32 |
| size | 798 K, stripped |
| sha256 | `c3df6b27dc769df271850964b8ac6ae2670af60557d57cf2cc9d32fd03bc743d` |
| recipe | `scripts/firmware/build-rsync-mipsel.sh`, run in `muslcc/x86_64:mipsel-linux-musl` |

**[verified]** reproducible: a clean rebuild on 2026-10-04 gave a
byte-identical binary (same sha256). Compare yours — a different hash means a
different toolchain image, not necessarily a problem, but worth knowing.

Source tarball `rsync-3.4.1.tar.gz`, sha256
`2924bcb3a1ed8b551fc101f740b9f0fe0a202b115027647cf69850d65fd88c52`.

**[verified]** GPG signature checked: **good signature** from RSA-4096 key
`9FEF112DCE19A0DC7E882CB81BB24997A8535F6F`, created 2017-09-23, uids
`Andrew Tridgell <tridge60@gmail.com>` / `<andrew@tridgell.net>` — rsync's
original author. Signature made 2025-01-15.

Limit of that proof, stated plainly: the key was fetched from
`keys.openpgp.org`, so this shows the tarball was signed by the holder of that
key, **not** that the key is Tridgell's via a channel independent of the
download. `keys.openpgp.org` does confirm control of an email address before
publishing its uid, which is meaningful but is not web-of-trust. Adequate here.

3.4.1 rather than the server's 3.2.7 deliberately: 3.4.x carries the
CVE-2024-1208x fixes, and this is a daemon that will listen on the LAN.
Protocol 32 negotiates down to the server client's 31 automatically.

## Toolchain

`muslcc/x86_64:mipsel-linux-musl` (GCC 11.2.1, musl). In that image the cross
compiler is plain `/bin/gcc` — `gcc -dumpmachine` returns `mipsel-linux-musl`.
There is **no** `mipsel-linux-musl-gcc` wrapper, so `CC=gcc` must be passed
explicitly or configure fails. `make` is absent; `apk add make` supplies it.

## ABI verification

**[verified]** `readelf` on the result versus the device's binaries:

| | device | built |
|---|---|---|
| class / endian | ELF32 LSB | ELF32 LSB |
| ABI | O32 | O32 |
| ISA | MIPS32r2 | MIPS32r2 |
| FP | hard float | hard float |
| type | EXEC | EXEC |
| `e_flags` | `0x70001005` | `0x70001007` |

No dynamic section, no INTERP segment — genuinely static.

The `e_flags` differ in **one bit: `0x2` = `EF_MIPS_PIC`**, set because musl
compiles with `-mabicalls`. The kernel does not act on that flag at exec time;
it matters only when the linker combines objects, and nothing here is being
combined. **[assumed]** harmless — not yet proven on hardware.

### Two earlier build mistakes, for the record

1. No `-march` → GCC defaulted to **MIPS-I** (`e_flags 0x1007`, `mips1`).
2. This GCC defaults to **PIE** → the first binary was a `static-pie` (`Type: DYN`,
   with a dynamic section). MIPS static-PIE self-relocates at startup and is not
   trustworthy on Linux 4.4.

Both fixed by `-march=mips32r2 -mabi=32 -fno-pie` + `LDFLAGS="-static -no-pie"`.
Do not drop those flags.

## It runs

**[verified]** Executed under `qemu-mipsel` on the server — so the binary is
proven to start and parse arguments *before* any firmware work:

```
rsync  version 3.4.1  protocol version 32
```

Daemon mode is compiled in (`--daemon`, `rsyncd.conf`, `hosts allow`,
`max connections` all present in the binary).

## Capabilities — what is in and what is out

In: 64-bit files/inums/timestamps, symlinks, symtimes, hardlinks, atimes,
inplace, append, iconv, prealloc, stop-at. Checksums md5/md4.

Out, **intentionally**: ACLs, xattrs, zstd/lz4/xxhash, openssl.

Out, as a **cross-compile side effect** — configure could not run its test
programs:

1. **no IPv6** — irrelevant, the device is IPv4-only on this LAN.
2. **no socketpairs** — used for *local* transfers; this daemon only serves TCP.

Neither blocks the design. **[assumed]**, on reading rsync's own usage of both.

## Carry into stage 2

Use **numeric** `uid`/`gid` in `rsyncd.conf`. This is static musl with no NSS, so
name lookups depend on `/etc/passwd` alone. Numeric values avoid the question.
