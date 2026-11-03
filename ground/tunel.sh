#!/bin/bash
# Vima: obousmerny IP tunel vzduchem na laptopu - wfb_tun (wfb-tun 10.5.0.1) + wfb_tx + wfb_rx na karte wfb0.
# Deska ma 10.5.0.2 (naběhne sama, viz /etc/vima/vima.conf TUN_*). Video (gs-video.sh) muze bezet soucasne.
# Spoustet BEZ sudo (o heslo si rekne):
#   ~/vima-board/tunel.sh             - tunel
#   ~/vima-board/tunel.sh kalibrace   - navic projde vykon laptopu (index 10..max) a zapise RSSI na obou koncich
# Spousti i root pomocnika pro ovladani desky (~/vima-board/ovladani.py). Konec: Ctrl+C.
KONF=/home/mikes/vima-board/kanal.conf
[ -f "$KONF" ] && . "$KONF"
CH=${CH:-13}
IF=wfb0
WFB=/home/mikes/wfb-ng
D=/home/mikes/vima-board
# Vykon laptopove karty (stejny typ high-power modulu jako na desce), index 1-63, ~0,5 dB/krok.
# Nikdy 0 ani kladne mBm (= neomezeny tovarni vykon). Kalibrace 25. 10.: laptop o <=6 dB silnejsi nez deska
# pri stejnem indexu -> pevne stropy laptopu 2,4 GHz 38, 5,8 GHz 8 (odpovida desce 50 / 20).
: "${LAPTOP_TXPWR_IDX_2G:=38}" "${LAPTOP_TXPWR_IDX_5G:=8}" "${TUN_AGG_MS:=5}"
# Uplink (laptop->deska): kazdy paket 3x s odstupem 3 ms - karta desky casto vysila video a mezitim neprijima,
# kopie hned za sebou se ztraceji spolecne (25. 10.: n=2 bez odstupu 6,5 % ztrat pingu, n=3 bez odstupu 7,5 %).
: "${TUN_UP_FEC_N:=3}" "${TUN_UP_FEC_DELAY_US:=3000}"
# Strop toku z laptopu do tunelu (kbit/s): velky prenos jinak zabere vzduch videu (25. 10.: scp 1 MB = 141 ztracenych paketu videa)
: "${TUN_RATE_KBIT:=300}"
case "$CH" in
	1|2|3|4|5|6|7|8|9|10|11|12|13) PWR=$LAPTOP_TXPWR_IDX_2G; MAXIDX=38; KROKY="10 20 30 38" ;;
	149|153|157|161|165) PWR=$LAPTOP_TXPWR_IDX_5G; MAXIDX=8; KROKY="2 4 6 8" ;;
	*) echo "Kanal $CH neni povoleny (1-13, 149-165)"; exit 1 ;;
esac
[ "$PWR" -ge 1 ] 2>/dev/null && [ "$PWR" -le "$MAXIDX" ] || { echo "Vykon $PWR mimo povoleny rozsah 1-$MAXIDX pro kanal $CH"; exit 1; }

set_pwr() {
	sudo sh -c "echo $1 > /sys/module/88XXau_wfb/parameters/rtw_tx_pwr_idx_override && iw dev $IF set txpower fixed -${1}00" || return 1
	NOW=$(cat /sys/module/88XXau_wfb/parameters/rtw_tx_pwr_idx_override)
	echo "Vykon laptopu: index $NOW"
	[ "$NOW" = "$1" ]
}

echo "Tunel Vima: kanal $CH, karta $IF, laptop 10.5.0.1 <-> deska 10.5.0.2"
sudo -v || exit 1
sudo bash -c "
	ip link show $IF >/dev/null 2>&1 || { echo 'Rozhrani $IF neexistuje - je karta v portu 3-1?'; exit 1; }
	pkill -f '[w]fb_tx -K gs.key -f data -p 160 '; pkill -f '[w]fb_rx -p 32 '; pkill -x wfb_tun; pkill -f '[o]vladani.py pomocnik'
	for i in 1 2 3 4 5 6 7 8 9 10; do pgrep -f '[w]fb_tx -K gs.key -f data -p 160 ' >/dev/null || break; sleep 0.3; done
	# vykon pred kanalem (nejnizsi spolecny strop 8, cilovy az po prepnuti)
	echo 8 > /sys/module/88XXau_wfb/parameters/rtw_tx_pwr_idx_override || exit 1
	iw dev $IF set txpower fixed -800 || exit 1
	if ! { iw dev $IF info | grep -q 'type monitor' && iw dev $IF info | grep -q 'channel $CH ('; }; then
		ip link set $IF down
		iw dev $IF set monitor otherbss
		ip link set $IF up
		iw dev $IF set channel $CH HT20
	fi
	iw dev $IF info | grep -q 'channel $CH (' || { echo 'Karta neni na kanalu $CH'; exit 1; }
