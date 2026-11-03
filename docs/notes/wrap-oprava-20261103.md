# Wrap + oprava ovládání – HOTOVO 3. 11. 2026

Chyba „panel 30 fps → skutečně 15“: wrap běžel i tam, kde snímač nemá mezi snímky pauzu (2304x1296@30).
Oprava (vše nasazeno, test celého panelu prošel – logy test-panel-1103-*.log):
- rkipc (/oem/usr/bin/rkipc be29bd6d, zdroj src/, patch video-wrap.patch): wrap jen když enable_wrap = 1 a fps snímače
  <= video.source:wrap_max_fps, a to JEN při startu rkipc. Přepínání wrapu za běhu (rk_video_restart) 3. 11. nechalo
  kodér bez snímků a desku s chybami čtení flash (Input/output error, Bus error) → nutné vypnout napájení. Zrušeno.
  Log /tmp/vima-rkipc.log, měření zpoždění /tmp/vima-venc-lat.txt (oba max ~64 kB).
- vima-ctl (/usr/bin/vima-ctl.py 412f99ff, i SDK overlay): REZIMY wrap_max/wrap_fps (60: 55/55, 30: 0/–); ini_rezim píše
  wrap_max_fps; skutečné fps z pkt_total_cnt (status real_fps, kontrola po set_fps, návrat při < 80 %); set_fps odmítne
  změnu, která by zapnula/vypnula wrap; set_mode umí restart i ve stejném režimu kvůli wrapu.
- panel (~/vima-board/ovladani.py): fps 55; přechod 55↔60 = „Nastavit (restart desky)“ (restart ~30 s); log příkazů
  ~/vima-board/ovladani.log; opravené měření mezery obrazu (padalo „max() iterable argument is empty“ se starým snimky.log).
- nasad-wrap.sh: wrap_max_fps podle /oem ini; `vrat` už nevrací staré celé ini, jen smaže klíče wrapu.
- Revize (workflow, 4 oblasti + 2 skeptici na nález): 5 potvrzených + 3 sporné opraveny.

Test (po kabelu, skutečné fps z kodéru): režim 30 – fps 15/20/25/30, rozlišení 1280x720/1920x1080/2304x1296;
režim 60 s wrapem (55) – fps 30/15/55, rozlišení 960x540/640x360/1152x648, kombinace; 60 fps (restart, bez wrapu) –
fps 30, rozlišení, zpět 60; 55 (restart, wrap); přepnutí 60→30→60. Vše přesně, mezery 50–180 ms, restart ~30 s.
Neověřeno: přenos vzduchem (tunel a video na laptopu neběžely).

Stav desky: režim 60, 1152x648 @ 55 fps, wrap zapnutý.
