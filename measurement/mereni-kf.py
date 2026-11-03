#!/usr/bin/python3
# Vima krok 3: mereni obnovy obrazu po ztrate paketu a trhani videa (klicove snimky).
# Bezi na laptopu, kdyz bezi tunel.sh i gs-video.sh (okno prijem.py). Deska musi byt i na kabelu:
#   - umela ztrata: ssh luckfox -> iptables na desce zahodi video pred wfb_tx (UDP 5602) na 250 ms
#   - nastaveni desky (GOP, postupne obnovovani, rozliseni, tok): vima-ctl.py pres kabel 10.42.0.2
#   - zadost o klicovy snimek zapina/vypina prijem.conf (prijem.py ji cte za behu)
# Vysledek: mereni-kf/plan-<cas>.json (casy variant) + nahledy z prijem.py -> analyza-kf.py
# Pouziti: python3 mereni-kf.py [rychle]
import json
import os
import random
import socket
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(D, "prijem.conf")
OUT = os.path.join(D, "mereni-kf")
DESKA = ("10.42.0.2", 5900)
CM = "/tmp/vima-kf-ssh-%r@%h"
SSH = ["ssh", "-o", "ControlMaster=auto", "-o", "ControlPath=" + CM, "-o", "ControlPersist=900", "luckfox"]
ZTRATA_MS = 250
RYCHLE = len(sys.argv) > 1 and sys.argv[1] == "rychle"

# (nazev, nastaveni desky, zadost o klicovy snimek, pocet ztrat, rozestup s)
VARIANTY = [
    ("A GOP 30, bez zadosti (puvodni stav)", {"gop": 30, "smooth": False}, 0, 10, (2.6, 3.6)),
    ("B GOP 30, se zadosti", {"gop": 30, "smooth": False}, 1, 10, (2.6, 3.6)),
    ("C GOP 150, bez zadosti", {"gop": 150, "smooth": False}, 0, 5, (5.5, 7.0)),
    ("D plynuly obraz (GOP 500), se zadosti", {"gop": None, "smooth": True}, 1, 10, (2.6, 3.6)),
]
# trhani bez ztrat: (nazev, rozliseni, tok, plynuly)
KLID = [
    ("720p, GOP 30", "1280x720", 2048, False),
    ("720p, plynuly", "1280x720", 2048, True),
    ("2304x1296 3072 kbit/s, GOP 30", "2304x1296", 3072, False),
    ("2304x1296 3072 kbit/s, plynuly", "2304x1296", 3072, True),
]
KLID_S = 20
if RYCHLE:
    VARIANTY = [(n, s, z, 3, r) for n, s, z, _, r in VARIANTY[1:4:2]]
    KLID = KLID[:2]
    KLID_S = 6

_id = [int(time.time()) & 0xffff]


def deska(op, **kw):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(4)
    _id[0] += 1
    req = dict(op=op, id=_id[0], **kw)
    try:
        for _ in range(3):
            s.sendto(json.dumps(req).encode(), DESKA)
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


def nastav_desku(res=None, kbps=None, gop=None, smooth=None):
    st = deska("status")
    if res and st.get("res") != res.replace("x", "*"):
        deska("set_resolution", res=res)
    if kbps and st.get("kbps") != kbps:
        deska("set_bitrate", kbps=kbps)
    if smooth is not None and (st.get("smooth") or {}).get("on") != smooth:
        deska("set_smooth", on=smooth)
    if gop and not smooth and deska("status").get("gop") != gop:
        deska("set_gop", gop=gop)
    deska("keyframe")   # cisty start varianty


