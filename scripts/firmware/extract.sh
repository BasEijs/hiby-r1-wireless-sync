#!/bin/bash
# Container side of build-firmware.sh: unpack the stock image into /work/fw.
# Runs as root in ubuntu:22.04, so unsquashfs keeps ownership and modes -
# a repack from a non-root unpack would produce a broken rootfs.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq libarchive-tools squashfs-tools genisoimage ncurses-bin file >/dev/null
command -v mkisofs >/dev/null || ln -sf "$(command -v genisoimage)" /usr/local/bin/mkisofs

cd /work
rm -rf fw && mkdir -p fw/ex && cd fw
bsdtar -xf /work/stock-v1.6.upt -C ex

# The .upt is an ISO holding the rootfs and kernel as numbered 512k chunks,
# named <part>.<n>.<md5>. Reassemble in numeric order - a plain glob would
# put chunk 10 before chunk 2.
join() {
	ls ex/ota_v0/"$1".* | sed "s/.*$1\.\([0-9]*\)\..*/\1 &/" \
		| sort -n | awk '{print $2}' | xargs cat > "$2"
}
same() {    # file, size, md5 - both from HiBy's own manifest in the ISO
	s=$(stat -c%s "$1"); m=$(md5sum "$1" | cut -d' ' -f1)
	[ "$s $m" = "$2 $3" ] || { echo "MISMATCH: $1 is $s/$m, expected $2/$3"; exit 1; }
	echo "$1: $s bytes, md5 $m - matches stock"
}

join rootfs.squashfs rootfs.squashfs.all
join xImage xImage
same rootfs.squashfs.all 37507072 9c8b3a941dc2324ed6a641760928959c
same xImage 3731520 022410af2bb16150f9597d14098dfe42

unsquashfs -d rootfs rootfs.squashfs.all > unsquashfs.log 2>&1 \
	|| { tail -5 unsquashfs.log; exit 1; }
echo "rootfs unpacked"
