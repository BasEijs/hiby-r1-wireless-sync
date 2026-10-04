#!/bin/bash
# Download and unpack HiBy R1 v1.6 stock firmware. Read-only, touches no device.
# macOS: bsdtar reads the .upt ISO directly, so 7z is NOT needed.
# Requires: squashfs-tools with LZO  ->  brew install squashfs
set -euo pipefail

WORK="${1:-./fw}"
URL="https://raw.githubusercontent.com/hiby-modding/hiby_os_crack/main/r1/firmware/original/r1%28v1.6%29.upt"
EXPECT_MD5="9c8b3a941dc2324ed6a641760928959c"
EXPECT_SIZE=37507072

mkdir -p "$WORK"; cd "$WORK"

if [ ! -f r1.upt ]; then
  echo "==> downloading stock v1.6 (~40MB)"
  curl -fL -o r1.upt "$URL"
fi

echo "==> extracting ISO"
rm -rf ex && mkdir -p ex
bsdtar -xf r1.upt -C ex

echo "==> concatenating squashfs chunks in numeric order"
ls ex/ota_v0/rootfs.squashfs.* \
  | sed 's/.*rootfs\.squashfs\.\([0-9]*\)\..*/\1 &/' \
  | sort -n | awk '{print $2}' > order.txt
xargs cat < order.txt > rootfs.squashfs.all

size=$(stat -f%z rootfs.squashfs.all 2>/dev/null || stat -c%s rootfs.squashfs.all)
md5=$(md5 -q rootfs.squashfs.all 2>/dev/null || md5sum rootfs.squashfs.all | cut -d' ' -f1)
[ "$size" = "$EXPECT_SIZE" ] || { echo "SIZE MISMATCH: $size != $EXPECT_SIZE"; exit 1; }
[ "$md5" = "$EXPECT_MD5" ]   || { echo "MD5 MISMATCH: $md5 != $EXPECT_MD5"; exit 1; }
echo "    checksum matches vendor manifest - genuine firmware"

echo "==> unpacking rootfs"
rm -rf rootfs
unsquashfs -d rootfs rootfs.squashfs.all > unsquashfs.log 2>&1
echo "    rootfs at $(pwd)/rootfs"

cat <<'TIPS'

Useful starting points:
  rootfs/etc/init.d/                    boot scripts (rcS runs only S??*)
  rootfs/etc/init.d/T90adb              ADB, renamed by HiBy so it never runs
  rootfs/usr/resource/set_functions.json  {"about":0} disables the easter egg
  rootfs/usr/bin/sys_server             owns port 4001 (no file operations)
  rootfs/usr/bin/adbd                   falls back to TCP 5555 with no USB gadget

NOTE: unsquashfs without sudo loses ownership/permissions. That is fine for
reading. A working REPACK needs sudo to preserve them.
TIPS
