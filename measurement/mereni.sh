#!/bin/bash
# Vima: vyhodnoceni poslednich N sekund prijmu z logu wfb_rx.
#   ~/vima-board/mereni.sh [sekund] [log]     (vychozi: 60 s, rx-test.log)
# Pocka, az v logu bude N novych sekund, a vypise prijato / FEC / ztraty / RSSI / SNR.
N=${1:-60}
LOG=${2:-/home/mikes/vima-board/rx-test.log}
[ -f "$LOG" ] || { echo "Log $LOG neexistuje (bezi rx-test.sh?)"; exit 1; }
N0=$(grep -c $'\tPKT\t' "$LOG")
echo "Cekam $N s na nova data v $LOG ..."
[ -n "$NOWAIT" ] || until [ "$(grep -c $'\tPKT\t' "$LOG")" -ge $((N0 + N)) ]; do sleep 2; done
python3 -I - "$LOG" "$N" <<'EOF'
import sys
log, n = sys.argv[1], int(sys.argv[2])
pkt, ant = [], []
for line in open(log, errors="replace"):
    f = line.rstrip("\n").split("\t")
    if len(f) >= 3 and f[1] == "PKT":
        pkt.append((int(f[0]), [int(x) for x in f[2].split(":")]))
    elif len(f) >= 5 and f[1] == "RX_ANT":
        ant.append((int(f[0]), f[2], f[3], [int(x) for x in f[4].split(":")]))
win = pkt[-n:]
t0 = win[0][0] - 1000
rx = sum(p[1][0] for p in win)
fec = sum(p[1][4] for p in win)
lost = sum(p[1][5] for p in win)
out = sum(p[1][7] for p in win)
bad_s = sum(1 for p in win if p[1][5] > 0)
print("okno %d s: prijato %d paketu, FEC opravil %d, nezachraneno %d (v %d s), vystup %.1f paketu/s"
      % (len(win), rx, fec, lost, bad_s, out / len(win)))
per = {}
for ts, freq, a, v in ant:
    if ts < t0:
        continue
    d = per.setdefault((freq.split(":")[0], a), [0, 0, 0, 999, 999])
    c = v[0]
    d[0] += c; d[1] += c * v[2]; d[2] += c * v[5]
    d[3] = min(d[3], v[1]); d[4] = min(d[4], v[4])
for (freq, a), d in sorted(per.items()):
    if d[0]:
        print("  %s MHz anténa %s: RSSI prumer %.1f dBm (min %d), SNR prumer %.1f dB (min %d)"
              % (freq, a, d[1] / d[0], d[3], d[2] / d[0], d[4]))
EOF
