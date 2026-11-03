#!/usr/bin/python3
# Vima krok 3: vyhodnoceni mereni z mereni-kf.py.
#   obnova obrazu = od prvniho paketu po ztrate do prvniho snimku, ktery se zase shoduje
#   se snimkem pred ztratou (scena se nehybe; prumerny rozdil jasu pod prahem ve 3 snimcich po sobe,
#   prah = max(PRAH, 15 % nejvetsiho poruseni); kdyz se scena pred ztratou hybala, ztrata se nehodnoti)
#   klicovy snimek = z udalosti.log (prijem.py): kdy po ztrate dorazil cely klicovy snimek
#   trhani = mezery mezi dekodovanymi snimky v klidu (bez ztrat)
# Pouziti: python3 analyza-kf.py [plan.json]   (bez argumentu posledni plan)
import glob
import json
import os
import struct
import sys

import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "mereni-kf")
PRAH = 2.0      # prumerny rozdil jasu 0-255 (rozbity obraz ~40-65, sum sceny ~0.01-1.5)
POHYB = 3.0     # rozdil dvou snimku pred ztratou (100 ms) nad tim = scena se hybala
REC = 12 + 80 * 45


def nahledy(t0, t1):
    ts, fs = [], []
    for p in sorted(glob.glob(os.path.join(OUT, "nahledy-*.bin"))):
        raw = open(p, "rb").read()
        for i in range(len(raw) // REC):
            t = struct.unpack_from("<d", raw, i * REC)[0]
            if t0 <= t <= t1:
                ts.append(t)
                fs.append(np.frombuffer(raw, np.uint8, 3600, i * REC + 12).reshape(45, 80).astype(np.int16))
    o = np.argsort(ts)
    return np.array(ts)[o], np.stack([fs[i] for i in o])


def udalosti():
    ev = []
    for ln in open(os.path.join(D, "udalosti.log")):
        p = ln.split()
        if len(p) >= 2:
            try:
                ev.append((float(p[0]), p[1], dict(x.split("=", 1) for x in p[2:] if "=" in x)))
            except ValueError:
                pass
    return ev


def stat(v):
    v = [x for x in v if x is not None]
    if not v:
        return "-"
    return "prumer %4.0f  median %4.0f  min %4.0f  max %5.0f ms  (n=%d)" % (np.mean(v), np.median(v), min(v), max(v), len(v))


def main():
    pf = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(OUT, "plan-*.json")))[-1]
    plan = json.load(open(pf))
    t, f = nahledy(plan["start"], plan.get("konec", 9e15))
    ev = udalosti()
    print("Plan %s, %d snimku" % (os.path.basename(pf), len(t)))
    vysl = {"varianty": [], "klid": []}
    for v in plan["varianty"]:
        losses = [e for e in ev if e[1] == "ZTRATA" and v["t0"] <= e[0] <= v["t1"]]
        obn, kf, porus, pocty, hybe = [], [], [], [], 0
        for i, (td, _, kv) in enumerate(losses):
            span = float(kv.get("videa_ms", 0))
            nxt = losses[i + 1][0] if i + 1 < len(losses) else v["t1"]
            i0 = np.searchsorted(t, td - span - 40) - 1          # posledni snimek pred ztratou
            if i0 < 0:
                continue
            ref = f[i0]
            js = np.where((t > td - 5) & (t < nxt))[0]
            d = np.array([np.abs(f[j] - ref).mean() for j in js])
            rec = None
            pohyb = float(np.abs(ref - f[max(0, i0 - 3)]).mean()) > POHYB
            thr = max(PRAH, 0.15 * d.max()) if len(d) else PRAH
            for k in range(len(d)):
                if not pohyb and (d[k:k + 3] < thr).all() and len(d[k:k + 3]) == 3:
                    rec = t[js[k]] - td
                    break
            hybe += pohyb
            obn.append(rec)
            porus.append(float(d.max()) if len(d) else 0.0)
            k_ev = [e for e in ev if e[1] == "KLICOVY" and "po_ztrate_ms" in e[2] and td <= e[0] < nxt]
            kf.append(float(k_ev[0][2]["po_ztrate_ms"]) if k_ev else None)
            pocty.append(int(kv.get("paketu", 0)))
        print("\n%s (ztrat %d, ztraceno paketu %s)" % (v["nazev"], len(losses), pocty))
        print("  obnova obrazu:    %s%s" % (stat(obn), "  (%d ztrat nehodnoceno - scena se hybala)" % hybe if hybe else ""))
        print("  klicovy snimek:   %s" % stat(kf))
        print("  nejvetsi poruseni obrazu (rozdil jasu): %s" % ([round(x, 1) for x in porus]))
        vysl["varianty"].append({"nazev": v["nazev"], "obnova_ms": obn, "klicovy_ms": kf, "poruseni": porus, "paketu": pocty})
    for k in plan["klid"]:
        sel = (t >= k["t0"]) & (t <= k["t1"])
        g = np.diff(t[sel])
        if len(g) == 0:
            continue
        dur = (k["t1"] - k["t0"]) / 1000
        losses = [e for e in ev if e[1] == "ZTRATA" and k["t0"] <= e[0] <= k["t1"]]
        print("\nklid %s: snimku %d za %.0f s, mezera median %.0f, p99 %.0f, max %.0f ms, mezer >60 ms: %d, ztrat %d"
              % (k["nazev"], len(g) + 1, dur, np.median(g), np.percentile(g, 99), g.max(), int((g > 60).sum()), len(losses)))
        vysl["klid"].append({"nazev": k["nazev"], "snimku": int(len(g) + 1), "s": dur, "median": float(np.median(g)),
                             "p99": float(np.percentile(g, 99)), "max": float(g.max()), "nad60": int((g > 60).sum()),
                             "ztrat": len(losses)})
    if plan.get("pojistka"):
        print("\npojistka (prijimac mlci): %s" % plan["pojistka"])
        vysl["pojistka"] = plan["pojistka"]
    jf = pf.replace("plan-", "vysledky-")
    json.dump(vysl, open(jf, "w"), indent=1)
    print("\nUlozeno: %s" % jf)


if __name__ == "__main__":
    main()
