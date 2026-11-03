#!/bin/bash
# Vima: test voleb panelu po kabelu. Pro kazdy prikaz "ovladani.py --kabel <prikaz>" zapise vystup panelu
# a co deska opravdu dela: venc_info (TarFr, RealFps, Online = wrap, rozliseni), snimky z kodéru za 3 s
# (pkt_total_cnt) a novy radky /tmp/vima-rkipc.log. Vysledky: test-panel-<cas>.log vedle skriptu.
#   ./test-panel.sh "fps 15" "fps 30" "rozliseni 1280x720" ...
D=$(cd "$(dirname "$0")" && pwd)
OUT=$D/test-panel-$(date +%m%d-%H%M%S).log
SSH="ssh -o BatchMode=yes -o ConnectTimeout=5 luckfox"
mer() {   # stav kodéru na desce
	$SSH 'v=/proc/vcodec/enc/venc_info
	row() { awk -v k="$1" -F"|" "{for(i=1;i<=NF;i++){gsub(/ /,\"\",\$i)}} \$1==\"ID\"{for(i=1;i<=NF;i++)h[i]=\$i; hdr=1; next} hdr&&\$1==\"0\"{for(i=1;i<=NF;i++)if(h[i]==k){print \$i; exit}} {hdr=0}" $v; }
	p0=$(row pkt_total_cnt); t0=$(cut -d" " -f1 /proc/uptime); sleep 3; p1=$(row pkt_total_cnt); t1=$(cut -d" " -f1 /proc/uptime)
	echo "deska: $(row Width)x$(row Height) TarFr $(row TarFr) SrcFr $(row SrcFr) RealFps*10 $(row RealFps*10) wrap(Online) $(row Online) | vydano za 3 s: $(awk -v a=$p0 -v b=$p1 -v x=$t0 -v y=$t1 "BEGIN{printf \"%.1f fps\", (b-a)/(y-x)}")"'
}
n0=$($SSH 'wc -l < /tmp/vima-rkipc.log' 2>/dev/null || echo 0)
for c in "$@"; do
	echo "===== $(date +%T) $c" | tee -a "$OUT"
	t=$(date +%s)
	python3 -I "$HOME/vima-board/ovladani.py" --kabel $c 2>&1 | tee -a "$OUT"
	echo "(panel $(( $(date +%s) - t )) s)" | tee -a "$OUT"
	sleep 1
	mer 2>&1 | tee -a "$OUT"
	n1=$($SSH 'wc -l < /tmp/vima-rkipc.log' 2>/dev/null || echo 0)
	[ "$n1" -gt "$n0" ] && $SSH "tail -n $((n1 - n0)) /tmp/vima-rkipc.log" | sed 's/^/rkipc: /' | tee -a "$OUT"
	[ "$n1" -lt "$n0" ] && echo "rkipc log zacal znovu (restart desky?)" | tee -a "$OUT"
	n0=$n1
done
echo "vysledky: $OUT"
