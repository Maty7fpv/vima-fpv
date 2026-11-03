#!/usr/bin/python3
# Vima krok 4: vyhodnoceni kapacita.py. Pro kazdy krok (MCS, tok): kolik testovacich paketu doslo,
# ztraty, zpozdeni navic (proti nejrychlejsim paketum celeho mereni) a zatizeni CPU desky.
# Pouziti: python3 analyza-kapacita.py [kapacita-plan-*.json]
import glob
import json
import os
import sys

import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "mereni-kf")


def main():
    pf = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(OUT, "kapacita-plan-*.json")))[-1]
    r = json.load(open(pf))
    rows = []
    for lf in sorted(glob.glob(os.path.join(OUT, "kapacita-2*.log"))):
        for ln in open(lf):
            v = ln.split()
            if len(v) == 4:
                rows.append([float(x) for x in v])
    a = np.array(rows)
    a = a[(a[:, 0] >= r["start"] - 5000) & (a[:, 0] <= r.get("konec", 9e15) + 5000)]
    a = a[a[:, 1] < max(k["seq1"] for k in r["kroky"])]        # jen testovaci pakety (ne zbytky videa)
    dd = a[:, 0] - a[:, 2] / 1000.0
    a = a[np.abs(dd - np.median(dd)) < 10000]
    off = np.percentile(a[:, 0] - a[:, 2] / 1000.0, 0.5)       # posun hodin deska -> laptop + nejkratsi cesta
    vysl = []
    print("Plan %s, %d testovacich paketu" % (os.path.basename(pf), len(a)))
    print(" MCS  tok kbit/s  doslo %   ztraty %   zpozdeni navic p50/p95/max ms   CPU wfb_tx %  celkem %  zahozeno")
    for k in r["kroky"]:
        sel = a[(a[:, 1] >= k["seq0"]) & (a[:, 1] < k["seq1"])]
        n = k["seq1"] - k["seq0"]
        got = len(np.unique(sel[:, 1])) if len(sel) else 0
        ex = sel[:, 0] - sel[:, 2] / 1000.0 - off if len(sel) else np.array([np.nan])
        d = {"mcs": k["mcs"], "kbps": k["kbps"], "vyslano": n, "doslo": got,
             "ztraty_pct": round(100.0 * (n - got) / max(1, n), 2),
             "zpozdeni_p50": round(float(np.nanpercentile(ex, 50)), 1),
             "zpozdeni_p95": round(float(np.nanpercentile(ex, 95)), 1),
             "zpozdeni_max": round(float(np.nanmax(ex)), 1),
             "cpu_wfb_tx": k["cpu_wfb_tx"], "cpu_celkem": k["cpu_celkem"], "zahozeno": k.get("dropped")}
        vysl.append(d)
        print(" %3d  %10d  %7.1f  %8.2f   %6.1f / %6.1f / %6.1f        %6.1f  %7.1f  %s"
              % (d["mcs"], d["kbps"], 100.0 * got / max(1, n), d["ztraty_pct"], d["zpozdeni_p50"], d["zpozdeni_p95"],
                 d["zpozdeni_max"], d["cpu_wfb_tx"], d["cpu_celkem"], d["zahozeno"]))
    jf = pf.replace("kapacita-plan-", "kapacita-vysledky-")
    json.dump(vysl, open(jf, "w"), indent=1)
    print("Ulozeno: %s" % jf)


if __name__ == "__main__":
    main()
