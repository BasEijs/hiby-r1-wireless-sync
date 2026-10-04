#!/bin/bash
# Build the modified HiBy R1 firmware from the stock v1.6 image.
#
#   SERVER_IP=192.168.1.10 scripts/build-firmware.sh [build-dir]
#
# SERVER_IP  the machine that will run the sync. The player's rsync daemon
#            accepts connections from this address only, and asks it for syncs.
# TIDAL_TRIGGER=0
#            if you use Tidal on the player. Opening Tidal is one of the two
#            on-device sync gestures (docs/08-triggering.md), so it would fire
#            on every visit.
#
# Needs an x86_64 Linux host with Docker, curl and coreutils. Every step runs
# in a throwaway container, nothing is installed on the host, and the player
# is never touched. The result is <build-dir>/R1.upt - already the one name
# the player's updater accepts.
set -euo pipefail

: "${SERVER_IP:?set SERVER_IP to the address of the machine that will run the sync}"
[[ $SERVER_IP =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "SERVER_IP must be an IPv4 address" >&2; exit 1; }
TIDAL_TRIGGER="${TIDAL_TRIGGER:-1}"

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
mkdir -p "${1:-$REPO/build}"
WORK="$(cd "${1:-$REPO/build}" && pwd)"

# hiby-modding/hiby_os_crack, pinned to the commit this was built from.
CRACK=https://raw.githubusercontent.com/hiby-modding/hiby_os_crack/8d6bb52e9bb82dae2a3dd0158f31b556ddd35cfa
STOCK_MD5=494e7bfbd46d623ceb56938c042f576e
RSYNC_URL=https://download.samba.org/pub/rsync/src/rsync-3.4.1.tar.gz
RSYNC_SHA256=2924bcb3a1ed8b551fc101f740b9f0fe0a202b115027647cf69850d65fd88c52

MUSL=muslcc/x86_64:mipsel-linux-musl
UBUNTU=ubuntu:22.04

check() {   # file, md5|sha256, expected
	got=$("$2sum" "$1" | cut -d' ' -f1)
	[ "$got" = "$3" ] || { echo "CHECKSUM MISMATCH: $1 is $got, expected $3" >&2; exit 1; }
}
fetch() { [ -f "$WORK/$2" ] || curl -fL -o "$WORK/$2" "$1"; }

echo "==> downloads (cached in $WORK)"
fetch "$CRACK/r1/firmware/original/r1%28v1.6%29.upt" stock-v1.6.upt
check "$WORK/stock-v1.6.upt" md5 "$STOCK_MD5"
fetch "$CRACK/scripts/repack.sh" repack.sh
fetch "$RSYNC_URL" rsync-3.4.1.tar.gz
check "$WORK/rsync-3.4.1.tar.gz" sha256 "$RSYNC_SHA256"
cp "$HERE"/firmware/*.sh "$WORK/"

echo "==> stage 1: static mipsel rsync"
if [ ! -f "$WORK/rsync-mipsel" ]; then
	docker run --rm -v "$WORK:/work" "$MUSL" sh /work/build-rsync-mipsel.sh
fi

echo "==> rendering S91netsync for $SERVER_IP"
sed "s/@SERVER_IP@/$SERVER_IP/g" \
	"$REPO/firmware/rootfs-overlay/etc/init.d/S91netsync" > "$WORK/S91netsync"
if [ "$TIDAL_TRIGGER" = 0 ]; then
	sed -i 's|^TRIGGER_TIDAL=.*|TRIGGER_TIDAL=|' "$WORK/S91netsync"
	echo "    Tidal trigger disabled"
fi

echo "==> stage 2: unpack, stage, repack, verify"
docker run --rm -v "$WORK:/work" -e HOST_IDS="$(id -u):$(id -g)" "$UBUNTU" bash -c '
	set -e
	trap "chown -R \$HOST_IDS /work; chmod -R u+w /work" EXIT
	bash /work/extract.sh
	bash /work/stage-and-repack.sh
	bash /work/verify.sh
	cp /work/fw/r1-netsync.upt /work/R1.upt'

echo
echo "Built: $WORK/R1.upt  md5 $(md5sum "$WORK/R1.upt" | cut -d' ' -f1)"
echo "Next: docs/09-flash-and-verify.md"
