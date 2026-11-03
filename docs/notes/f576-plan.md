# Varianta F576 – snímač 2304×576, obraz 1152×576 @ 60 fps s wrapem (připraveno 3. 11. 2026)

**Stav: jen připraveno, na desce nic nezměněno, nic nerestartováno.** Na desce dál běží varianta D
(sc3336.ko c5c169ce) + 1152×648 @ 55 fps s wrapem.

## Proč
Wrap (kodér kóduje už během vyčítání) potřebuje mezi snímky pauzu ISP ≥ ~1,5 ms. U D při 60 fps (VTS 680,
648 řádků) je v-blank ISP 0 → kodér půlí fps; proto teď 55 fps (VTS 742, v-blank 1576 µs).
Skrytá režie ~30 řádků: v-blank ISP ≈ (VTS − řádky − 30) × 24,51 µs (55 fps: (742−648−30) × 24,51 = 1569 µs, změřeno 1576).

F576 čte o 72 řádků méně: **(680 − 576 − 30) × 24,51 µs ≈ 1,8 ms** i při 60 fps (VTS 680 beze změny).

## Co se v snímači mění (jen proti D)
| registr | D | F576 | význam |
|---|---|---|---|
| 0x3202/03 | 0x0000 | **0x0048** = 72 | první čtený řádek okna |
| 0x3206/07 | 0x0517 = 1303 | **0x04cf** = 1231 | poslední čtený řádek okna (okno 1160 = 2 × (576 + 4)) |
| 0x320a/0b | 0x0288 = 648 | **0x0240** = 576 | výška výstupu |
| 0x3212/13 | 2 | 2 | posun y v přeskočených řádcích (2 + 576 + 2 = 580 = 1160/2) |
| 0x3215, 0x3220 | 0x31, 0x01 | stejné | svislé přeskakování 1:2 |
| šířka, MIPI 510, HTS 2500, VTS 680 | | stejné | |

Recept je stejný jako vendor tabulky s ořezem a přeskakováním (hpmcu drv_sc3336.c): 640x480@75 má okno
168..1135 = 968 = 2 × (480 + 4), posun y 2; 320x240@120 okno 408..895 = 488 = 2 × (240 + 4). Začátek 72 je
násobek 4 → stejná fáze Bayeru i přeskakování jako D. Režim V4L2: **2304×576@60** (supported_modes[2].height,
z ní vblank_def = 680 − 576 = 104, VTS = vblank + height = 680, rozsahy vblank – vše odvozené od height).

Záběr: svisle 1152 z 1296 řádků (ořez 72 nahoře i dole = 89 % výšky D), vodorovně beze změny. Poměr stran 2:1.

## Soubory (vše nové, D a produkční soubory beze změny)
| soubor | md5 | |
|---|---|---|
| `ovladac/build-F576/sc3336.ko` | c99dc4ff0f82f382bf0a309ccfc339d2 | `distrobox enter luckfox -- bash ovladac/build-varianty.sh F576` |
| `iq/sc3336_CMK-OT2119-PC1_30IRC-F16.json.f576` | 86237c6387f75129cdca4687e6c35153 | IQ desky 3. 11. (= `.exp4`, e9678587, strop expozice 4 ms) + LSC 2304x576 |
| `rkipc/rkipc-300w.ini.f576` | 3ee7a1604580fa436c65e89c831fea16 | ini desky 3. 11. (b2322e1f, power_line close) + `rkipc/ini-f576.awk` |
| `iq/pridej-lsc-orez.py` | | LSC pro ořezaný záběr (přepočet tabulek) |
| `rkipc/ini-f576.awk` | | ini → F576 (`-v FPS=55`, `-v WRAP=0` volitelně) |
| `deska/nasad-f576.sh` | | `stav` / `zap` / `vrat [-f]` – zálohy + md5, bez restartu |
| `deska/over-f576.sh` | | kontrola po restartu, jen čte |

