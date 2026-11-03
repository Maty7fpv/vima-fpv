#!/usr/bin/python3
# Vima krok 4: srovnani adaptivniho spoje zap/vyp pri "vzdalovani" (simulovane snizovanim vykonu desky).
# Vykon desky se po krocich snizi z 50 na 1 (asi -25 dB) a zase zvysi; pro kazdy krok se zaznamena:
# ztraty obrazu, doba rozbiteho obrazu (udalosti.log), zadrhy (snimky.log), dorucene kbit/s a SNR
# (gs-video.log), profil adaptivniho spoje. Nastaveni desky jde pres kabel (10.42.0.2), s volbou
# "vzduch" pres tunel (10.5.0.2; prikazy z laptopu dojdou i pri slabem signalu desky, odpoved
# se muze ztratit - pak se pokracuje). Vykon se jen snizuje pod zakonny strop a na konci se vrati.
# Pouziti: python3 mereni-alink.py [rychle] [vzduch]
import json
import os
import socket
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "mereni-kf")
VZDUCH = "vzduch" in sys.argv
DESKA = ("10.5.0.2", 5900) if VZDUCH else ("10.42.0.2", 5900)
RYCHLE = "rychle" in sys.argv
KROKY = [50, 43, 36, 29, 22, 15, 10, 6, 3, 1, 3, 6, 10, 15, 22, 29, 36, 43, 50]
DRZET_S = 7
if RYCHLE:
    KROKY, DRZET_S = [50, 20, 50], 4
_id = [int(time.time()) & 0xffff]


def deska(op, **kw):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.5 if VZDUCH else 5)
    _id[0] += 1
    try:
        for _ in range(5 if VZDUCH else 3):
            s.sendto(json.dumps(dict(op=op, id=_id[0], **kw)).encode(), DESKA)
            try:
                r = json.loads(s.recv(65535).decode())
            except socket.timeout:
                continue
            if r.get("id") == _id[0]:
                if not r.get("ok"):
                    raise RuntimeError("%s: %s" % (op, r.get("err")))
                return r["res"]
        raise RuntimeError("%s: deska neodpovida" % op)
    finally:
        s.close()


def zkus(op, **kw):
    try:
        return deska(op, **kw)
    except Exception as e:  # noqa: BLE001  slaby signal: odpoved se ztratila, prikaz ale nejspis prosel
        print("   (%s: %s)" % (op, e), flush=True)
        return {}


def beh(nazev, alink_on, plan):
    print("== %s" % nazev, flush=True)
    deska("set_power", idx=50)
    deska("set_alink", on=alink_on)
    time.sleep(25 if alink_on else 8)    # adaptivni spoj se rozbehne nahoru (start od MCS 1, 5 s na krok)
    run = {"nazev": nazev, "alink": alink_on, "kroky": []}
    for idx in KROKY:
        r = zkus("set_power", idx=idx)
        k = {"idx": r.get("idx", idx), "t0": time.time() * 1000, "m0": time.monotonic() * 1000}
        time.sleep(DRZET_S)
        st = zkus("status")
        al = st.get("alink") or {}
        k.update({"t1": time.time() * 1000, "m1": time.monotonic() * 1000, "mcs": (st.get("video") or {}).get("mcs"),
                  "kbps_nast": st.get("kbps"), "p": al.get("p"), "rep": al.get("rep")})
        run["kroky"].append(k)
        print("  vykon %2d: MCS %s, tok %s, %s" % (k["idx"], k["mcs"], k["kbps_nast"], al.get("rep")), flush=True)
    plan["behy"].append(run)


