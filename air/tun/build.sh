#!/bin/bash
# Vima: tun.ko jako externi modul pro jadro desky (5.10.160) - jadro se nemeni, staci insmod.
# Zdroj = drivers/net/tun.c z SDK, stavi se proti sysdrv/source/objs_kernel (stejny .config jako bezici jadro).
set -e
cd "$(dirname "$0")"
cp ~/luckfox-pico/sysdrv/source/kernel/drivers/net/tun.c .
TC=$HOME/luckfox-pico/tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf/bin/arm-rockchip830-linux-uclibcgnueabihf-
make -C $HOME/luckfox-pico/sysdrv/source/objs_kernel ARCH=arm CROSS_COMPILE=$TC M=$PWD modules
${TC}strip --strip-debug tun.ko
cp tun.ko $HOME/luckfox-pico/project/cfg/BoardConfig_IPC/overlay/overlay-vima/lib/modules/5.10.160/extra/tun.ko
echo "tun.ko -> overlay-vima/lib/modules/5.10.160/extra/"
