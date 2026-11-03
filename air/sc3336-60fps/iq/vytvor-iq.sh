#!/bin/sh
# Vima: IQ soubor SC3336 pro rezim 1152x648 @ 55/60 fps vyrobeny z puvodniho souboru z Luckfox SDK.
#   1. LSC (stinovani objektivu) pro 1152x648
#   2. LSC pro 2304x648 (varianta D: snimac posila 2304x648, sirku zmensi ISP)
#   3. strop expozice 4 ms
# pouziti: vytvor-iq.sh <puvodni.json> <vystup.json>
# Puvodni soubor v SDK: media/isp/release_camera_engine_rkaiq_rv1106_arm-rockchip830-linux-uclibcgnueabihf/
#                       isp_iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json   (md5 f7da8d365b1f32b6523dd80e7fa1d1cf)
# Vysledek odpovida souboru na desce z 3. 11. 2026                        (md5 e96785879c4ad2eba6b486c96420dc32)
set -e
[ $# -eq 2 ] || { sed -n 2,9p "$0"; exit 1; }
D=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
python3 "$D/pridej-lsc-1152x648.py" "$1" "$T/1.json"
python3 "$D/pridej-lsc-rozliseni.py" "$T/1.json" "$T/2.json" 2304x648
python3 "$D/strop-expozice.py" "$T/2.json" "$2" 0.004
md5sum "$2"
