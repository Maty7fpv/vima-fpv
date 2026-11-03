#!/bin/bash
# Vima: kontrola desky po restartu s rezimem 1152x648@60 - jen cte, nic nemeni.
# Hlavni ukazatele (dmesg ma jen 16 kB a po startu ho prepise wifi ovladac, proto az na konci):
#   md5 sc3336.ko = build-B (255 Mbit/s) nebo build-A (510)    bin60 = Y
#   /proc/rkisp-vir0: Input ... 1152x648@60                     /proc/rkcif*: fps ~60, chyby nerostou
#   LSC: svisle sektory 40/41 (= tabulky 1152x648; 2304x1296 ma 81/81)
#   ini: [video.0] 1152x648, fps 60, [video.jpeg] 1152x648, [isp.0.adjustment] fps 60
D=$(cd "$(dirname "$0")/.." && pwd)
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"
MAPA=$(cd "$D/ovladac" && for f in build-*/sc3336.ko; do v=${f%/sc3336.ko}; echo "$(md5sum $f | cut -d' ' -f1)=${v#build-}"; done | tr '\n' ' ')
$SSH "MAPA='$MAPA' sh -s" <<'EOF'
echo "== ovladac"
m=$(md5sum /oem/usr/ko/sc3336.ko | cut -d' ' -f1)
v=""; for p in $MAPA; do [ "${p%%=*}" = "$m" ] && v=${p#*=}; done
if [ -n "$v" ]; then echo "sc3336.ko = varianta $v"; else echo "sc3336.ko = JINY ($m) - puvodni 30fps?"; fi
echo "bin60 = $(cat /sys/module/sc3336/parameters/bin60 2>/dev/null || echo 'neni (puvodni modul?)')"
echo "== VICAP (rkcif)"; for f in /proc/rkcif*; do [ -f "$f" ] && { echo "-- $f"; grep -iE "fps|rate|err|size|format" "$f"; }; done
sleep 5
echo "== VICAP po 5 s"; for f in /proc/rkcif*; do [ -f "$f" ] && { echo "-- $f"; grep -iE "fps|err" "$f"; }; done
echo "== ISP"; for f in /proc/rkisp-vir0 /proc/rkisp0; do [ -f "$f" ] && grep -iE "Input|Output|Interval|LSC" "$f" | head -20; done
echo "== rkipc"
if pidof rkipc >/dev/null; then
	echo "rkipc bezi"
	# registry LSC jen pri bezicim ISP (cteni vypnuteho bloku muze zablokovat sbernici)
	x=$(devmem 0xffa02244 32); y=$(devmem 0xffa02254 32)
	echo "LSC XSIZE_01=$x YSIZE_01=$y"
	yl=$(( $y & 0x3ff )); yh=$(( ($y >> 16) & 0x3ff ))
	xl=$(( $x & 0x3ff ))
	if [ $((yh - yl)) = 1 ]; then echo "LSC: tabulky pro 648 radku (svisle $yl/$yh, vodorovne $xl) OK"
	elif [ $yh = $yl ]; then echo "LSC: POZOR svisle sektory $yl/$yh = tabulky 2304x1296 nebo zadne"
	else echo "LSC: neocekavane $yl/$yh"; fi
else
	echo "rkipc NEBEZI"
fi
awk '/^\[/{s=$0} s~/^\[(video\.0|video\.jpeg|isp\.0\.adjustment)\]/ && /^(width|height|max_width|max_height|fps|src_frame_rate_num|dst_frame_rate_num|gop|buffer_size) /{print s, $0}' /userdata/rkipc.ini
echo "== zatez"; top -b -n 1 | head -12
echo "== dmesg (muze uz byt prepsany)"
dmesg | grep -iE "sc3336|data_rate_mbps|set isp clk|csi2.*err|size err|overflow" | tail -15
EOF
