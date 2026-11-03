# Wrap (rkipc) – výsledek 27. 10. 2026

Wrap = ISP píše hlavní proud po řádcích do kruhového bufferu a VENC kóduje už během vyčítání (online ISP→VENC).
Měření na desce: čas vydání zakódovaného snímku − PTS snímku z VI (/tmp/vima-venc-lat.txt, průměr po 600 snímcích).

| nastavení (1152x648, varianta D)       | v-blank ISP | snímky z kodéru | zpoždění na desce |
|-----------------------------------------|-------------|-----------------|-------------------|
| 60 fps, bez wrapu                       | 0 µs        | 60 fps          | 22,5 ms           |
| 60 fps, wrap (buffer_line 256)          | 0 µs        | **30 fps**      | 18,3 ms           |
| 58 fps, wrap                            | 578 µs      | **29 fps**      | 18,3 ms           |
| 55 fps, wrap  ← na desce                | 1577 µs     | 55 fps          | 18,5 ms           |
| 50 fps, wrap                            | 3463 µs     | 50 fps          | 18,2 ms           |

Kodér ve wrapu potřebuje mezi snímky pauzu (~1–1,5 ms); bez ní každý druhý snímek vynechá.
Přes vzduch 55 fps + wrap: 55 fps, 0 ztrát, max mezera 48 ms (tunel běží, ALINK profil 4).

Přepínání: `nasad-wrap.sh zap|vyp|vrat` + reboot; fps v /oem ini přes `awk -v FPS=55 -f ../sc3336-60fps/rkipc/ini-60fps.awk`.
Zpět na 60 fps bez wrapu: `nasad-wrap.sh vyp` a ini se 60 fps (zaloha/rkipc-300w.ini.wrap-60fps má wrap=1 → po nahrání ještě `vyp`).