def main():
    os.makedirs(OUT, exist_ok=True)
    st0 = deska("status")
    al0 = bool((st0.get("alink") or {}).get("on"))
    pwr0 = st0.get("pwr") or 50
    plan = {"start": time.time() * 1000, "behy": [], "kroky": KROKY, "drzet_s": DRZET_S}
    pf = os.path.join(OUT, "alink-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        beh("adaptivni spoj VYP (pevne MCS 1)", False, plan)
        json.dump(plan, open(pf, "w"), indent=1)
        beh("adaptivni spoj ZAP", True, plan)
    finally:
        for _ in range(5):
            try:
                deska("set_power", idx=pwr0)
                break
            except Exception as e:  # noqa: BLE001
                print("POZOR: vykon se nevratil (%s), zkousim znovu" % e, flush=True)
                time.sleep(1)
        zkus("set_alink", on=al0)
        plan["konec"] = time.time() * 1000
        json.dump(plan, open(pf, "w"), indent=1)
        print("Plan: %s" % pf, flush=True)
    vyhodnot(pf)


def vyhodnot(pf):
    plan = json.load(open(pf))
    ev = []
    for ln in open(os.path.join(D, "udalosti.log")):
        p = ln.split()
        if len(p) >= 2:
            try:
                ev.append((float(p[0]), p[1], dict(x.split("=", 1) for x in p[2:] if "=" in x)))
            except ValueError:
                pass
    sn = []
    for ln in open(os.path.join(D, "snimky.log")):
        p = ln.split()
        try:
            sn.append(float(p[0]))
        except (ValueError, IndexError):
            pass
    wfb = []
    for ln in open(os.path.join(D, "gs-video.log"), errors="replace"):
        p = ln.rstrip("\n").split("\t")
        if len(p) >= 3 and p[1] == "PKT":
            try:
                v = [int(x) for x in p[2].split(":")]
                wfb.append((int(p[0]), v))
            except ValueError:
                pass
    out = []
    for run in plan["behy"]:
        print("\n%s" % run["nazev"])
        print(" vykon  MCS  tok   doruceno kbit/s  ztraty obrazu  rozbity obraz ms  zadrhy>=100ms  SNR")
        tot = {"ztraty": 0, "rozbito_ms": 0, "zadrhy": 0, "kbit": 0.0, "s": 0.0}
        for k in run["kroky"]:
            z = [e for e in ev if e[1] == "ZTRATA" and k["t0"] <= e[0] < k["t1"]]
            kf = [float(e[2]["po_ztrate_ms"]) for e in ev if e[1] == "KLICOVY" and "po_ztrate_ms" in e[2]
                  and k["t0"] <= e[0] < k["t1"] + 3000]
            t = [x for x in sn if k["t0"] <= x < k["t1"]]
            gaps = [b - a for a, b in zip(t, t[1:])] + ([k["t1"] - t[-1]] if t else [k["t1"] - k["t0"]])
            w = [v for m, v in wfb if k["m0"] <= m < k["m1"]]
            kb = sum(v[8] for v in w) * 8 / 1000 / max(0.1, (k["m1"] - k["m0"]) / 1000)
            rozb = sum(kf[:len(z)]) if z else 0
            zd = sum(1 for g in gaps if g >= 100)
            tot["ztraty"] += len(z)
            tot["rozbito_ms"] += rozb
            tot["zadrhy"] += zd
            tot["kbit"] += kb * (k["t1"] - k["t0"]) / 1000
            tot["s"] += (k["t1"] - k["t0"]) / 1000
            snr = (k.get("rep") or {}).get("snr")
            print("  %3s   %3s  %5s   %8.0f        %4d          %6.0f           %3d        %s"
                  % (k["idx"], k["mcs"], k["kbps_nast"], kb, len(z), rozb, zd, snr))
        tot["kbit_s"] = round(tot["kbit"] / max(1, tot["s"]))
        print(" celkem: ztraty obrazu %d, rozbity obraz %.1f s, zadrhy %d, prumerny tok %d kbit/s"
              % (tot["ztraty"], tot["rozbito_ms"] / 1000, tot["zadrhy"], tot["kbit_s"]))
        out.append({"nazev": run["nazev"], **tot})
    json.dump(out, open(pf.replace("alink-", "alink-vysledky-"), "w"), indent=1)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "vyhodnot":
        vyhodnot(sys.argv[2])
    else:
        main()
