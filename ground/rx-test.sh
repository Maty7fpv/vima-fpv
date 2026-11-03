#!/bin/bash
# Vima: prijem z desky na laptopu (RX karta wfb0 v portu 3-1).
# Spoustet se sudo: sudo ~/vima-board/rx-test.sh [kanal]   (bez kanalu = ~/vima-board/kanal.conf)
# Vypisuje statistiky wfb_rx (PKT ...) a pocitadlo testovacich dat z desky.
[ -f /home/mikes/vima-board/kanal.conf ] && . /home/mikes/vima-board/kanal.conf
CH=${1:-${CH:-149}}
IF=wfb0
WFB=/home/mikes/wfb-ng
LOG=/home/mikes/vima-board/rx-test.log

ip link show $IF >/dev/null 2>&1 || { echo "Rozhrani $IF neexistuje - je RX karta v portu 3-1?"; exit 1; }
if pgrep -f '[w]fb_tx -K gs.key -f data -p 160 ' >/dev/null; then echo "Bezi tunel.sh - nejdriv ho ukonci"; exit 1; fi
modprobe -r 88XXau_wfb 2>/dev/null && modprobe 88XXau_wfb rtw_tx_pwr_idx_override=8 && sleep 3
ip link set $IF down
iw dev $IF set monitor otherbss
ip link set $IF up
iw dev $IF set channel $CH HT20
iw dev $IF info | grep -E 'type|channel'

# pocitadlo testovacich dat (poradova cisla z vima-testgen.py na desce)
python3 -I -c '
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", 5600)); s.settimeout(0.2)
c = b = lost = 0; last = None; t = time.time()
while True:
    try:
        d = s.recv(4096); c += 1; b += len(d)
        q = int.from_bytes(d[:4], "big")
        if last is not None and q > last + 1: lost += q - last - 1
        last = q
    except socket.timeout:
        pass
    if time.time() - t >= 1:
        print("DATA %4d pkt/s %5.2f Mbit/s, chybi celkem %d" % (c, b * 8 / 1e6, lost), flush=True)
        c = b = 0; t = time.time()
' &
CNT=$!
trap 'kill $CNT 2>/dev/null' EXIT

cd $WFB && ./wfb_rx -p 0 -c 127.0.0.1 -u 5600 -K gs.key $IF 2>&1 | tee $LOG
