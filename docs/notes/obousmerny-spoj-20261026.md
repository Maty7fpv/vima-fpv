# Vima – obousměrná komunikace přes wfb-ng (stav práce)

Uloženo: 25. 10. 2026 ~20:20. Dokument s výsledky: https://claude.ai/artifact/XEjdQZVgVYV2EDMUxcXPUS

## Zadání (4 kroky, po každém kroku STOP a čekat na potvrzení uživatele)
1. IP tunel vzduchem (wfb_tun), naběhne sám na desce, výkon laptopu pod limitem, ping + SSH vzduchem, vliv na video. – **HOTOVO, uživatel potvrdil**
2. Ovládání desky ze země přes tunel: datový tok, rozlišení, fps, výkon, kanál (bezpečné přepnutí obou konců s návratem). Co jde bez restartu rkipc, kolik trvá výpadek. Jednoduché ovládání na laptopu. – **HOTOVO, uživatel potvrdil (okno funguje, 25. 10. ~22:05)**
3. Žádost o klíčový snímek při ztrátě (rkipc/RKMPI za běhu?), změřit zkrácení obnovy obrazu. – **HOTOVO 26. 10. ~19:50, čeká na potvrzení uživatele**
4. Adaptivní spoj: laptop posílá kvalitu příjmu, deska mění tok (příp. MCS/FEC), hystereze, bezpečné nastavení při ztrátě uplinku, srovnání zap/vyp. – **HOTOVO 26. 10. ~21:50, čeká na potvrzení uživatele**

Pravidla: řízení dronu přes tento spoj NE (RC = ELRS 868 MHz). Vše do SDK/firmwaru. **Flash až na konci (po kroku 4) a jen po souhlasu** (uživatel 25. 10. potvrdil „flash až na konci“). Výsledky každého kroku do dokumentu výše. Česky, jednoduše, max 1–2 fyzické kroky.

## Krok 1 – co je hotové
Deska (nahráno na desku I v SDK overlay `~/luckfox-pico/project/cfg/BoardConfig_IPC/overlay/overlay-vima/`):
- `lib/modules/5.10.160/extra/tun.ko` – externí modul (jádro nemá CONFIG_TUN), build: `~/vima-board/tun-ko/build.sh` (v distroboxu luckfox). Jádro beze změny.
- `usr/bin/wfb_tun` – cross build: `~/vima-board/wfb-ng/wfb_tun.board` (log build-arm-tun.log).
- `usr/bin/vima-wfb` – TUN_*: tun_loop (wfb_tun -t wfb-tun -a 10.5.0.2/24 -u 5801 -l 5800 -T 5), wfb_tx -f data -p 32 -k 1 -n 2, wfb_rx -p 160 -u 5800, samostatný restart spadlých procesů tunelu, IPv6 vypnuté na wfb-tun, tun_limit (iptables hashlimit 37 kB/s = 300 kbit/s; jádro nemá tc).
- `etc/vima/vima.conf` – TUN_ENABLE=1, TUN_IF, TUN_ADDR, TUN_TX_PORT=32, TUN_RX_PORT=160, TUN_FEC_K/N=1/2, TUN_AGG_MS=5, TUN_RATE_KBIT=300.
- `etc/init.d/S98vimawfb` – stop zabíjí i wfb_rx, wfb_tun.
- rkipc: `project/app/rkipc/rkipc/common/network/network.c` – přeskakuje rozhraní `wfb*` (jinak udhcpc smazal adresu tunelu). Přestavěno (`project/app/rkipc/build`, make), na desce /oem/usr/bin/rkipc (stripped), v `output/out/app_out/bin/rkipc` pro firmware. Originál: `~/vima-board/fw-20261025/network.c.orig`.
- Zálohy před tunelem: `~/vima-board/fw-20261025/*.pred-tunelem`.

