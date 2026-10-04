#!/bin/bash
# Container side of build-firmware.sh: add the three modifications to the
# unpacked rootfs and repack it into /work/fw/r1-netsync.upt.
set -euo pipefail
export TERM=xterm    # repack.sh calls tput

ROOT=/work/fw/rootfs

if grep -q '@SERVER_IP@' /work/S91netsync; then
	echo "S91netsync still holds the @SERVER_IP@ placeholder - run build-firmware.sh"
	exit 1
fi

echo "### STAGING ###"

# 1. the static rsync built in stage 1
install -m 755 -o root -g root /work/rsync-mipsel "$ROOT/usr/bin/rsync"
echo "rsync:            $(ls -l "$ROOT/usr/bin/rsync" | awk "{print \$1, \$5}")"

# 2. the init script (no .sh extension: rcS sources *.sh and would hang)
install -m 755 -o root -g root /work/S91netsync "$ROOT/etc/init.d/S91netsync"
echo "S91netsync:       $(ls -l "$ROOT/etc/init.d/S91netsync" | awk "{print \$1, \$5}")"

# 3. re-enable the About page so the USB easter egg rescue path exists
sed -i "s/{\"about\":0}/{\"about\":1}/" "$ROOT/usr/resource/set_functions.json"
echo "set_functions:    $(grep -o "\"about\":[01]" "$ROOT/usr/resource/set_functions.json")"

echo
echo "### boot order check ###"
ls -1 "$ROOT/etc/init.d/" | grep "^S"

echo
echo "### REPACKING ###"
rm -f /work/fw/r1-netsync.upt
bash /work/repack.sh -i "$ROOT" -k /work/fw/xImage -o /work/fw/r1-netsync.upt 2>&1 | tail -6
