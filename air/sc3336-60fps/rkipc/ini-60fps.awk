# Vima: rkipc-300w.ini -> 1152x648@60 (rezim snimace 2x2 binning).
# Meni jen vybrane klice v [video.0], [video.jpeg] a [isp.0.adjustment], komentare za ';' zachova.
# Pouziti: awk -f ini-60fps.awk vstup.ini > vystup.ini   (POSIX/BusyBox awk)
#          awk -v FPS=58 -f ini-60fps.awk ...             (zaloha pri potizich se spodnim okrajem:
#                                                          snimac, video.0 src/dst i gop stejne fps)
#          awk -v IVS=0 -f ini-60fps.awk ...              (navic vypne IVS, kdyz je CPU na 100 %)
BEGIN {
	if (FPS == "") FPS = 60
	if (FPS !~ /^[0-9]+$/ || FPS < 5 || FPS > 60) { print "spatne FPS: " FPS > "/dev/stderr"; bad = 1; exit 1 }
	set["video.0", "buffer_size"] = 373248      # w * h / 2
	set["video.0", "max_width"] = 1152
	set["video.0", "max_height"] = 648
	set["video.0", "width"] = 1152
	set["video.0", "height"] = 648
	set["video.0", "src_frame_rate_num"] = FPS
	set["video.0", "dst_frame_rate_num"] = FPS
	set["video.0", "gop"] = FPS                 # 1 s jako dosud (gop = fps)
	set["video.jpeg", "width"] = 1152           # JPEG nesmi byt vetsi nez max video.0
	set["video.jpeg", "height"] = 648
	set["isp.0.adjustment", "fps"] = FPS        # snimac (AE); video.1 si VI decimuje na svych 30
	if (IVS != "") set["video.source", "enable_ivs"] = IVS   # -v IVS=0: vypnout detekci pohybu (zatez CPU)
}
{ sub(/\r$/, "") }
/^\[.*\]/ { sec = $0; gsub(/^\[|\].*$/, "", sec); print; next }
{
	line = $0
	if (match(line, /^[ \t]*[A-Za-z0-9_.]+[ \t]*=/)) {
		key = substr(line, RSTART, RLENGTH - 1); gsub(/[ \t]/, "", key)
		if ((sec, key) in set) {
			cmt = ""
			if (index(line, ";")) cmt = " " substr(line, index(line, ";"))
			eq = index(line, "=")
			pre = substr(line, 1, eq)
			print pre " " set[sec, key] cmt
			done[sec, key] = 1
			next
		}
	}
	print
}
END {
	if (bad) exit 1
	for (k in set) if (!(k in done)) { split(k, p, SUBSEP); printf("CHYBI klic [%s] %s\n", p[1], p[2]) > "/dev/stderr"; bad = 1 }
	if (bad) exit 1
}