" || exit 1
set_pwr "$PWR" || { echo "Vykon se nepodarilo nastavit, tunel nespoustim"; exit 1; }

cd "$WFB" || exit 1
sudo ./wfb_tun -t wfb-tun -a 10.5.0.1/24 -c 127.0.0.1 -u 5801 -l 5800 -T "$TUN_AGG_MS" > "$D/tunel-tun.log" 2>&1 &
P1=$!
sudo ./wfb_tx -K gs.key -f data -p 160 -u 5801 -k 1 -n "$TUN_UP_FEC_N" -T 0 -F "$TUN_UP_FEC_DELAY_US" -M 1 -S 0 -L 0 -B 20 \
	-C 8101 $IF > "$D/tunel-tx.log" 2>&1 &
P2=$!
sudo ./wfb_rx -p 32 -c 127.0.0.1 -u 5800 -K gs.key $IF > "$D/tunel-rx.log" 2>&1 &
P3=$!
# root pomocnik pro ovladani.py (prepnuti kanalu a vykonu laptopu bez dalsiho hesla)
sudo python3 -I "$D/ovladani.py" pomocnik > "$D/tunel-pomocnik.log" 2>&1 &
P4=$!
trap 'echo; echo "Vypinam tunel"; sudo kill $P1 $P2 $P3 $P4 2>/dev/null; exit' INT TERM EXIT
for i in $(seq 20); do ip link show wfb-tun >/dev/null 2>&1 && break; sleep 0.5; done
sudo sysctl -q -w net.ipv6.conf.wfb-tun.disable_ipv6=1
[ "$TUN_RATE_KBIT" -gt 0 ] && sudo tc qdisc replace dev wfb-tun root tbf rate "${TUN_RATE_KBIT}kbit" burst 8kb latency 400ms \
	&& echo "Tunel z laptopu omezen na $TUN_RATE_KBIT kbit/s"
ip -br addr show wfb-tun

echo "Cekam na odpoved desky (10.5.0.2)..."
for i in $(seq 30); do ping -c 1 -W 1 10.5.0.2 >/dev/null 2>&1 && { echo "Deska odpovida vzduchem."; break; }; done

if [ "$1" = "kalibrace" ]; then
	OUT=$D/kalibrace-laptop.txt
	echo "# Kalibrace vykonu laptopu $(date '+%F %T'), kanal $CH. Uplink = laptop->deska (RSSI na desce), downlink = deska->laptop (RSSI na laptopu)" > "$OUT"
	for idx in $KROKY; do
		[ "$idx" -le "$MAXIDX" ] || break
		set_pwr "$idx"
		sleep 1
		: > "$D/tunel-rx.log.okno"
		tail -n0 -f "$D/tunel-rx.log" > "$D/tunel-rx.log.okno" &
		TP=$!
		ping -q -c 40 -i 0.25 10.5.0.2 | tail -2 | sed "s/^/idx $idx ping: /" >> "$OUT"
		kill $TP
		echo "idx $idx uplink (deska):" >> "$OUT"
		ssh -o BatchMode=yes -o ConnectTimeout=3 luckfox 'tail -n 24 /tmp/wfb_tun_rx.log | grep RX_ANT | tail -n 16' >> "$OUT" 2>&1
		echo "idx $idx downlink (laptop):" >> "$OUT"
		grep RX_ANT "$D/tunel-rx.log.okno" >> "$OUT"
		echo "  index $idx hotovo"
	done
	set_pwr "$PWR"
	echo "Kalibrace zapsana do $OUT, vykon vracen na index $PWR."
fi

echo "Tunel bezi (Ctrl+C = konec). Statistiky: $D/tunel-rx.log, $D/tunel-tx.log"
while true; do
	sleep 10
	R=$(grep PKT "$D/tunel-rx.log" | tail -1 | cut -f3)
	T=$(grep PKT "$D/tunel-tx.log" | tail -1 | cut -f3)
	echo "$(date +%T) prijem z desky [vse:bajty:dec_err:ok:fec:ztraty:...] $R | vysilani [timeouty:vstup:..:odvysilano:..] $T"
	kill -0 $P1 2>/dev/null && kill -0 $P2 2>/dev/null && kill -0 $P3 2>/dev/null || { echo "Nektery proces tunelu skoncil - zkontroluj logy v $D/tunel-*.log"; }
done