Změny existujících souborů: `ovladac/sc3336.c` – nový přepínač `SC3336_V60_HEIGHT` (výchozí 648), `.height`
režimu BIN60 ho používá; komentář zkrácen o 3 řádky, aby všechny řádky od 76 zůstaly na místě.
`ovladac/build-varianty.sh` – položka `[F576]` (`-DSC3336_V60_KIND=1 -DSC3336_V60_HEIGHT=576` + FIX
`{0x3220,0x01}` jako D + okno a výška výše). Zálohy před změnou: `ovladac/sc3336.c.pred-f576` (52b19bd8),
`ovladac/build-varianty.sh.pred-f576` (d35c425d).

**Ověření D:** `build-varianty.sh D F576` (v build-D) dal sc3336.ko **c5c169ce8fed752c9e14885a81cba8f9 = bajtově
shodný**; adresář build-D pak vrácen ze zálohy (časy i zdroj jako 27. 10.). Pozn.: build-id (.note.gnu.build-id,
20 B) závisí na cestě buildu (DWARF před strip) – tentýž zdroj v jiném adresáři dá 61a237b6 a liší se jen
v těch 20 bajtech; nový zdroj v tomtéž cizím adresáři dal také 61a237b6, tj. ani čísla řádků se nezměnila.
Kontrola obsahu modulu: F576 v60_fix = D + {0x3202,0x00} {0x3203,0x48} {0x3206,0x04} {0x3207,0xcf}
{0x320a,0x02} {0x320b,0x40}; režim 2 = 2304x576, hts 2500, vts 680.

### LSC
LSC se vybírá podle **vstupu ISP = výstupu snímače** (D používá položku 2304x648: XSIZE 144, YSIZE 40/41),
takže stačí položka **2304x576** (sektory x 16 × 144, y 16 × 36); položka 1152x576 potřeba není (ISP výstup
se nepoužívá). Na rozdíl od D (stejný záběr → kopie tabulek, `pridej-lsc-rozliseni.py`) je F576 ořez, kopie
by dala horní/dolní okraj přesvětlený (jako E2). `pridej-lsc-orez.py` proto tabulky 17×17 (po řádcích,
řádek = y) přepočítá: bod k leží v řádku plného záběru 72 + 72k a hodnota je lineární interpolace mezi
body původní mřížky (81 řádků) – střední řádek mřížky zůstane přesně, okraje dostanou zisk z místa ořezu
(greenR A_100 střední sloupec: 1324 → 1260 nahoře, 1304 → 1256 dole). Mimo LSC beze změny (skript ověřuje).
Riziko: IQ bude mít 4 rozlišení LSC; hlavička rkaiq má `LSC_MAX_RESOLUTION 2` (starý typ), ale D funguje se
třemi (používá 3.) – ověřit registry LSC (viz níže).

## Nasazení (jen po domluvě s druhou session – restart přeruší video i wfb)
```bash
cd ~/vima-board/sc3336-60fps
deska/nasad-f576.sh stav        # jen čte: md5 na desce (čekám ko c5c169ce = D), wrap_max_fps 55, volno /oem
deska/nasad-f576.sh zap         # zálohy + nahrání, md5 kontrola, BEZ restartu
ssh -o BatchMode=yes luckfox 'sync; reboot'     # jen se souhlasem uživatele
sleep 45; deska/over-f576.sh    # kontrola (jen čte)
```
Co `zap` dělá (pro ruční postup stejné kroky):
1. kontroly: md5 build-F576 = c99dc4ff, `uname -r` = 5.10.160, /oem zapisovatelný, volno ≥ 2000 kB
   (potřeba ~1,5 MB; 3. 11. volno 3440 kB), upozorní, když na desce není D nebo rkipc není wrap build be29bd6d;
2. zálohy na desce: `cp -p X X.pred-f576.tmp; cmp; mv → X.pred-f576` pro
   `/oem/usr/ko/sc3336.ko`, `/oem/usr/share/iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json`,
   `/oem/usr/share/rkipc-300w.ini` (jen když záloha není), kopie do `deska/zaloha-f576/` (+ `prvni/`), md5 kopie = deska;
3. IQ: když má deska pořád e9678587 → `iq/...json.f576`; jinak IQ stáhne a LSC 2304x576 přepočítá z aktuálního
   (`python3 -I iq/pridej-lsc-orez.py <iq-desky> <vystup> 2304x576 72 1152`) – cizí změny IQ zůstanou;
