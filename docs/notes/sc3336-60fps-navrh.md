# Vima – snímač SC3336 v režimu 1152×648 @ 60 fps (binning 2×2)

Připraveno 26. 10. 2026. **Jen v SDK a v této složce, na desce nic nezměněno, nic se neflashovalo.**
Originály v SDK jsou beze změny; nové verze leží vedle nich s příponou `.60fps`.
Revize 26. 10. večer: nezávislá kontrola (5 oblastí + skeptik na každý nález, jen čtení) – opravy viz kap. 7.

## 1. Shrnutí

- Do ovladače `sc3336.ko` přibyl třetí režim **1152×648 @ 60,0 fps** (binning 2×2 přes celou plochu čipu, stejný záběr jako 2304×1296). Při startu se zapne sám (parametr modulu `bin60=1`, jde vypnout `bin60=0`).
- Registry nejsou vymyšlené: je to **vendorová binning tabulka SC3336** (MCU ovladač v SDK, režim 640×480@75), jen s větším oknem/výstupem, VTS a expozicí. Geometrie vychází přesně jako u sesterského čipu SC3336P (1152×648@60, posun 2/2).
- **Test na desce nepotřebuje flash ani nové jádro**: stačí vyměnit 3 soubory v `/oem` (modul, IQ, rkipc ini) a restartovat desku. Návrat = 3 zálohy zpět + restart.
- Odhad latence (stejná metoda jako 25. 10.): **83 ms → asi 60–66 ms** (podrobně v kap. 4).

## 2. Ověření podkladů

| Podklad | Výsledek |
|---|---|
| Ovladač má jen 2304×1296 30/25 fps, 2 linky, 10 bit | ✅ Ano. 30 fps: XVCLK 24 MHz, link_freq 255 MHz (= 510 Mbit/s na linku), VTS 0x550 = 1360. Okno/binning registry nepoužívá. |
| Řádek 24,51 µs | ✅ 1/(30 × 1360). Nezávisle potvrzeno: MCU režim 640×480@75 má **stejné PLL** (0x36e9=0x54, 0x37f9=0x47, 0x37fa–fd) a VTS 544 → 1/(75 × 544) = 24,51 µs. Binning tedy čas řádku nemění. |
| MCU ovladač: 0x3215=0x31, 0x3220=0x01, 0x5000=0x46, 0x5900=0x01, 0x5901=0x04, 0x5988=0x70, okno 0x3200–0x3213 | ✅ Ano, ale **chybělo**: binned tabulky navíc mění **0x36ec 0x1c→0x2c** (MIPI na polovinu = 255 Mbit/s), přidávají **0x4819–0x4829** (časování MIPI pro 255 Mbit/s) a **0x30b8=0x44**. Analogové registry jsou z 25fps sady (0x3309, 0x331f, 0x339c=0xb4, 0x3678/79, 0x3690–92) – stejné jako v kernelové 25fps tabulce. |
| SC3336P má 1152×648@60 | ✅ Ano, 255 Mbit/s, stejné binning registry (jen 0x5900=0xf1). Jiný čip (ID 0x9c41 vs 0xcc41), v jádře vypnutý – slouží jen jako předloha geometrie. |
| Výstup 0x3208/09=0x0480, 0x320a/0b=0x0288 | ✅ Okno 2312×1304 → binned 1156×652 → výstup 1152×648, posun 2/2 (vycentrováno, sudé → Bayer BGGR zůstává). Stejná plocha čipu jako 2304×1296 (posun 4/4). |
| VTS 0x2a8 (60,0) nebo 0x2c4 (57,6), expozice VTS−8 | ✅ Zvoleno **VTS 680 = 60,00 fps**, expozice 672. 57,6 fps není třeba stavět zvlášť: stačí v ini `fps = 58` → AE nastaví VTS 703 (58,0 fps). Rezerva 32 řádků (SC3336P má jen 16). |
| Link 255 nebo 510 | Zvoleno **255 Mbit/s** (varianta B, výchozí) – stejné nastavení MIPI jako vendorové binned tabulky SC3336; na řádek zbývá ~1,8 µs na přechody MIPI, stejně jako u dnešního ověřeného režimu 2304×1296 při 510. Pozor: vendor ale 255 Mbit/s používá jen pro 640/320 px na řádek; 1152 px při 255 má jen SC3336P a ten má delší řádek (25,1 µs, rezerva ~2,4 µs). Varianta A (510, linka vytížená ~46 %) je proto **rovnocenná alternativa** (`-DSC3336_BIN60_MIPI_510M=1`, hotový build-A). DPHY si rychlost čte z link_freq při startu streamu (255 spadá do rozsahu ≤ 299 v tabulce RV1106); ISP hodiny zůstanou 200 MHz v obou variantách. |
| IQ: LSC jen 2304x1296 | ✅ Ano. Ostatní rozlišení-závislé moduly jsou vypnuté (CAC enable 0, LDCH 0). Přidáno LSC 1152x648 (viz kap. 3). |
| rkipc ini: max/width/height, buffer_size, fps, gop | ✅ + **navíc nutné**: `video.jpeg` 1920×1080 → 1152×648 (JPEG kanál má max = video.0:max, jinak chyba/přetečení bufferu) a `isp.0.adjustment fps = 60` (podle něj se ladí snímač i decimace). `video.1` (substream 30 fps) si VI zdecimuje samo. |

