#!/bin/sh
# Build static rsync for HiBy R1 (Ingenic X1600E: MIPS32r2, O32, little-endian).
# Runs inside muslcc/x86_64:mipsel-linux-musl. /work is the build dir.
#
# -march=mips32r2  match the device ISA (default would be MIPS-I)
# -mabi=32         O32, as every device binary uses
# -fno-pie/-no-pie plain ET_EXEC. A static-PIE self-relocates at startup and
#                  MIPS static-PIE on Linux 4.4 is not trustworthy.
# -static          device glibc 2.22 becomes irrelevant
set -e
apk add --no-cache make >/dev/null
cd /work
rm -rf rsync-3.4.1
tar xzf rsync-3.4.1.tar.gz
cd rsync-3.4.1
./configure --host=mipsel-linux-musl \
  --disable-xxhash --disable-zstd --disable-lz4 \
  --disable-xattr-support --disable-acl-support \
  --disable-openssl --disable-md2man --disable-simd --disable-asm \
  CC=gcc \
  CFLAGS="-Os -march=mips32r2 -mabi=32 -fno-pie" \
  LDFLAGS="-static -no-pie" > /work/configure.log 2>&1
make -j2 > /work/make.log 2>&1
cp rsync /work/rsync-mipsel.debug
strip -s -o /work/rsync-mipsel /work/rsync-mipsel.debug
echo BUILD_OK
