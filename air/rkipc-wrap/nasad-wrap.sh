#!/bin/bash
# Vima: rkipc s rezimem wrap (ISP pise hlavni proud po radcich do kruhoveho bufferu a VENC koduje
# uz behem zapisu) - nasazeni jen do /oem, firmware beze zmeny. Zdroj src/, patch video-wrap.patch.
#   ./nasad-wrap.sh zap [buffer_line]  novy rkipc + enable_wrap = 1 (vychozi buffer_line 256);
#                                      wrap_max_fps podle rezimu snimace (60 -> 55, 30 -> 0 = wrap nikdy)
#   ./nasad-wrap.sh vyp                novy rkipc + enable_wrap = 0 (chova se jako puvodni, jen meri)
#   ./nasad-wrap.sh vrat               puvodni rkipc ze zalohy *.pred-wrap (spotrebuje ji) a z /oem ini jen smaze
#                                      klice wrapu (zbytek ini patri aktualnimu rezimu snimace - neprepisovat)
#   ./nasad-wrap.sh lat                mereni na desce: cas vydani snimku z VENC - PTS z VI
# Zalohy: na desce /oem/usr/bin/rkipc.pred-wrap a $B_INI.pred-wrap (jen poprve), kopie v zaloha/.
# Projevi se po restartu desky - skript NErestartuje (ssh luckfox reboot).
# Pozn.: vrat-30fps.sh pak hlasi zmenu ini (nahrano.md5) - wrap klice by s -f zmizely.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"
B_BIN=/oem/usr/bin/rkipc
B_INI=/oem/usr/share/rkipc-300w.ini
ORIG_MD5=02769b57e6457c7353174dbcd49efcf5   # rkipc na desce pred wrapem (stripped, s rk_video_request_idr)
NEW=$D/rkipc-wrap
Z=$D/zaloha
m5() { md5sum "$1" | cut -d' ' -f1; }
rm5() { $SSH "md5sum $1" | cut -d' ' -f1; }

# wrap jen do tohoto fps snimace (vic = snimac nema mezi snimky pauzu a kodér vynecha kazdy druhy snimek);
# stejne hodnoty jako REZIMY[..]["wrap_max"] ve vima-ctl.py. Podle /oem ini, se kterym deska nabehne
# (video.0 max_height 648 = rezim 60), ne podle prave beziciho modulu.
wrap_max() { $SSH "cat $B_INI" | awk '/^\[/{s=$0} s=="[video.0]" && /^max_height[ \t]*=/{split($0,a,"="); h=a[2]+0} END{print (h > 0 && h <= 648) ? 55 : 0}'; }