Laptop:
- `~/vima-board/tunel.sh` (bez sudo, řekne si o heslo; `kalibrace` = projde výkon): wfb_tun 10.5.0.1, wfb_tx -p 160 -k 1 -n 3 -F 3000 -C 8101, wfb_rx -p 32, tc tbf 300 kbit, výkon z kanal.conf.
- `~/vima-board/kanal.conf`: LAPTOP_TXPWR_IDX_2G=38, LAPTOP_TXPWR_IDX_5G=8 (kalibrace: laptop o ≤6 dB silnější než deska při stejném indexu, 0,52 dB/krok).
- `~/vima-board/gs-video.sh` – zabíjí jen svůj wfb_rx (`pkill -f '[w]fb_rx -p 0 '` – závorka kvůli self-match!), kartu přenastaví jen když není monitor na kanálu.
- `~/.ssh/config`: Host luckfox-air (10.5.0.2).
- Výsledky: `~/vima-board/tunel-mereni-20261025.txt`, `kalibrace-laptop-20261025.txt`.

Výsledky kroku 1: ping 15,9 ms (12,7–42,8), ztráty ~1 % (bez 3 kopií s odstupem 6,5 %); SSH bez ethernetu 0,63 s; video 0 ztrát při klidu i pingu 20/s; scp 1 MB bez stropu = 141 ztracených paketů videa, se stropem 300 kbit/s 0 ztrát (1 MB za 25–29 s).

## Pozor (poučení)
- `pkill -f 'vzor'` uvnitř `sudo bash -c "..."` najde i sám sebe → vzor psát `'[w]fb_...'`.
- Staré běžící verze skriptů mají v paměti staré trapy (stará gs-video.sh zabila `pkill -x wfb_rx` všechny přijímače).
- Uživatel občas spustí tunel.sh dvakrát → druhý převezme kartu; starý ukončit `kill -9` (bez trapu, jinak `pkill -x wfb_tun` shodí nový).
- Ztráty uplinku = karta desky vysílá video ~40 % času (FEC 8/16 s -T 5 → ~330 rámců/s pro ~65 paketů videa/s).

## Krok 2 – plán (nezačato)
- Zjistit, co jde v rkipc měnit za běhu (RK_MPI_VENC_SetChnAttr: bitrate/fps/gop; rozlišení asi jen restartem pipeline/rkipc → změřit výpadek). rkipc má vlastní rozhraní? (hledat rkipc „socket“, „/tmp/rkipc“, web/ini set API – common/socket, rk_param_set).
- Výkon: rtw_tx_pwr_idx_override + iw set txpower za běhu (bez výpadku).
- MCS/FEC videa za běhu: wfb_tx -C <port> + wfb_tx_cmd set_radio/set_fec (video wfb_tx zatím nemá pevný -C).
- Kanál: dvoufázové přepnutí (příkaz s časem přepnutí, oba konce, ověření pingem, jinak návrat po timeoutu).
- Démon na desce (python3) poslouchající na tunelu (UDP), laptop příkaz `deska.sh`/okno. Firewall laptopu (firewalld, zóna public) blokuje UDP iniciované deskou → odpovědi řešit v rámci stejného spojení nebo port otevřít (sudo + souhlas).

