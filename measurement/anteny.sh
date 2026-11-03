#!/bin/bash
# Vima: test vysilacich anten. Deska musi byt na ethernetu, na laptopu musi bezet rx-test.sh.
#   ~/vima-board/anteny.sh <nazev-zapojeni> [index]
# Pro STBC 0 a 1 zmeri 20 s prijmu (vykon docasne index 30, pak se vrati podle vima.conf).
NAZEV=${1:?Pouziti: $0 <nazev-zapojeni> [index]}
IDX=${2:-30}
OUT=/home/mikes/vima-board/anteny-$NAZEV.txt
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"
: > "$OUT"
for STBC in 0 1; do
	$SSH "sed -i 's/^WFB_STBC=.*/WFB_STBC=$STBC/' /etc/vima/vima.conf && : > /tmp/vima-wfb.log && /etc/init.d/S98vimawfb restart >/dev/null" || { echo "Deska neodpovida"; exit 1; }
	for i in $(seq 20); do $SSH "grep -q 'spoustim wfb_tx' /tmp/vima-wfb.log" && break; sleep 1; done
	$SSH "echo $IDX > /sys/module/88XXau_wfb/parameters/rtw_tx_pwr_idx_override; iw dev wfb0 set txpower fixed -${IDX}00"
	sleep 4
	echo "== $NAZEV, STBC $STBC, index $IDX" | tee -a "$OUT"
	/home/mikes/vima-board/mereni.sh 20 | tail -3 | tee -a "$OUT"
done
# vratit STBC 0 a vykon z konfigurace
$SSH "sed -i 's/^WFB_STBC=.*/WFB_STBC=0/' /etc/vima/vima.conf && /etc/init.d/S98vimawfb restart >/dev/null"
echo "Hotovo: $OUT (STBC zpet na 0, vykon podle vima.conf)"