Další zjištění:
- Režim se vybírá jen tím, který je v ovladači výchozí – rkipc/rkaiq ani skripty formát snímače nenastavují (`rk_aiq_uapi2_sysctl_prepare(ctx, 0, 0, …)`). Proto parametr `bin60`.
- Stávající 30fps režim má `hts_def` 2800 při pixel rate 102 Mpx/s (to by dávalo řádek 27,45 µs místo 24,51). Nový režim má hodnoty konzistentní oběma způsoby výpočtu (hts × vts × fps = pixel rate, 1250 × 680 × 60 = 51 Mpx/s), takže `rk_isp_set_frame_rate` trefí VTS přesně.
- Jádro nemá MODVERSIONS ani podpis modulů → stačí samotný modul se stejným vermagic (`5.10.160 mod_unload ARMv7 thumb2 p2v8` – ověřeno).
- Kontrola potvrdila: tabulka B se od vendorové 640×480@75 liší jen v oknu/výstupu/VTS/expozici (168 položek, stejné pořadí), A jen v 0x36ec a 0x4819–0x4829; zkompilované `.ko` obsahují správnou tabulku; nic v řetězci (rkcif, mipi-csi2, rockit, rkaiq, rkipc) formát snímače zpět na 2304×1296 nepřepne – jen čtou `get_fmt`.

## 3. Připravené změny

Pracovní složka `~/vima-board/sc3336-60fps/`:

| Soubor | Co to je |
|---|---|
| `ovladac/sc3336.c` (+ `.orig`, `sc3336-1152x648-60fps.patch`) | upravený ovladač: tabulka 1152×648, režim č. 2, link_freq 127,5 MHz, parametr `bin60` (výchozí 1), verze 0.1.2 |
| `ovladac/build-ko.sh` | překlad modulu mimo strom proti `objs_kernel` (SDK se nemění) |
| `ovladac/build-B/sc3336.ko` | **hotový modul, MIPI 255** (sha256 4528e37e…) |
| `ovladac/build-A/sc3336.ko` | záloha, MIPI 510 (sha256 33019e14…) |
| `iq/sc3336_CMK-OT2119-PC1_30IRC-F16.json` (+ `.orig`) | IQ: přidáno LSC 1152x648 – stejné koeficienty 17×17 (stejný záběr), sektory x 16×72, y 40/41 střídavě (jako vendor u 1080 řádků). Skript `pridej-lsc-1152x648.py` kontroluje, že jinde se nic nezměnilo. Pro 2304×1296 dál platí původní tabulky. |
| `rkipc/ini-60fps.awk` (+ `rkipc-300w.ini.60fps`, `.patch`) | mění jen 11 klíčů ([video.0] 1152×648, buffer 373248, fps/src/dst/gop, [video.jpeg] 1152×648, [isp.0.adjustment] fps), zbytek ini nechá – funguje i na ini, které mezitím změní druhá session. `awk -v FPS=58 …` nastaví všechny 4 fps klíče najednou. Chybějící klíč = chyba (exit 1). |
| `deska/nasad-60fps.sh [A\|B] [fps]` | nahraje 3 soubory do `/oem` a ověří md5. Zálohu `*.pred-60fps` dělá jen když žádná není (ověřenou `cmp`). Kopie záloh na laptopu: `deska/zaloha/` (poslední) a `deska/zaloha/prvni/` (nikdy nepřepsaná). Ini upravuje z aktuálního souboru na desce. **Nerestartuje.** |
| `deska/vrat-30fps.sh [-f]` | vrátí zálohy a tím je spotřebuje (příští nasazení zazálohuje čerstvý stav), ověří md5 proti kopiím na laptopu. Když se některý soubor na desce od nasazení změnil (např. ini druhou session), ukáže rozdíl a skončí; `-f` vrátí i tak. Bez restartu. |
| `deska/over-60fps.sh` | po restartu jen čte: md5 modulu (pozná A/B), bin60, fps a chyby VICAP, vstup ISP, **registry LSC přes devmem** (svislé sektory 40/41 = tabulky 1152x648, 81/81 = špatně; jen když běží rkipc), ini po sekcích, zátěž, dmesg (16 kB, může být už přepsaný) |
| `sdk-prepni.sh stav\|60fps\|puvodni` | až po úspěšném testu: přepne SDK pro firmware. Zálohy zdrojů `*.pred-60fps` vedle originálů, zálohy kopií pro balení (`output/out`, `media/isp/out`) v `sdk-zaloha/` – jinak by se dostaly do oem.img. Hlídá md5 (stav puvodni / 60fps / ZMENENO); soubor změněný po přepnutí při návratu nechá a ohlásí; obnovenému `sc3336.c` dá nové mtime (jinak by Kbuild nechal 60fps `sc3336.o`). Otestováno jen na kopii SDK. |

V SDK vedle originálů (sestavení je nepobere – IQ i ini se kopírují jmenovitě, jádro bere jen `.c` z Makefile):
- `sysdrv/source/kernel/drivers/media/i2c/sc3336.c.60fps` + `sc3336.c.60fps.patch`
- `media/isp/release_camera_engine_rkaiq_rv1106_…/isp_iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json.60fps`
- `project/app/rkipc/rkipc/src/rv1106_ipc/rkipc-300w.ini.60fps` + `.patch` (snímek z 26. 10.; pro firmware raději `sdk-prepni.sh`, který vezme aktuální ini)

## 4. Odhad latence

Měření 25. 10. (720p30, šero): sklo–sklo 83 ms (stopky) / 91 ms (blikající čtverec); deska SOF→RTP 43 ms = vyčtení snímače 32 ms + ISP/kodér/RTP ~11 ms; expozice ~30 ms.

| Část | 720p30 dnes | 1152×648@60 | Rozdíl |
|---|---|---|---|
| Vyčtení snímku (kodér čeká na celý snímek) | 1296 ř. × 24,51 µs = 32 ms | 648 ř. = 16 ms | stopky uprostřed obrazu: −8 ms (polovina), u horního okraje −16 ms |
| Polovina expozice (v šeru) | ~15 ms | max ~8 ms (strop 16,4 ms) | −7 ms (na světle ~0) |
| Kodér (0,92 → 0,75 Mpx) | ~11 ms | ~9 ms | −2 ms |
| Vysílání snímku vzduchem (MCS 1, poloviční snímek) | ~5 ms | ~2,5 ms | −2 až −3 ms |
| Dekódování | 2,2 ms | ~1,7 ms | −0,5 ms |
| Čekání na další snímek (jen metoda „čtverec“) | 16,7 ms | 8,3 ms | −8 ms |