## Krok 2 – co je hotové (25. 10. ~21:50)
Deska (SDK overlay + nahráno): `usr/bin/vima-ctl.py` (UDP 5900, rkipc socket /var/tmp/rkipc: max_rate/frame_rate+gop/resolution; výkon iw; dvoufázový kanál ch_prepare/abort/confirm(jen z 10.5.0.1)/commit, návrat po 4 s, opakovaný návrat, hlídač kanálu vs vima.conf a výkonu vs strop, pevné stropy 50/20, zámek /var/run/vima-radio.lock); `vima-wfb` (ctl_loop, -C 8000 video / -C 8001 tunel, setup_if: re-source conf, ch_ok whitelist, pwr_idx clamp 1..50/20, výkon před kanálem, flock, insmod s idx 20); `vima.conf` (CTL_ENABLE=1, WFB_CTRL_PORT, TUN_CTRL_PORT, komentář 0 = zakázáno; po commitu WFB_CHANNEL + WFB_CHANNEL_TOK); S98 stop killall vima-ctl.py. Zálohy: fw-20261025/*.pred-ovladanim.
Laptop: `ovladani.py` (stav|tok|fps|gop|rozliseni|vykon|kanal|najdi|okno GTK4; root pomocník `pomocnik` na /run/user/1000/vima-pomocnik.sock spouští tunel.sh, stropy 38/8, pojistka navrat_s 9 s), `prijem.py` (okno videa + snimky.log), gs-video.sh (prijem.py, nepřeladí kartu když běží tunel), tunel.sh (stropy 38/8, kalibrace max 38/8, výkon 8 před kanálem + readback, trap jen vlastní PID), rx-test.sh (idx 8, odmítne při tunelu), deska.sh (bez 36-48, nemaže LAPTOP_*). Zálohy *.bak-ovladani.
Měření: ~/vima-board/ovladani-mereni-{video,kanal,navrat}.txt. Normální max mezera obrazu ~100 ms/3 s (I-snímek 1×/s); tok/fps/výkon beze změny, rozlišení +40–100 ms, kanál 96–133 ms, chyby: deska zpět po 4 s (4,3 s výpadek), pojistka laptopu 3,4 s, hlídač 0,3 s.
Doporučení pro uživatele (neprovedeno, sudo): /etc/modprobe.d/88XXau_wfb.conf override=30 → 8.

## Krok 3 – kde se skončilo (25. 10. ~22:20)
Uživatel potvrdil pokračování krokem 3, pak požádal o uložení a ukončení. Průzkum (workflow) byl zastaven, výsledky nejsou.
Známé z průzkumu kroku 2: RK_MPI_VENC_RequestIDR(chn, RK_FALSE) existuje v librockit (RK_TRUE nepodporováno), rkipc nemá socket příkaz → patch jen v common/socket_server/server.c:
  int ser_rk_video_request_idr(int fd){int id,err; if(sock_read(fd,&id,sizeof(id))==SOCKERR_CLOSED) return -1; err=RK_MPI_VENC_RequestIDR(id, RK_FALSE); if(sock_write(fd,&err,sizeof(int))==SOCKERR_CLOSED) return -1; return 0;}
  + map entry {(char *)"rk_video_request_idr", &ser_rk_video_request_idr},
Plán: (1) patch + rebuild rkipc (project/app/rkipc/build, make v distroboxu; strip; na desku /oem/usr/bin/rkipc + output/out/app_out/bin/rkipc; reboot desky); (2) vima-ctl.py op "keyframe" (rk_set_int-like: send id, read err, final); (3) prijem.py: probe na udpsrc – RTP seq mezery = nezachráněná ztráta → UDP {"op":"keyframe"} na 10.5.0.2:5900 (max 1x/300 ms, opakovat když IDR nepřijde do 200 ms, max 3x), detekce IDR (NAL 19/20, FU typ 49 → byte2&0x3f), log událostí; (4) měření obnovy: ztráta uměle na desce `iptables -I INPUT -p udp --dport 5602 -j DROP` na 200–300 ms přes ssh, obnova = konec ztráty → první IDR; varianty GOP 30 / dlouhý GOP (150–300) bez požadavku / s požadavkem; (5) bonus: intra refresh (RK_MPI_VENC_SetIntraRefresh?) proti trhnutí 1x/s (I-snímek 2304x1296 až 190 ms vzduchem, uživatel to viděl jako „mikro lag“), případně MaxIprop; (6) dokument sekce Krok 3 (pending blok mj8q19n5nvn.50).
Pozn.: uživatel v okně nastavil desce 2304x1296, 3072 kbit/s (dočasné, po restartu desky zpět 1280x720/2048/30/GOP30).
Firmware zatím NEflashován – flash až po kroku 4 se souhlasem (build: ./build.sh firmware nepřestaví app → rkipc + ini ručně do output/out/app_out; overlay obsahuje vše ostatní).

## Krok 3 – co je hotové (26. 10. ~19:50, čeká na potvrzení uživatele)
Deska (SDK + nahráno):
- rkipc: `common/socket_server/server.c` + `src/rv1106_ipc/video/video.{c,h}` – nový příkaz socketu `rk_video_request_idr` (RK_MPI_VENC_RequestIDR(chn, RK_FALSE)). Přestavěno, stripped na desce /oem/usr/bin/rkipc (md5 02769b57…), nestripped v output/out/app_out/bin/rkipc (31eee748…). Zálohy: fw-20261025/*.pred-idr, rkipc.deska-pred-idr, rkipc.app_out-pred-idr.
- Intra refresh NEJDE: RK_MPI_VENC_SetIntraRefresh vrátí 0, ale MPP píše „mpp_enc_cfg_set_u32 failed to set rc:refresh_en“ (klíč v MPP tohoto SDK není). GOP max 500 (venc_info ukáže 500 i pro víc).
- vima-ctl.py: op keyframe (limit 10/s, počty v status.kf), rx_alive, set_smooth; plynulý obraz = GOP 500 jen když rx_alive < 3 s, jinak GOP = fps (smooth_tick v timers 1×/s); set_gop odmítne při plynulém; set_fps dá GOP 500 v plynulém. Odpovědi přes IP_PKTINFO ze stejné adresy (eth0 má i DHCP 10.42.0.12 vedle 10.42.0.2 → odpovědi přes kabel firewall laptopu zahazoval).
- vima.conf: VIDEO_SMOOTH=1 (výchozí zapnuto; na desce zapnuto přes ovladani.py).
- Pozn.: /userdata/rkipc.ini se při každém bootu přepíše z /oem/usr/share/rkipc-300w.ini (RkLunch.sh); rkipc při ukončení ukládá parametry z paměti do /userdata/rkipc.ini.
Laptop:
- prijem.py: RTP probe (mezera seq → ZTRATA → ZADOST přes 10.5.0.2:5900, opakování 250 ms, max 1×/300 ms; detekce IDR NAL 19/20 → KLICOVY), rx_alive 1×/s, prijem.conf (ZADOST_KF, MERENI), SIGHUP → exit 3; udalosti.log; MERENI=1 → mereni-kf/nahledy-*.bin (80×45 jas).
- gs-video.sh: návratový kód 3 = okno hned znovu. ovladani.py: klicovy, plynule zap|vyp, zadosti zap|vyp, řádek stavu (ztráty obrazu/min, obnova), okno s volbami. Zálohy *.bak-kf.
- mereni-kf.py (varianty, umělá ztráta iptables DROP UDP 5602 na desce 250 ms přes ssh kabel), analyza-kf.py.
Výsledky (mereni-kf/vysledky-20261026-194055.{txt,json}): obnova A GOP30 bez žádosti 489 ms (227–896), B GOP30 se žádostí 100 (96–108), C GOP150 bez 2851 (1059–4534), D plynulý se žádostí 99 (95–102); klíčový snímek dorazí za 93 ms (89–101). Trhnutí ≥90 ms za 20 s: 720p GOP30 17× vs plynulý 1×; 2304x1296/3072 GOP30 21× (163–184 ms) vs plynulý 2×. Pojistka: GOP 500→30 za 3,2 s po umlčení, zpět za 1,1 s.
Dokument: sekce Krok 3 vyplněna, Shrnutí upraveno (rev 8).
Další: čekat na potvrzení kroku 3, pak krok 4 (adaptivní spoj; rx_alive lze rozšířit o kvalitu příjmu). Flash až po kroku 4 se souhlasem.

## Krok 3 – doplněk po připomínce uživatele (26. 10. ~20:10)
Uživatel: „stále se to trochu zadrhne, změř to; panel ať při otevření čte aktuální hodnoty“.
Zjištěno (mereni-kf/trhani-20261026-195847.*, trhani-mcs-20261026-200456.*; prijem.py při MERENI=1 zapisuje i prichody-*.log a dekod-*.log; mereni-trhani.py + analyza-trhani.py):
1. Uživatel měl v panelu „Žádat klíčový snímek“ = vyp (panel ukazoval první položku seznamu, ne skutečný stav) → plynulý obraz neaktivní, GOP 25 → klíčový snímek 1×/s. Zapnuto zpět (prijem.conf ZADOST_KF=1).
2. 25 fps: rkipc rk_video_set_frame_rate jen zahazoval snímky z 30 fps snímače (RTP rozestupy 33/67 ms). Oprava ve vima-ctl op_set_fps: nejdřív rk_isp_set_frame_rate(fps) (snímač), pak rk_video_set_frame_rate → rozestup přesně 40 ms (ověřeno 20/25/30). status má sensor_fps (venc SrcFr). Nasazeno na desku + SDK.
3. Zbývající jitter ve vzduchu: MCS 1 p99 67–89 ms navíc, MCS 3 35–39 ms → krok 4 (MCS/FEC adaptivně).
Zádrhely ≥2 snímky / 30 s (2304x1296 3072 25 fps): postaru 31, opraveno+plynulý 2, GOP 25 23.
ovladani.py okno: seznamy a tlačítka „Nastavit“ zamčené, dokud se nenačte stav; po otevření a po každé změně nastaví skutečné hodnoty (chybějící hodnotu přidá do seznamu). Zálohy prijem.py.bak-trhani.
Pozn.: uživatel během měření přepínal kanály (7, 165, 149, 1) – teď kanál 1 (vima.conf i kanal.conf). Displeje laptopu 2560x1440@180 a 1920x1080@100.
Dokument rev 9: doplněn odstavec „Druhé měření zádrhelů“.

## Krok 4 – co je hotové (26. 10. ~21:50, čeká na potvrzení uživatele)
Uživatel: 60 Mb/s a 50 ms jsou jen orientační cíle; chtěl volbu pásma 2,4/5,8 GHz v panelu (hotovo: řádek „Pásmo“, CLI `pasmo 2.4|5.8`, kanal.conf CH_2G_POSLEDNI/CH_5G_POSLEDNI, seznam kanálů jen pro pásmo).
Kapacita (kapacita.py + kapacita-deska.py, prijem.py PAUZA; mereni-kf/kapacita-vysledky-20261026-202720.*): FEC 8/16 bez fronty MCS0 ~2,1, MCS1 ~3,3, MCS2 ~6,3, MCS3 ~6,5–8,4, MCS4 ~9,7, MCS5–7 ~9–11 Mbit/s (CPU desky 93–100 %, wfb_tx dropped). Deska si přes NTP (rkipc ntp_client_thread, server 119.28.183.184 přes NAT laptopu) přestavuje hodiny → časy v logu desky nesedí.
Průzkum (workflow, výsledky v scratchpad res-*.md): override indexu = jeden index pro všechna MCS (1 řetězec bez STBC) → vyšší MCS nevysílá silněji; 64-QAM (MCS5-7) bez by-rate snížení → riziko EVM → ladder max MCS4. HT40 vyžaduje iw set channel HT40± na obou stranách. SET_FEC restartuje relaci, SET_RADIO okamžitě. EN 300 328: neadaptivní >10 dBm EIRP → max 10 % MU (ověřit). SC3336 60 fps: 1152x648 binning 2x2 (registry z RT-Thread drv_sc3336.c / sc3336p.c) → samostatná session (task_5882b11d) to připravuje.
Deska vima-ctl.py: sekce „krok 4: adaptivni spoj“ – PROFILY MCS0 800 / MCS1 1600 / MCS2 2800 / MCS3 3800 / MCS4 5500 kbit/s (strop = min(profil, user_kbps)), SNR prahy 0/8/11/14/18, kf_min_s 0.8/0.4/0.1…; dolů: SNR průměr < práh, FEC>15 %, 2× pkt=0, ztráty (při SNR ≥ práh+4 dB až 3 hlášení se ztrátou za 3 s); nahoru: 3 s OK, SNR min ≥ další+3 dB, FEC<8 %, žádná ztráta 3 s; block 6→30 s po nepovedeném pokusu (pád do 10 s po kroku nahoru); okno ≥1 s a ≥150 pkt (max 3 s); settle 0,6 s; bez hlášení 1,5 s (≥2,5× interval) → profil 0; resync MCS/tok 1×/s; alink_stall při dlouhých příkazech; user_kbps v /var/run/vima-user-kbps; op set_alink, rx_report (rx_alive jen při zadost=True); status alink i během přepínání kanálu. vima.conf ALINK (SDK výchozí 0, na desce 1). Zálohy fw-20261025/vima-ctl.py.pred-alink, .pred-review4.
Laptop: prijem.py posílá rx_report z gs-video.log (wfb_rx -l 200) s každým intervalem (i při ZADOST_KF=0, příznak zadost), PAUZA mód, tick chráněný try/except, odložené žádosti o KF se nepočítají; gs-video.sh -l 200; ovladani.py adaptivni zap|vyp, řádek stavu, tok v panelu = user_kbps; kapacita.py vypíná alink během měření. Zálohy *.bak-alink, *.bak-report, *.bak-review4, *.bak-pasmo.
Kontrola kódu (workflow, 3 dimenze + ověření): 24 potvrzených nálezů opraveno.
Srovnání (mereni-alink.py vzduch, laptop v jiné místnosti −53 dBm, výkon desky 50→1→50, kanál 1; mereni-kf/alink-beh{,2,3}.txt): střední signál vždy o 35–60 % méně záseků s adaptivním (25/62, 20/52, 22/34), ztráty 35/58, 24/79, 54/27; hranice dosahu nejednoznačné. Kola 2–3 odhalila: okno při malém toku (opraveno) a pády kvůli ztrátám z rušení (opraveno: ztráty při silném SNR jen opakované). Finální verze ověřena simulací (7 situací), vzduchem ještě ne.
Dokument rev 10: sekce Krok 4, Shrnutí, checklist.
Další: potvrzení uživatele; nabídnout 4. měření finální verze; rozhodnout ALINK výchozí ve firmwaru; pak firmware build (overlay + app_out rkipc) a flash JEN se souhlasem; sekce „Soubory, firmware a postupy“ (pending .52).

## Firmware a flash (26. 10. ~21:45) – HOTOVO
Uživatel potvrdil krok 4, chtěl ALINK výchozí a sestavit firmware; flash spustil sám (`sudo flash.sh`) = souhlas.
- SDK overlay vima.conf: ALINK=1, VIDEO_SMOOTH=1, WFB_CHANNEL=13 (výchozí). Overlay = deska (md5), app_out rkipc 31eee748 (v oem obrazu stripped = deska 02769b57).
- `./build.sh firmware` (distrobox luckfox), log ~/vima-board/build-firmware-krok4.log; obraz ~/vima-board/fw-krok4/update-krok4.img sha256 4353d05d64ed1f11cc9aebff7fdb921729289d503063c88d1a693f45df468d7b; boot.img stejný jako 25. 10.; porovnání obraz↔deska ve fw-krok4/*.md5.
- Flash OK; po flashi: ssh-keygen -R 10.42.0.2 (nové host klíče), host mód, coherent_pool=256K, kanál 13, ALINK/SMOOTH zap, md5 vima-ctl 196edf73 / rkipc 02769b57. Laptop přeladěn `ovladani.py najdi` (CH=13, CH_2G_POSLEDNI=13), alink do 10 s na MCS 4.
- Pozn.: obraz z 25. 10. večer (302d1134) byl přepsán sestavením; návrat jen na fw-20261025/update-2304x1296-25fps.img nebo backup-20261019.
- Dokument rev 12: sekce „Soubory, firmware a postupy“, checklist kompletní.
Otevřené: vzdušné měření finální verze alink; profil 0 s nižším rozlišením; EN 300 328 (10 % MU na 2,4 GHz nad 10 mW); 60 fps SC3336 (samostatná session task_5882b11d); NTP skoky hodin desky.
