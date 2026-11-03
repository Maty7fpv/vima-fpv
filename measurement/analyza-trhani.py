#!/usr/bin/python3
# Vima: vyhodnoceni mereni-trhani.py. Pro kazde nastaveni rozlisi, kde zadrhel vznikl:
#   deska  - mezera v RTP casech (snimek vubec nevznikl / kamera ho zahodila)
#   vzduch - snimek dorazil o vic nez polovinu snimkoveho intervalu pozdeji nez obvykle
#   laptop - dekodovany snimek prisel pozde, i kdyz dorazil vcas
# Zadrhel = mezera mezi dekodovanymi snimky aspon 1,5x snimkovy interval.
# Pouziti: python3 analyza-trhani.py [trhani-*.json]
import glob
import json
import os
import sys

import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "mereni-kf")


def nacti(prefix, t0, t1, col_t):
    rows = []
    for p in sorted(glob.glob(os.path.join(OUT, prefix + "-*.log"))):
        for ln in open(p):
            v = ln.split()
            try:
                t = float(v[col_t])
            except (ValueError, IndexError):
                continue
            if t0 <= t <= t1:
                rows.append([float(x) for x in v])
    return np.array(rows)


def main():
    pf = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(OUT, "trhani-*.json")))[-1]
    plan = json.load(open(pf))
    vysl = []
    print("Plan %s" % os.path.basename(pf))
    for w in plan["okna"]:
        per = 1000.0 / w["fps"]
        pr = nacti("prichody", w["t0"], w["t1"], 1)      # t_prvni, t_posledni, rtp, bajty, pakety, klicovy
        dk = nacti("dekod", w["t0"], w["t1"], 0)          # t, pts
        if len(pr) < 10 or len(dk) < 10:
            print("\n%s: malo dat" % w["nazev"])
            continue
        pr = pr[pr[:, 3] > 200]                           # bez samotnych VPS/SPS/PPS
        rtp_ms = np.unwrap(pr[:, 2], period=2 ** 32) / 90.0
        src_gap = np.diff(rtp_ms)
        delay = pr[:, 1] - rtp_ms
        extra = delay - np.percentile(delay, 5)           # zpozdeni navic proti nejrychlejsim snimkum
        dgap = np.diff(dk[:, 0])
        dur = (w["t1"] - w["t0"]) / 1000.0
        zadrhel = dgap >= 1.5 * per
        # pricina kazdeho zadrhele: najit snimek, ktery se dekodoval po mezere (nejblizsi prichod pred nim)
        pric = {"deska": 0, "vzduch": 0, "laptop": 0}
        for i in np.where(zadrhel)[0]:
            t_dec = dk[i + 1, 0]
            j = np.searchsorted(pr[:, 1], t_dec) - 1
            if j < 1:
                continue
            if src_gap[j - 1] >= 1.5 * per:
                pric["deska"] += 1
            elif extra[j] >= 0.5 * per:
                pric["vzduch"] += 1
            else:
                pric["laptop"] += 1
        velke = pr[:, 3] >= np.percentile(pr[:, 3], 99)
        r = {"nazev": w["nazev"], "fps": w["fps"], "gop": w["gop"], "snimac_fps": w.get("sensor_fps"),
             "snimku": int(len(dk)), "s": round(dur, 1),
             "zadrhelu": int(zadrhel.sum()), "zadrhelu_za_10s": round(zadrhel.sum() / dur * 10, 1),
             "nejdelsi_ms": round(float(dgap.max())), "pricina": pric,
             "mezery_rtp_ms": {str(int(round(k))): int(v) for k, v in zip(*np.unique(np.round(src_gap), return_counts=True))},
             "zpozdeni_navic_p50_p99_max": [round(float(np.percentile(extra, 50))), round(float(np.percentile(extra, 99))),
                                            round(float(extra.max()))],
             "klicovych": int(pr[:, 5].sum()), "velikost_p50_max_kB": [round(float(np.median(pr[:, 3])) / 1000, 1),
                                                                    round(float(pr[:, 3].max()) / 1000, 1)],
             "zpozdeni_velkych_snimku": round(float(np.median(extra[velke]))) if velke.any() else None}
        vysl.append(r)
        print("\n%s (GOP %s, snimac %s fps): %d snimku za %.0f s" % (w["nazev"], w["gop"], w.get("sensor_fps"), len(dk), dur))
        print("  zadrhelu (mezera >= %.0f ms): %d, tj. %.1f za 10 s, nejdelsi %d ms; pricina: deska %d, vzduch %d, laptop %d"
              % (1.5 * per, r["zadrhelu"], r["zadrhelu_za_10s"], r["nejdelsi_ms"], pric["deska"], pric["vzduch"], pric["laptop"]))
        print("  rozestup snimku na desce (ms: pocet): %s" % r["mezery_rtp_ms"])
        print("  zpozdeni navic vzduchem p50/p99/max: %s ms; klicovych snimku %d; velikost snimku median/max %s kB"
              % (r["zpozdeni_navic_p50_p99_max"], r["klicovych"], r["velikost_p50_max_kB"]))
    jf = pf.replace("trhani-", "trhani-vysledky-")
    json.dump(vysl, open(jf, "w"), indent=1, ensure_ascii=False)
    print("\nUlozeno: %s" % jf)


if __name__ == "__main__":
    main()