def cekej_gop(want, limit=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        if deska("status").get("gop") == want:
            return round((time.monotonic() - t0) * 1000)
        time.sleep(0.1)
    return None


def prijem_conf(zadost, mereni):
    with open(CONF + ".tmp", "w") as f:
        f.write("# Vima prijem.py - nastaveni (cte se za behu, zmena do 1 s)\n"
                "# ZADOST_KF=1  pri ztrate paketu pozadat desku o klicovy snimek (0 = nezadat, cekat na pravidelny)\n"
                "ZADOST_KF=%d\n"
                "# MERENI=1  ukladat zmensene snimky do mereni-kf/ (projevi se pri dalsim otevreni okna)\n"
                "MERENI=%d\n" % (zadost, mereni))
    os.replace(CONF + ".tmp", CONF)


def restart_okna():
    subprocess.run(["pkill", "-HUP", "-f", "[p]ython3 -I /home/mikes/vima-board/prijem.py"])
    time.sleep(4)


def ztrata():
    t = time.time() * 1000
    subprocess.run(SSH + ["iptables -I INPUT -p udp --dport 5602 -j DROP; usleep %d; "
                          "iptables -D INPUT -p udp --dport 5602 -j DROP" % (ZTRATA_MS * 1000)], check=True)
    return t


def main():
    if subprocess.run(["pgrep", "-f", "[p]ython3 -I /home/mikes/vima-board/prijem.py"], capture_output=True).returncode:
        sys.exit("Nebezi okno s videem (gs-video.sh) - nejdriv ho spust.")
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(SSH + ["true"], check=True)
    plan = {"start": time.time() * 1000, "ztrata_ms": ZTRATA_MS, "varianty": [], "klid": []}
    pfile = os.path.join(OUT, "plan-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    puvodni = deska("status")
    print("Deska: %s, %s kbit/s, GOP %s, plynuly %s" % (puvodni.get("res"), puvodni.get("kbps"), puvodni.get("gop"), puvodni.get("smooth")), flush=True)
    try:
        prijem_conf(1, 1)
        nastav_desku(res="1280x720", kbps=2048, gop=30, smooth=False)
        restart_okna()
        for name, nast, zad, n, (a, b) in VARIANTY:
            print("== %s" % name, flush=True)
            prijem_conf(zad, 1)
            nastav_desku(gop=nast["gop"], smooth=nast["smooth"])
            time.sleep(3)
            v = {"nazev": name, "zadost": zad, **nast, "t0": time.time() * 1000, "ztraty": []}
            for i in range(n):
                time.sleep(random.uniform(a, b))
                v["ztraty"].append(ztrata())
                print("  ztrata %d/%d" % (i + 1, n), flush=True)
            time.sleep(b)
            v["t1"] = time.time() * 1000
            plan["varianty"].append(v)
            json.dump(plan, open(pfile, "w"), indent=1)
        prijem_conf(1, 1)
        for name, res, kbps, sm in KLID:
            print("== klid: %s" % name, flush=True)
            nastav_desku(res=res, kbps=kbps, gop=30, smooth=sm)
            time.sleep(3)
            k = {"nazev": name, "res": res, "kbps": kbps, "plynuly": sm, "gop": deska("status").get("gop"),
                 "t0": time.time() * 1000}
            time.sleep(KLID_S)
            k["t1"] = time.time() * 1000
            plan["klid"].append(k)
            json.dump(plan, open(pfile, "w"), indent=1)
        print("== pojistka: prijimac prestane posilat rx_alive", flush=True)
        nastav_desku(res="1280x720", kbps=2048, smooth=True)
        time.sleep(2)
        poj = {"gop_pred": deska("status").get("gop")}
        prijem_conf(0, 1)
        poj["na_30_ms"] = cekej_gop(30)
        prijem_conf(1, 1)
        poj["zpet_500_ms"] = cekej_gop(500)
        plan["pojistka"] = poj
        print("  %s" % poj, flush=True)
        json.dump(plan, open(pfile, "w"), indent=1)
    finally:
        print("Vracim desku a okno do puvodniho stavu...", flush=True)
        try:
            sm = bool((puvodni.get("smooth") or {}).get("on"))
            nastav_desku(res=(puvodni.get("res") or "1280*720").replace("*", "x"), kbps=puvodni.get("kbps") or 2048,
                         gop=None if sm else (puvodni.get("gop") or 30), smooth=sm)
        except Exception as e:  # noqa: BLE001
            print("POZOR: desku se nepodarilo vratit: %s" % e, flush=True)
        subprocess.run(SSH + ["iptables -D INPUT -p udp --dport 5602 -j DROP 2>/dev/null; true"])
        prijem_conf(1, 0)
        restart_okna()
        plan["konec"] = time.time() * 1000
        json.dump(plan, open(pfile, "w"), indent=1)
        print("Plan: %s" % pfile, flush=True)


if __name__ == "__main__":
    main()
