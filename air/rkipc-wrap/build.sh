#!/bin/bash
# Vima: preklad rkipc s wrapem mimo SDK (zdroj src/, build build/), spoustet v distroboxu luckfox.
# Priznaky z ~/luckfox-pico/project/app/rkipc/build/CMakeCache.txt (posledni build rkipc pro desku).
set -e
D=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$D/build" && cd "$D/build"
cmake "$D/src" -DCMAKE_C_COMPILER=/home/mikes/luckfox-pico/tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf/bin/arm-rockchip830-linux-uclibcgnueabihf-gcc -DCMAKE_CXX_COMPILER=/home/mikes/luckfox-pico/tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf/bin/arm-rockchip830-linux-uclibcgnueabihf-g++ \
  -DCMAKE_INSTALL_PREFIX="$D/out" -DCMAKE_COLOR_MAKEFILE=OFF -DCMAKE_SYSTEM_NAME=Linux \
  -DCOMPILE_FOR_RV1106_IPC=ON -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS="-I /home/mikes/luckfox-pico/output/out/media_out/include -I /home/mikes/luckfox-pico/output/out/media_out/include/libdrm -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/uAPI -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/uAPI2 -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/algos -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/common -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/xcore -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/iq_parser -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/iq_parser_v2 -I /home/mikes/luckfox-pico/project/app/out/include -I /home/mikes/luckfox-pico/project/app/out/include/freetype2 -I /home/mikes/luckfox-pico/output/out/media_out/include/easymedia -L /home/mikes/luckfox-pico/output/out/media_out/lib -L/home/mikes/luckfox-pico/project/app/out/lib -D_LARGEFILE_SOURCE -D_LARGEFILE64_SOURCE -D_FILE_OFFSET_BITS=64 -Wl,-rpath-link,/home/mikes/luckfox-pico/output/out/media_out/lib:/home/mikes/luckfox-pico/output/out/media_out/root/usr/lib:/home/mikes/luckfox-pico/project/app/out/lib" \
  -DCMAKE_CXX_FLAGS="-I /home/mikes/luckfox-pico/output/out/media_out/include -I /home/mikes/luckfox-pico/output/out/media_out/include/libdrm -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/uAPI -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/uAPI2 -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/algos -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/common -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/xcore -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/iq_parser -I /home/mikes/luckfox-pico/output/out/media_out/include/rkaiq/iq_parser_v2 -I /home/mikes/luckfox-pico/project/app/out/include -I /home/mikes/luckfox-pico/project/app/out/include/freetype2 -I /home/mikes/luckfox-pico/output/out/media_out/include/easymedia -L /home/mikes/luckfox-pico/output/out/media_out/lib -L/home/mikes/luckfox-pico/project/app/out/lib -D_LARGEFILE_SOURCE -D_LARGEFILE64_SOURCE -D_FILE_OFFSET_BITS=64 -Wl,-rpath-link,/home/mikes/luckfox-pico/output/out/media_out/lib:/home/mikes/luckfox-pico/output/out/media_out/root/usr/lib:/home/mikes/luckfox-pico/project/app/out/lib" \
  -DRKIPC_CROSS_COMPILE=arm-rockchip830-linux-uclibcgnueabihf \
  -DCMAKE_FIND_ROOT_PATH="/home/mikes/luckfox-pico/project/app/rkipc/out;/home/mikes/luckfox-pico/project/app/out;/home/mikes/luckfox-pico/tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf/bin/../arm-rockchip830-linux-uclibcgnueabihf/sysroot" -DCMAKE_SYSROOT="/home/mikes/luckfox-pico/tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf/bin/../arm-rockchip830-linux-uclibcgnueabihf/sysroot" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
  -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
  -DCMAKE_NO_SYSTEM_FROM_IMPORTED=ON >/dev/null
make -j$(nproc) 2>&1 | grep -E "error|warning: .*wrap|Error|Built target" || true
B=$D/build/src/rv1106_ipc/rkipc
test -x "$B"
/home/mikes/luckfox-pico/tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf/bin/arm-rockchip830-linux-uclibcgnueabihf-strip -o "$D/rkipc-wrap" "$B"
md5sum "$B" "$D/rkipc-wrap"