4. ini: aktuální `/oem/usr/share/rkipc-300w.ini` → `awk -f rkipc/ini-f576.awk` → `deska/rkipc-300w.ini.f576.nahrat`
   (diff vypíše): video.0 1152x576 (max 1152x576), buffer_size 331776, src/dst fps 60, gop 60, jpeg 1152x576,
   isp.0.adjustment fps 60, video.source enable_wrap 1, buffer_line 256, wrap_max_fps 60;
5. `cat > X.novy`, md5 .novy = laptop (jinak smaže .novy a skončí), `mv` všech tří, `sync`, md5 znovu → `deska/zaloha-f576/nahrano.md5`.

## Ověření po restartu (`deska/over-f576.sh`, bez registrů LSC: `BEZ_DEVMEM=1 deska/over-f576.sh`)
| co | kde | čekám |
|---|---|---|
| modul | md5 /oem/usr/ko/sc3336.ko, /sys/module/sc3336/parameters/bin60 | F576 c99dc4ff, Y |
| VICAP | /proc/rkcif-mipi-lvds | `2304x576@60`, fps ~60–62, csi size err 0, all err count 0 (nerostou) |
| ISP | /proc/rkisp-vir0 | `Input … Size:2304x576@60fps`, **`v-blank:` ≥ 1500 µs (odhad ~1800)**, mainpath 1152x576 rate 16 ms frameloss 0 |
| LSC | devmem 0xffa02244 / 0xffa02254 (jen při běžícím rkipc) | 0x00900090 / **0x00240024** (144 / 36) |
| kodér | /proc/vcodec/enc/venc_info kanál 0 | 1152x576, **Online 1**, TarFr 60, **RealFps\*10 ~600**, pkt_total_cnt +~600 za 10 s (ne ~300 = půlení) |
| zpoždění | /tmp/vima-venc-lat.txt | `wrap=1`, avg < 18,6 ms (D 55 fps wrap; čtení 576 místo 648 řádků ≈ −1,8 ms) |
| rkipc | /tmp/vima-rkipc.log | `video init: 1152x576, fps 60 (snimac 60), wrap 1 (enable_wrap 1, wrap_max_fps 60)` |

Stream a snímek na laptopu (po kabelu, jako `deska/test-varianta.sh`):
```bash
mkdir -p test-f576
timeout 25 ffmpeg -hide_banner -loglevel error -skip_frame nokey -rtsp_transport tcp -i rtsp://10.42.0.2:554/live/0 -frames:v 1 -update 1 -y test-f576/snimek.png
timeout 30 ffprobe -hide_banner -loglevel error -rtsp_transport tcp -select_streams v -read_intervals %+12 -show_entries packet=pts_time -of csv=p=0 rtsp://10.42.0.2:554/live/0 > test-f576/pakety.csv
deska/over-f576.sh > test-f576/over.txt; ssh -o BatchMode=yes luckfox dmesg > test-f576/dmesg.txt
```
(fps z pakety.csv: python blok z `deska/test-varianta.sh`.) Snímek: horní/dolní okraj nesmí být světlejší
než střed (LSC), žádné pruhy, barvy jako D. Pak vzduchem `~/vima-board/gs-video.sh` a latence telefonem
(`~/vima-board/latence/latence.py`).

Když něco nesedí:
- csi size err / žádný obraz → okno; zpět `deska/nasad-f576.sh vrat` + restart;
- v-blank < ~1500 µs nebo RealFps ~30 → `FPS=58 deska/nasad-f576.sh zap` + restart (zálohy D zůstanou) nebo zpět;
- LSC YSIZE ≠ 0x00240024 (rkaiq nevzal 4. rozlišení) → obraz s tmavými rohy/okraji; zkusit IQ bez položky 1152x648 (A/B/E2 se nepoužívají) nebo zpět.

