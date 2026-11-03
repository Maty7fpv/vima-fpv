#!/usr/bin/env python3
# Vima: strop expozice v IQ souboru SC3336 (LinearAeCtrl.Route.TimeDot) - kratsi expozice = nizsi zpozdeni.
# Na desce plati jen spolu s vypnutou ochranou proti blikani (rkipc ini: power_line_frequency_mode = close),
# jinak AE drzi expozici v nasobcich 10 ms. Soubor se meni jen textove (CRLF, taby zustanou).
# pouziti: strop-expozice.py vstup.json vystup.json [strop_v_sekundach]   (vychozi 0.004 = 4 ms)
import sys

src, dst = sys.argv[1], sys.argv[2]
cap = sys.argv[3] if len(sys.argv) > 3 else "0.004"
float(cap)
t = open(src, "rb").read().decode("utf-8")
old = '"TimeDot":\t[0, 0.01, 0.01, 0.02, 0.03, 0.03]'
assert t.count(old) == 1, ("TimeDot nenalezen nebo vic vyskytu", t.count(old))
t = t.replace(old, '"TimeDot":\t[0, ' + ", ".join([cap] * 5) + "]")
open(dst, "wb").write(t.encode("utf-8"))
print("OK:", dst, "TimeDot strop", cap, "s")
