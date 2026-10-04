#!/bin/bash
# Container side of build-firmware.sh: re-extract the new image the way the
# device will, and check the modifications landed and nothing else moved.
set -euo pipefail

cd /work/fw
rm -rf vfy && mkdir -p vfy/ex && cd vfy
bsdtar -xf ../r1-netsync.upt -C ex

join() {
	ls ex/ota_v0/"$1".* | sed "s/.*$1\.\([0-9]*\)\..*/\1 &/" \
		| sort -n | awk '{print $2}' | xargs cat > "$2"
}

echo "### VERIFY ###"
join rootfs.squashfs rootfs.squashfs.all
md5=$(md5sum rootfs.squashfs.all | cut -d' ' -f1)
marker=$(ls ex/ota_v0/ | grep ota_md5_rootfs | sed "s/ota_md5_rootfs.squashfs.//")
echo "rootfs md5:    $md5"
[ "$md5" = "$marker" ] && echo "manifest:      matches its own ota_md5 marker" \
	|| { echo "manifest:      MISMATCH ($marker)"; exit 1; }

join xImage xImage
k=$(md5sum xImage | cut -d' ' -f1)
[ "$k" = 022410af2bb16150f9597d14098dfe42 ] && echo "kernel:        identical to stock" \
	|| { echo "kernel:        CHANGED ($k)"; exit 1; }

unsquashfs -d rfs rootfs.squashfs.all > /dev/null 2>&1
printf "rsync:         "; ls -l rfs/usr/bin/rsync | awk "{print \$1, \$3\":\"\$4, \$5}"
printf "rsync type:    "; file rfs/usr/bin/rsync | cut -d, -f2-5
printf "S91netsync:    "; ls -l rfs/etc/init.d/S91netsync | awk "{print \$1, \$3\":\"\$4, \$5}"
printf "allowed host:  "; grep '^ALLOW=' rfs/etc/init.d/S91netsync
printf "about flag:    "; grep -o "\"about\":[01]" rfs/usr/resource/set_functions.json
modules=$(grep -oE "^\[[^]]+\]" rfs/etc/init.d/S91netsync | tr "\n" " ")
echo "modules:       $modules"
[ "$modules" = "[music] [podcasts] " ] \
	|| { echo "UNEXPECTED MODULES - only [music] and [podcasts] may exist"; exit 1; }
cd .. && rm -rf vfy
