#!/bin/bash
# Vima: ovladani desky z laptopu pres SSH (ethernet). Bez sudo.
#   ~/vima-board/deska.sh stav              - kanal, rezim, domena, posledni zaznamy logu
#   ~/vima-board/deska.sh kanal <cislo>     - prepne kanal na desce restartem (vypadek videa); za behu radeji ovladani.py kanal
#   ~/vima-board/deska.sh rezim test|video  - testovaci data, nebo video z kamery
KONF=/home/mikes/vima-board/kanal.conf
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"

stav() {
	$SSH '. /etc/vima/vima.conf
		echo "konfigurace: kanal $WFB_CHANNEL $WFB_BW, MCS $WFB_MCS, STBC ${WFB_STBC:-0}, LDPC ${WFB_LDPC:-0}, vykon 2G/5G ${WFB_TXPWR_IDX_2G:-$WFB_TXPWR_IDX}/${WFB_TXPWR_IDX_5G:-$WFB_TXPWR_IDX} (ted $(cat /sys/module/88XXau_wfb/parameters/rtw_tx_pwr_idx_override)), video=$VIDEO_ENABLE, test=$TESTGEN_ENABLE"
		iw dev wfb0 info 2>/dev/null | grep -E "type|channel" || echo "karta wfb0 neni videt"
		iw reg get | sed -n 2p
		tail -1 /tmp/wfb_tx.log 2>/dev/null
		echo "--- log:"; tail -5 /tmp/vima-wfb.log'
}

restart_a_cekej() {
	local ch=$1
	$SSH '/etc/init.d/S98vimawfb restart' >/dev/null || return 1
	for i in $(seq 20); do
		if $SSH "grep -q 'monitor, kanal $ch,' /tmp/vima-wfb.log" 2>/dev/null; then
			sleep 3
			return 0
		fi
		sleep 1
	done
	echo "POZOR: v logu desky se kanal $ch neobjevil (je karta zapojena?)"
	return 1
}

case "$1" in
	stav)
		stav
		;;
	kanal)
		CH=$2
		case "$CH" in
			1|2|3|4|5|6|7|8|9|10|11|12|13) ;;
			149|153|157|161|165) ;;
			*) echo "Kanal '$CH' nepouzivej (povolene: 1-13, 149-165; 36-48 jen uvnitr a DFS ne)."; exit 1 ;;
		esac
		$SSH "sed -i 's/^WFB_CHANNEL=.*/WFB_CHANNEL=$CH/' /etc/vima/vima.conf && : > /tmp/vima-wfb.log" || { echo "Deska neodpovida pres SSH (ethernet?)"; exit 1; }
		restart_a_cekej "$CH"
		# prepsat jen radek CH= (vykony laptopu LAPTOP_TXPWR_IDX_* v souboru zustanou)
		if grep -q '^CH=' "$KONF" 2>/dev/null; then sed -i "s/^CH=.*/CH=$CH/" "$KONF"; else echo "CH=$CH" >> "$KONF"; fi
		echo "Laptop: vychozi kanal je ted $CH (kanal.conf)."
		stav
		;;
	rezim)
		case "$2" in
			test) V=0; T=1 ;;
			video) V=1; T=0 ;;
			*) echo "Pouziti: $0 rezim test|video"; exit 1 ;;
		esac
		$SSH "sed -i 's/^VIDEO_ENABLE=.*/VIDEO_ENABLE=$V/; s/^TESTGEN_ENABLE=.*/TESTGEN_ENABLE=$T/' /etc/vima/vima.conf && : > /tmp/vima-wfb.log" || { echo "Deska neodpovida pres SSH (ethernet?)"; exit 1; }
		CH=$($SSH '. /etc/vima/vima.conf; echo $WFB_CHANNEL')
		restart_a_cekej "$CH"
		stav
		;;
	*)
		sed -n '2,5p' "$0" | sed 's/^# \?//'
		exit 1
		;;
esac
