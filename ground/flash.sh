#!/bin/bash
# Vima: naflashuje update.img do desky Luckfox Pico Pro Max.
# Spoustet se sudo. Desku sam prepne do flash rezimu:
#   - rezim zarizeni (adb, 2207:0019): adb reboot loader
#   - USB host mod (adb nejde): ssh luckfox 'reboot loader'  (USB-C desky MUSI byt v laptopu, ne v hubu)
#   - kdyz to nejde: odpojit USB-C, drzet BOOT a zapojit USB-C znovu do laptopu.
# Pouziti: sudo ~/vima-board/flash.sh [cesta/k/update.img]
#   navrat k puvodni verzi: sudo ~/vima-board/flash.sh ~/vima-board/backup-20261019/image/update.img
set -e
set -o pipefail
IMG=${1:-/home/mikes/luckfox-pico/output/image/update.img}
DIR=/home/mikes/vima-board/tools/Linux_Upgrade_Tool
UT=$DIR/upgrade_tool
SSH="sudo -u mikes ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"

[ -f "$IMG" ] || { echo "Nenalezen obraz: $IMG"; exit 1; }
echo "Obraz: $IMG ($(du -h "$IMG" | cut -f1))"

flash_mode() { lsusb | grep -E 'ID 2207:' | grep -vq 'ID 2207:0019'; }

if flash_mode; then
	echo "Deska uz je ve flash rezimu (MaskROM/Loader)."
elif lsusb | grep -q 'ID 2207:0019'; then
	# deska bezi normalne v rezimu zarizeni (adb)
	echo "Prepinam desku do flash rezimu (adb reboot loader)..."
	sudo -u mikes adb -s 6f7eaefa0aede229 reboot loader || true
	sleep 3
elif $SSH true 2>/dev/null; then
	# USB host mod: adb nejde, pouzije se SSH. Deska musi byt USB-C kablem v laptopu,
	# jinak skonci v MaskROM bez pocitace a ceka, dokud se neodpoji napajeni.
	USBDEV=$($SSH 'ls /sys/bus/usb/devices' 2>/dev/null | grep -E '^[0-9]+-[1-9]' || true)
	if [ -n "$USBDEV" ]; then
		echo "Deska ma na USB pripojene zarizeni (hub/karta) -> USB-C neni v laptopu."
		echo "Odpoj hub, zapoj do desky USB-C kabel z laptopu, pockej na SSH a spust znovu."
		exit 1
	fi
	echo "Deska je v USB host modu -> prepinam pres SSH (reboot loader)..."
	# setsid + /dev/null: dite busyboxu 'reboot <arg>' ceka na SIGTERM od init
	# a nesmi umrit na SIGPIPE/SIGHUP, az skonci SSH relace
	$SSH 'sync; setsid reboot loader </dev/null >/dev/null 2>&1 &' || true
	sleep 3
fi

echo "Cekam na desku ve flash rezimu (USB 2207:xxxx, ne 2207:0019)..."
for i in $(seq 150); do
	flash_mode && break
	sleep 1
done
if ! lsusb | grep 'ID 2207:' | grep -v 'ID 2207:0019'; then
	echo "Deska neni ve flash rezimu. Odpoj USB-C, drz tlacitko BOOT a zapoj USB-C znovu do laptopu."
	exit 1
fi

cd "$DIR"
"$UT" ld
echo "Flashuji, neodpojuj desku..."
"$UT" uf "$IMG" 2>&1 | tee /tmp/vima-flash.log
grep -q 'Upgrade firmware ok' /tmp/vima-flash.log || { echo; echo "CHYBA: flash se nepovedl (viz vyse)"; exit 1; }
chown -R mikes:mikes "$DIR" 2>/dev/null || true
echo
echo "HOTOVO - deska se restartuje. Cekam na SSH (10.42.0.2)..."
for i in $(seq 40); do
	$SSH true 2>/dev/null && { echo "SSH funguje."; break; }
	sleep 1
done
$SSH 'echo "dr_mode: $(cat /proc/device-tree/usbdrd/usb@ffb00000/dr_mode)";
	tr " " "\n" </proc/cmdline | grep coherent_pool;
	grep -h "DMA: " /var/log/messages 2>/dev/null' || echo "SSH zatim nefunguje - zkontroluj kabel ethernetu."
