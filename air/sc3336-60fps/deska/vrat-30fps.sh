#!/bin/bash
# Vima: vrati na desce puvodni snimac 2304x1296@30 (+ IQ a rkipc ini) ze zaloh *.pred-60fps.
# Od 27. 10. jde mezi 30 a 60 fps prepinat panelem (ovladani.py obraz ...) - tenhle skript je navrat ke stavu PRED nasazenim.
# Zalohy na desce se tim spotrebuji (mv) - dalsi nasad-60fps.sh pak zazalohuje cerstvy stav.
# Kopie zaloh zustavaji na laptopu v deska/zaloha/ (a nejstarsi v deska/zaloha/prvni/).
# Kdyz nekdo behem 60fps testu zmenil na desce nektery ze 3 souboru, skript to ukaze a skonci;
# s -f zmeny zahodi a vrati zalohu i tak. Desku NErestartuje - projevi se po restartu.
# Kdyz nejede ani SSH: krajni pripad sudo ~/vima-board/flash.sh ~/vima-board/fw-krok4/update-krok4.img
set -euo pipefail
D=$(cd "$(dirname "$0")/.." && pwd)
Z=$D/deska/zaloha
FORCE=${1:-}
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"
B_KO=/oem/usr/ko/sc3336.ko
B_IQ=/oem/usr/share/iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json
B_INI=/oem/usr/share/rkipc-300w.ini
FILES="$B_KO $B_IQ $B_INI"

$SSH "for f in $FILES; do [ -e \$f.pred-60fps ] || { echo \"chybi zaloha \$f.pred-60fps\"; exit 1; }; done" \
	|| { echo "Nic nevraceno."; exit 1; }

if [ -f "$Z/nahrano.md5" ] && [ "$FORCE" != -f ]; then
	now=$($SSH "md5sum $FILES" | cut -d' ' -f1)
	if [ "$now" != "$(cat "$Z/nahrano.md5")" ]; then
		echo "POZOR: na desce se od nasazeni zmenil nektery soubor (proti deska/zaloha/nahrano.md5):"
		paste <(echo "$FILES" | tr ' ' '\n') <(cat "$Z/nahrano.md5") <(echo "$now")
		$SSH "cat $B_INI" | diff -u "$D/deska/rkipc-300w.ini.nahrat" - || true
		echo "Tyto zmeny by se navratem ztratily. Prenes je rucne do zalohy, nebo spust: $0 -f"
		exit 1
	fi
fi

$SSH "set -e; for f in $FILES; do mv -f \$f.pred-60fps \$f; done; sync"
ok=1
for f in $FILES; do
	n=$(basename $f).pred-60fps
	r=$($SSH "md5sum $f" | cut -d' ' -f1)
	l=$(md5sum "$Z/$n" | cut -d' ' -f1)
	if [ "$r" = "$l" ]; then echo "vraceno  $f"; else echo "NESEDI   $f (deska $r, zaloha na laptopu $l)"; ok=0; fi
done
rm -f "$Z/nahrano.md5" "$Z/nahrano.varianta"
[ $ok = 1 ] || { echo "CHYBA: nektery soubor nesedi se zalohou na laptopu"; exit 1; }
# zaloha nemusi byt 30 fps (napr. nasazeno, kdyz uz panel prepnul rezim na 60) -> upozornit
ko=$($SSH "md5sum $B_KO" | cut -d' ' -f1)
[ "$ko" = 58bc20e2aee467189d873e7647d5023f ] || echo "POZOR: vraceny sc3336.ko neni puvodni 30fps ($ko) - po restartu pobezi rezim 60; na 30 fps prepni panelem: ovladani.py obraz 1280x720@30"
echo "Vraceno, zalohy na desce spotrebovany. Projevi se po restartu desky: $SSH reboot"