ini_set() {   # $1 = enable_wrap, $2 = buffer_line, $3 = wrap_max_fps (prazdne = nechat jak je)
	local t; t=$(mktemp -d)
	$SSH "cat $B_INI" > "$t/ini"
	grep -qx '\[video.source\]' "$t/ini" || { echo "CHYBA: v $B_INI chybi [video.source]"; exit 1; }
	awk -v W="$1" -v L="$2" -v M="${3:-}" '
	function flush() { if (sec) { if (!sw) print "enable_wrap = " W; if (L != "" && !sl) print "buffer_line = " L; if (M != "" && !sm) print "wrap_max_fps = " M } sec = 0 }
	/^\[/ { flush(); sec = ($0 == "[video.source]"); sw = sl = sm = 0; print; next }
	sec && /^enable_wrap[ \t]*=/ { print "enable_wrap = " W; sw = 1; next }
	sec && /^buffer_line[ \t]*=/ { if (L != "") print "buffer_line = " L; else print; sl = 1; next }
	sec && /^wrap_max_fps[ \t]*=/ { if (M != "") print "wrap_max_fps = " M; else print; sm = 1; next }
	{ print }
	END { flush() }' "$t/ini" > "$t/ini.new"
	$SSH "cat > $B_INI.tmp" < "$t/ini.new"
	[ "$(rm5 $B_INI.tmp)" = "$(m5 "$t/ini.new")" ] || { echo "CHYBA prenosu ini"; exit 1; }
	$SSH "mv $B_INI.tmp $B_INI && sync"
	{ diff -u "$t/ini" "$t/ini.new" || true; } | grep '^[-+][a-z]' || echo "ini beze zmeny"
	rm -rf "$t"
}

zalohuj() {
	mkdir -p "$Z"
	local cur; cur=$(rm5 $B_BIN)
	if $SSH "[ -e $B_BIN.pred-wrap ]"; then return; fi
	[ "$cur" = "$ORIG_MD5" ] || { echo "CHYBA: rkipc na desce je $cur, cekal jsem $ORIG_MD5 - nic nemenim"; exit 1; }
	$SSH "cp -p $B_BIN $B_BIN.pred-wrap && cp -p $B_INI $B_INI.pred-wrap && sync"
	$SSH "cat $B_BIN.pred-wrap" > "$Z/rkipc.pred-wrap"
	$SSH "cat $B_INI.pred-wrap" > "$Z/rkipc-300w.ini.pred-wrap"
	[ "$(m5 "$Z/rkipc.pred-wrap")" = "$ORIG_MD5" ] || { echo "CHYBA kopie zalohy"; exit 1; }
	[ "$(m5 "$Z/rkipc-300w.ini.pred-wrap")" = "$(rm5 $B_INI.pred-wrap)" ] || { echo "CHYBA kopie zalohy ini"; exit 1; }
	echo "zalohovano: $B_BIN.pred-wrap, $B_INI.pred-wrap (+ $Z)"
}

nahraj_rkipc() {
	[ "$(rm5 $B_BIN)" = "$(m5 "$NEW")" ] && { echo "rkipc s wrapem uz na desce je"; return; }
	$SSH "cat > $B_BIN.tmp" < "$NEW"
	[ "$(rm5 $B_BIN.tmp)" = "$(m5 "$NEW")" ] || { echo "CHYBA prenosu rkipc"; $SSH "rm -f $B_BIN.tmp"; exit 1; }
	# mv = nove inode, bezici rkipc si drzi stare
	$SSH "chmod 755 $B_BIN.tmp && mv $B_BIN.tmp $B_BIN && sync"
	echo "nahran rkipc $(m5 "$NEW")"
}

case "${1:-}" in
zap)  zalohuj; nahraj_rkipc; ini_set 1 "${2:-256}" "$(wrap_max)" ;;
vyp)  zalohuj; nahraj_rkipc; ini_set 0 "" ;;
vrat)
	$SSH "[ -e $B_BIN.pred-wrap ]" || { echo "na desce chybi zaloha $B_BIN.pred-wrap"; exit 1; }
	$SSH "mv -f $B_BIN.pred-wrap $B_BIN && sync"
	[ "$(rm5 $B_BIN)" = "$ORIG_MD5" ] && echo "vracen puvodni rkipc" || echo "POZOR: rkipc po navratu nesedi"
	# ini: jen pryc klice wrapu (stara zaloha ini muze patrit jinemu rezimu snimace)
	t=$(mktemp -d)
	$SSH "cat $B_INI" > "$t/ini"
	awk '/^\[/{s=$0} s=="[video.source]" && /^(enable_wrap|buffer_line|wrap_max_fps)[ \t]*=/{next} {print}' "$t/ini" > "$t/ini.new"
	$SSH "cat > $B_INI.tmp" < "$t/ini.new"
	[ "$(rm5 $B_INI.tmp)" = "$(m5 "$t/ini.new")" ] || { echo "CHYBA prenosu ini"; exit 1; }
	$SSH "mv $B_INI.tmp $B_INI && rm -f $B_INI.pred-wrap && sync"
	{ diff -u "$t/ini" "$t/ini.new" || true; } | grep '^[-+][a-z]' || echo "ini bez klicu wrapu uz bylo"
	rm -rf "$t"
	;;
lat)  $SSH "grep -E 'wrap|buffer_line' /userdata/rkipc.ini; cat /tmp/vima-venc-lat.txt 2>/dev/null || echo 'zatim zadne mereni'; tail -5 /tmp/vima-rkipc.log 2>/dev/null" ;;
*)    sed -n 2,9p "$0"; exit 1 ;;
esac
[ "${1}" = lat ] || echo "Projevi se po restartu: ssh luckfox reboot"