Odhad: **stopky ~60–66 ms, čtverec ~62–68 ms** (úspora 17–25 ms). Podklady počítaly 50–56 ms – to by platilo, kdyby se ušetřilo celé vyčtení (32 → 16 ms) i čekání na snímek; u stopek uprostřed obrazu se ale vyčtení projeví jen z poloviny a čekání na snímek vůbec. Další velká páka (mimo tento úkol): kódovat už během vyčítání (režim wrap/slice VI→VENC) – ubralo by většinu zbylých ~8 ms vyčtení.

## 5. Rizika

1. **Binning vs. skipping.** Stejnou sadu registrů (0x3215=0x31, 0x3220=0x01, 0x5000, 0x5900/0x5901) používá vendor u SC3336, SC3336P, SC230AI, SC231HAI i SC450AI a nazývá to „binning“. Bez datasheetu ale nejde říct, jestli je svisle opravdu analogové sčítání řádků, nebo jen přeskakování (0x3215=0x31 vypadá jako vynechání každé druhé dvojice řádků; vodorovně je to nejspíš digitální průměr v bloku 0x59xx). Při přeskakování: zubaté vodorovné hrany, moaré, šum se svisle nezlepší. Pro FPV obraz pořád použitelný; ověří se testem (kap. 6, bod 6). Ladicí knoflík: 0x5900=0xf1 (u SC3336P a sc2355 „fix noise“).
2. **Kalibrace IQ.** LSC převzaté (stejná plocha čipu) – měla by sedět. Ostrost a odšumění (sharp, ynr, cnr, bayer2dnr/tnr) jsou laděné na 2304×1296 → na 1152×648 může být obraz přeostřený (lemy) nebo rozmazaný. Černá úroveň se může mírně lišit (jiné analogové nastavení). AE: čas řádku je správně, ale expozice má strop 16,4 ms → v šeru víc zesílení (šum). Při 50Hz světle a 60 fps se uplatní ochrana proti blikání (expozice po 10 ms); kdyby byla expozice kratší než 10 ms, můžou se objevit pruhy.
3. **MIPI 255 Mbit/s** – data zaberou ~92 % řádku, na přechody zbývá ~1,8 µs (odhad potřeby 0,6–0,8 µs). Stejná rezerva jako dnešní ověřený režim při 510, ale žádná vendorová tabulka nemá 1152 px při 255 s tak krátkým řádkem (SC3336P má 25,1 µs). Při jakýchkoli chybách VICAP / rozpadlých řádcích **nejdřív vyzkoušet A**, teprve pak dělat závěry o binningu. (Prodloužit řádek jako SC3336P naslepo nejde – neznáme výchozí HTS SC3336.)
4. **VTS 680** (32 řádků rezervy) – kdyby dělal potíže spodní okraj: `nasad-60fps.sh B 58` (snímač i kodér 58 fps, VTS 703; stejný modul).
5. **Nástroje druhé session:** `vima-ctl.py`/`ovladani.py` mají rozlišení `640*360 … 2304*1296` – **1152*648 v seznamu není**, takže po přepnutí dolů se na nativní rozlišení nejde vrátit (jen restartem rkipc/desky) a větší rozlišení kodér odmítne (skript vrátí původní). `FPS_MAX = 30`: změna fps je jednosměrná (60 už nejde nastavit) a substream `/live/1` pak spadne na polovinu. `SMOOTH_GOP 500` = 8,3 s při 60 fps. **Během testu rozlišení ani fps ze země neměnit.** Do jejích souborů jsem nesahal – úpravy (přidat 1152*648, FPS_MAX 60, fps i pro stream 1) až po domluvě.
6. **Zátěž CPU:** IVS (detekce pohybu, `enable_ivs = 1`) dostane 60 snímků/s místo 30. Když `top` ukáže vysokou zátěž, vypnout `enable_ivs` (FPV ho nepotřebuje).
7. **Modul nesedí na jádro** (deska by měla jiné jádro než SDK) → insmod selže, kamera nejede, SSH ano → `vrat-30fps.sh`. Skript předem kontroluje `uname -r`.
8. Kamera neovlivňuje síť ani wfb ovladač; ani vadný modul by neměl shodit SSH. Krajní případ (deska nenaběhne): `sudo ~/vima-board/flash.sh ~/vima-board/fw-krok4/update-krok4.img` (firmware kroku 4 z 26. 10.; tlačítko BOOT + USB-C).