## Návrat na D + 55 fps wrap
```bash
cd ~/vima-board/sc3336-60fps
deska/nasad-f576.sh vrat        # mv *.pred-f576 zpět, md5 = kopie v deska/zaloha-f576/; změny od nasazení → stop (-f = i tak)
ssh -o BatchMode=yes luckfox 'sync; reboot'     # se souhlasem
BEZ_DEVMEM=1 deska/over-f576.sh # čekám sc3336.ko = D, Input 2304x648, v-blank ~1576 µs, Online 1, 55 fps, wrap_max_fps 55
```
Bez záloh (krajní případ, na desce): `cp -p /oem/usr/share/vima/sc3336-60.ko /oem/usr/ko/sc3336.ko` (D c5c169ce);
ini: `awk -v FPS=55 -f rkipc/ini-60fps.awk <ini-desky>` a pak `~/vima-board/wrap/nasad-wrap.sh zap` (doplní
wrap_max_fps 55 podle max_height 648); IQ .f576 může zůstat (obsahuje i 2304x648 a 2304x1296).
Úplně zpět na 30 fps: `deska/vrat-30fps.sh` (po F576 nejdřív `nasad-f576.sh vrat`, jinak hlásí změnu nahrano.md5).

## Pozor během testu F576
- Panel a vima-ctl.py F576 neznají: `rezim()` = 60 (bin60 = Y) s maximem 1152x648 a wrap_max 55 → **z panelu
  neměnit rozlišení, fps ani režim** (1152x648 by ISP/VENC odmítl, set_mode by přepsal modul na D a ini na
  1152x648/55). Panel se otevírá `~/vima-board/ovladani.py okno` (po kabelu `~/vima-board/ovladani.py --kabel okno`).
- `wrap/nasad-wrap.sh zap` by nastavil wrap_max_fps 55 (max_height ≤ 648) → wrap při 60 fps vypnutý; nespouštět.
- `sdk-prepni.sh` a firmware se F576 netýkají (pořád D); do firmwaru až po úspěšném testu a domluvě.
- Substreamy: video.1 704x576 a video.2 960x540 (IVS) zůstávají, z 2:1 jsou jen jinak zdeformované než dosud.

## Stav 3. 11. 2026 večer – NENASAZENO (uživatel: „příště“)
Připraveno agentem, nezávislá kontrola: ok (registry odpovídají tabulkám výrobce pro ořez + přeskakování,
build-F576/sc3336.ko md5 c99dc4ff: tabulka D + 6 zápisů, mode 2 = 2304x576, VTS 680; varianta D beze změny c5c169ce).
Před nasazením opravit (nálezy kontroly, všechny drobné):
1. deska/nasad-f576.sh ř. 23 RKIPC_WRAP_MD5=be29bd6d je zastaralé – na desce je 84a9691c (wrap + isp-antiflicker.patch);
   porovnávat s md5 ~/vima-board/wrap/rkipc-wrap. NEVRACET be29bd6d (ztratilo by se vypnutí ochrany proti blikání = strop expozice 4 ms).
2. zap dělá zálohy *.pred-f576 dřív, než může skončit chybou (konflikt IQ, chyba pridej-lsc-orez.py/awk, md5 přenosu) –
   při chybě po záloze zálohy smazat, nebo při existujících zálohách bez nahrano.md5 odmítnout / zálohovat znovu.
3. Záložní cesta FPS=58 selže, pokud první nasazení přepočítalo IQ z desky (IQ md5 ≠ .f576) – brát jako „už F576“ i md5 z $Z/nahrano.md5.
4. Nouzový návrat „bez záloh“ v tomto plánu je neúplný – nejjednodušší funkční návrat: ~/vima-board/ovladani.py obraz 1152x648@60
   (vima-ctl set_mode: 60 > wrap_max 55 → restart, zapíše sc3336-60.ko (D) a ini 1152x648), pak panelem 55 fps (restart, wrap).
Během testu F576 neměnit z panelu rozlišení/fps/režim a nespouštět wrap/nasad-wrap.sh zap (nastavil by wrap_max_fps 55).
Po nasazení zkontrolovat LSC registry (YSIZE 0x00240024, XSIZE 0x00900090) – IQ má 4 rozlišení LSC.
