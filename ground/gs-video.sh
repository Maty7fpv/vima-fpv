#!/bin/bash
# Vima: pozemni stanice na laptopu - prijem videa z desky pres wfb-ng a zobrazeni.
# Spoustet BEZ sudo (o heslo si rekne samo): ~/vima-board/gs-video.sh [kanal]   (bez kanalu = ~/vima-board/kanal.conf)
# RX karta = wfb0 (port 3-1). Ukonceni: Ctrl+C.
[ -f /home/mikes/vima-board/kanal.conf ] && . /home/mikes/vima-board/kanal.conf
CH=${1:-${CH:-149}}
IF=wfb0
WFB=/home/mikes/wfb-ng
LOG=/home/mikes/vima-board/gs-video.log

echo "Pozemni stanice Vima: kanal $CH, karta $IF"
sudo -v || exit 1

# karta se prenastavi jen kdyz neni v monitor modu na spravnem kanalu (tunel.sh muze bezet soucasne)
case "$CH" in 1|2|3|4|5|6|7|8|9|10|11|12|13|149|153|157|161|165) ;; *) echo "Kanal $CH neni povoleny"; exit 1 ;; esac
sudo bash -c "
	ip link show $IF >/dev/null 2>&1 || { echo 'Rozhrani $IF neexistuje - je RX karta v portu 3-1?'; exit 1; }
	pkill -f '[w]fb_rx -p 0 '
	if ! { iw dev $IF info | grep -q 'type monitor' && iw dev $IF info | grep -q 'channel $CH ('; }; then
		# karta je na jinem kanalu: kdyz bezi tunel (laptop vysila), neprelazovat - kanal meni ovladani.py
		if pgrep -f '[w]fb_tx -K gs.key -f data -p 160 ' >/dev/null; then
			echo 'Bezi tunel na jinem kanalu nez $CH - kanal men pres ovladani.py kanal, nebo restartuj tunel.sh'
			exit 1
		fi
		echo 8 > /sys/module/88XXau_wfb/parameters/rtw_tx_pwr_idx_override
		ip link set $IF down
		iw dev $IF set monitor otherbss
		ip link set $IF up
		iw dev $IF set channel $CH HT20
	fi
	iw dev $IF info | grep -E 'type|channel'
" || exit 1

# wfb_rx na pozadi (statistiky do logu 5x za sekundu - z nich prijem.py hlasi kvalitu desce), video jde na UDP 5600
sudo bash -c "cd $WFB && exec ./wfb_rx -p 0 -c 127.0.0.1 -u 5600 -K gs.key -l 200 $IF" > "$LOG" 2>&1 &
RXPID=$!
trap 'sudo kill $RXPID 2>/dev/null; sudo pkill -f "[w]fb_rx -p 0 "; exit' INT TERM EXIT
sleep 1

echo "Statistiky prijmu: tail -f $LOG"
if [ -n "$VIMA_LATENCE" ]; then
	# mereni latence: misto gst-launch bezi latence.py (okno videa + automaticke mereni)
	python3 /home/mikes/vima-board/latence/latence.py "$VIMA_LATENCE" "${VIMA_VZORKY:-60}"
	exit
fi
echo "Spoustim okno s videem (zavreni okna nebo Ctrl+C = konec)..."
# prijem.py = stejne zobrazeni jako drive gst-launch + cas kazdeho snimku do snimky.log (mereni vypadku)
while true; do
	python3 -I /home/mikes/vima-board/prijem.py
	[ $? -eq 3 ] && continue   # prijem.py dostal SIGHUP (zmena nastaveni mereni) - otevrit hned znovu
	echo "Okno zavreno. Znovu otevrit? [Enter = ano, Ctrl+C = konec]"
	read -r
done