## 6. Postup testu na desce (až se souhlasem a po domluvě s druhou session)

Restart desky přeruší video i wfb – proto jen ve chvíli, kdy druhá session na desce nic neladí.

1. `~/vima-board/sc3336-60fps/deska/nasad-60fps.sh` – zkontroluje jádro a zápis do /oem, udělá zálohy, ukáže změny ini, nahraje varianta B. (Nic nerestartuje.)
2. Restart desky: `ssh luckfox reboot` (žádná fyzická akce).
3. `deska/over-60fps.sh` – čekám: `start mode 1152x648@60`, `data_rate_mbps 255`, VICAP fps ~60 a počet chyb se nezvyšuje, ISP vstup 1152x648, LSC ON, rkipc běží.
4. Obraz na laptopu: `~/vima-board/gs-video.sh` – 1152×648, ~60 fps (fpsdisplaysink), bez rozpadlých řádků a barevných pruhů.
5. Latence: stejná metoda jako 25. 10. (telefon 480 fps, stopky + blikající čtverec, `latence/latence.py`), stejné světlo a místo; ideálně 2× (60 fps a pro srovnání `vrat-30fps.sh`).
6. Kvalita: jemné vodorovné čáry / text (zubatost = skipping), šum ve tmě, černá (zakrytý objektiv), rohy obrazu (vinětace = LSC, `over-60fps.sh` ukáže sektory 40/41), 50Hz světlo (pruhy). Pozor: při 2048 kbit/s a 60 fps má kodér na pixel a snímek o ~38 % méně bitů než 720p30 – na posouzení detailu/šumu dočasně zvednout tok (adaptivní spoj vypnutý) nebo srovnávat se stejným počtem bitů na snímek, jinak se artefakty kodéru spletou s binningem.
7. Když něco nesedí: chyby VICAP / rozpadlé řádky → `nasad-60fps.sh A` + restart; spodní okraj → `nasad-60fps.sh B 58` + restart; divné rohy → LSC; vše ostatní → `vrat-30fps.sh` + restart.
8. Po úspěchu: domluvit úpravy `vima-ctl.py`/`ovladani.py` (fps 60, rozlišení ≤ 1152×648, GOP), pak `sdk-prepni.sh 60fps` a firmware – flash jen se souhlasem.

## 7. Revize po nezávislé kontrole (26. 10. večer)

Kontrolovalo 5 oblastí (registry, napojení ovladače, IQ, rkipc, skripty), každý závažnější nález ověřil skeptik. Ovladač a IQ: bez chyby. Opraveno:
- `vrat-30fps.sh` vracel pořád tu první zálohu → při dalším cyklu by tiše zahodil změny ini (např. od druhé session). Teď zálohy spotřebuje, hlídá změny a ověřuje md5.
- `nasad-60fps.sh`: chyba při zálohování/přenosu se dřív nepoznala → teď `cmp` zálohy, porovnání md5 a při chybě nic nepřepne. Parametr fps (58 = všechny 4 klíče).
- `sdk-prepni.sh`: po `puvodni` by Kbuild nechal 60fps `sc3336.o` (staré mtime obnoveného zdroje) a firmware by tiše měl 60fps modul s 30fps ini → `touch`; zálohy kopií pro balení by se dostaly do oem.img → `sdk-zaloha/`; selhání awk se nehlásilo → exit 1; stav podle md5.
- `over-60fps.sh`: ini se vypisovalo jen prvních 12 řádků (chybělo `fps = 60`), dmesg může být přepsaný → md5 modulu, výpis po sekcích, kontrola LSC v registrech.
- Text: rezerva MIPI u varianty B (A jako rovnocenná alternativa), 1152*648 není v seznamu rozlišení vima-ctl, bitový rozpočet při posuzování kvality.
Skripty pro desku vyzkoušeny na falešné desce (sandbox místo SSH): nasazení, opakované nasazení A/58, změna ini během testu, návrat s `-f`, druhý cyklus – vždy zpět bajtově na původní stav.
