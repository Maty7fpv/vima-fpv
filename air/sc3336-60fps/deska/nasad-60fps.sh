#!/bin/bash
# Vima: nahraje na desku rezim snimace 1152x648@60 (2x2 binning) - BEZ flashe, jen 3 soubory v /oem:
#   /oem/usr/ko/sc3336.ko                                      (ovladac, bin60=1 je vychozi)
#   /oem/usr/share/iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json (IQ + LSC pro 1152x648)
#   /oem/usr/share/rkipc-300w.ini                              (video.0 1152x648, fps, isp fps)
# Zalohy: na desce *.pred-60fps (bere se jen kdyz zadna neni; vrat-30fps.sh je spotrebuje, takze dalsi
# nasazeni zazalohuje cerstvy stav), na laptopu deska/zaloha/ (posledni) a deska/zaloha/prvni/ (nikdy
# neprepsane). Desku NErestartuje - zmena se projevi az po restartu (preruseni videa i wfb ->
# domluvit s druhou session). Navrat: deska/vrat-30fps.sh
#   ./nasad-60fps.sh            varianta B (MIPI 255 Mbit/s), 60 fps
#   ./nasad-60fps.sh A          varianta A (MIPI 510 Mbit/s jako dnesni 30fps rezim)
#   ./nasad-60fps.sh B 58       60fps modul, ale snimac/kodér 58 fps (vsechny 4 fps klice v ini)
#   IVS=0 ./nasad-60fps.sh B    navic vypne IVS (detekce pohybu) - pri CPU 100 %
#   ./nasad-60fps.sh D          dalsi testovaci varianty z ovladac/build-varianty.sh (C, A2, A3, D, D2, E)
set -euo pipefail
D=$(cd "$(dirname "$0")/.." && pwd)
VAR=${1:-B}
FPS=${2:-60}
[ -f "$D/ovladac/build-$VAR/sc3336.ko" ] || { echo "pouziti: $0 [A|B|C|A2|A3|D|D2|E] [fps] (chybi build-$VAR)"; exit 1; }
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"
KO=$D/ovladac/build-$VAR/sc3336.ko
IQ=$D/iq/sc3336_CMK-OT2119-PC1_30IRC-F16.json
B_KO=/oem/usr/ko/sc3336.ko
B_IQ=/oem/usr/share/iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json
B_INI=/oem/usr/share/rkipc-300w.ini
ORIG_KO_MD5=58bc20e2aee467189d873e7647d5023f   # sc3336.ko z SDK (output/out/oem/usr/ko) = naflashovany 25. 10.
Z=$D/deska/zaloha
mkdir -p "$Z/prvni"

echo "== kontrola desky"
[ "$($SSH uname -r)" = 5.10.160 ] || { echo "CHYBA: jine jadro nez 5.10.160 (vermagic modulu by nesedel)"; exit 1; }
$SSH "touch /oem/.zapis-test && rm /oem/.zapis-test" || { echo "CHYBA: /oem neni zapisovatelny"; exit 1; }
cur=$($SSH "md5sum $B_KO" | cut -d' ' -f1)
if $SSH "[ -e $B_KO.pred-60fps ]"; then
	echo "zaloha uz na desce je (predchozi nasazeni bez navratu) - nechavam ji"
elif [ "$cur" != "$ORIG_KO_MD5" ]; then
	echo "POZOR: sc3336.ko na desce neni puvodni z SDK ($cur) - pokracuji, zaloha bude tento soubor"
fi

echo "== zalohy na desce (jen kdyz zadna neni) + kopie na laptop"
$SSH "set -e; for f in $B_KO $B_IQ $B_INI; do
	[ -e \$f.pred-60fps ] && continue
	cp -p \$f \$f.pred-60fps.tmp; cmp \$f \$f.pred-60fps.tmp; mv \$f.pred-60fps.tmp \$f.pred-60fps
done; sync" || { echo "CHYBA pri zalohovani na desce - nic nenahrano"; exit 1; }
for f in $B_KO $B_IQ $B_INI; do
	n=$(basename $f).pred-60fps
	$SSH "cat $f.pred-60fps" > "$Z/$n"
	[ -e "$Z/prvni/$n" ] || cp -p "$Z/$n" "$Z/prvni/$n"
done
ls -la "$Z"

echo "== ini: aktualni z desky -> upravit jen 11 klicu (awk lokalne, FPS=$FPS)"
# z aktualniho souboru: pri opakovanem nasazeni (B -> A, 60 -> 58) zustanou zmeny, ktere mezitim udelal nekdo jiny
$SSH "cat $B_INI" > "$Z/rkipc-300w.ini.deska-pred-nasazenim"
awk -v FPS="$FPS" -v IVS="${IVS:-}" -f "$D/rkipc/ini-60fps.awk" "$Z/rkipc-300w.ini.deska-pred-nasazenim" > "$D/deska/rkipc-300w.ini.nahrat"
diff -u "$Z/rkipc-300w.ini.deska-pred-nasazenim" "$D/deska/rkipc-300w.ini.nahrat" || true

echo "== nahravam (varianta $VAR, $FPS fps)"
put() { $SSH "cat > $2.novy" < "$1"; }
put "$KO" $B_KO
put "$IQ" $B_IQ
put "$D/deska/rkipc-300w.ini.nahrat" $B_INI
md5sum "$KO" "$IQ" "$D/deska/rkipc-300w.ini.nahrat" | cut -d' ' -f1 > "$Z/nahrano.md5"
remote=$($SSH "md5sum $B_KO.novy $B_IQ.novy $B_INI.novy" | cut -d' ' -f1)
[ "$remote" = "$(cat "$Z/nahrano.md5")" ] || { echo "CHYBA: prenos poskozen - mazu .novy, na desce beze zmeny"; $SSH "rm -f $B_KO.novy $B_IQ.novy $B_INI.novy"; exit 1; }
$SSH "mv $B_KO.novy $B_KO && mv $B_IQ.novy $B_IQ && mv $B_INI.novy $B_INI && sync"
[ "$($SSH "md5sum $B_KO $B_IQ $B_INI" | cut -d' ' -f1)" = "$(cat "$Z/nahrano.md5")" ] || { echo "CHYBA: po presunu nesedi md5 - spust vrat-30fps.sh"; exit 1; }
echo "$VAR $FPS IVS=${IVS:-beze zmeny}" > "$Z/nahrano.varianta"
echo
echo "HOTOVO (varianta $VAR, $FPS fps), md5 overeno. Projevi se po restartu desky: $SSH reboot"
echo "Restart prerusi video i wfb - jen po domluve. Navrat: $D/deska/vrat-30fps.sh"
