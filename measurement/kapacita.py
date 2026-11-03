#!/usr/bin/python3
# Vima krok 4: mereni kapacity spoje (kolik dat unese wfb-ng pri jednotlivych MCS).
# Bezi kdyz bezi tunel.sh a gs-video.sh a deska je i na kabelu. Obraz po dobu mereni zamrzne:
# okno s videem prejde do PAUZA (prijem.conf) a jen zapisuje testovaci pakety, deska misto kamery
# posila testovaci data (kapacita-deska.py). Vysledek: mereni-kf/kapacita-plan-*.json + kapacita-*.log
# Pouziti: python3 kapacita.py [rychle]
import json
import os
import re
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(D, "prijem.conf")
OUT = os.path.join(D, "mereni-kf")
PHY_HT20 = [6.5, 13, 19.5, 26, 39, 52, 58.5, 65]          # Mbit/s, 1 proud, dlouhy GI
PODILY = [0.2, 0.35, 0.5, 0.65, 0.8, 0.95]                # z PHY/2 (FEC 8/16 = dvojnasobek dat ve vzduchu)


def conf_set(key, val):
    s = open(CONF).read()
    if re.search(r"(?m)^%s=" % key, s):
        s = re.sub(r"(?m)^%s=.*$" % key, "%s=%s" % (key, val), s)
    else:
        s = s.rstrip("\n") + "\n%s=%s\n" % (key, val)
    open(CONF + ".tmp", "w").write(s)
    os.replace(CONF + ".tmp", CONF)


def deska(op, **kw):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(4)
    rid = int(time.time() * 1000) & 0x7fffffff
    try:
        for _ in range(3):
            s.sendto(json.dumps(dict(op=op, id=rid, **kw)).encode(), ("10.42.0.2", 5900))
            try:
                r = json.loads(s.recv(65535).decode())
            except socket.timeout:
                continue
            if r.get("id") == rid:
                if not r.get("ok"):
                    raise RuntimeError("%s: %s" % (op, r.get("err")))
                return r["res"]
        raise RuntimeError("%s: deska neodpovida" % op)
    finally:
        s.close()


def main():
    if subprocess.run(["pgrep", "-f", "[p]ython3 -I /home/mikes/vima-board/prijem.py"], capture_output=True).returncode:
        sys.exit("Nebezi okno s videem (gs-video.sh).")
    rychle = len(sys.argv) > 1 and sys.argv[1] == "rychle"
    mcs_list = [1] if rychle else list(range(8))
    podily = [0.2, 0.5] if rychle else PODILY
    kroky = [[m, int(PHY_HT20[m] / 2 * p * 1000)] for m in mcs_list for p in podily]
    plan = {"kroky": kroky, "krok_s": 2 if rychle else 3, "velikost": 1400}
    os.makedirs(OUT, exist_ok=True)
    pf = os.path.join(OUT, "kapacita-plan-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    res = {"plan": plan, "kroky": [], "start": time.time() * 1000}
    subprocess.run(["scp", "-q", os.path.join(D, "kapacita-deska.py"), "luckfox:/tmp/kapacita-deska.py"], check=True)
    alink_byl = False
    try:   # adaptivni spoj by behem mereni prepisoval MCS -> vypnout a pak vratit
        alink_byl = bool((deska("status").get("alink") or {}).get("on"))
        if alink_byl:
            deska("set_alink", on=False)
    except Exception as e:  # noqa: BLE001
        sys.exit("Deska neodpovida pres kabel: %s" % e)
    conf_set("PAUZA", "1")
    try:
        time.sleep(2)
        p = subprocess.Popen(["ssh", "luckfox", "python3 /tmp/kapacita-deska.py '%s'" % json.dumps(plan)],
                             stdout=subprocess.PIPE, text=True)
        for ln in p.stdout:
            try:
                d = json.loads(ln)
            except ValueError:
                print(ln.rstrip(), flush=True)
                continue
            if "mcs" in d:
                res["kroky"].append(d)
                print("MCS %d %6d kbit/s: vyslano %d, wfb_tx CPU %s %% (celkem %s %%), zahozeno %s, latence vys. %s/%s us"
                      % (d["mcs"], d["kbps"], d["seq1"] - d["seq0"], d["cpu_wfb_tx"], d["cpu_celkem"],
                         d["dropped"], d["lat_avg_us"], d["lat_max_us"]), flush=True)
            else:
                res.setdefault("deska", []).append(d)
                print(d, flush=True)
            json.dump(res, open(pf, "w"), indent=1)
        p.wait()
    finally:
        time.sleep(1)
        conf_set("PAUZA", "0")
        if alink_byl:
            try:
                deska("set_alink", on=True)
            except Exception as e:  # noqa: BLE001
                print("POZOR: adaptivni spoj se nezapnul zpet: %s" % e, flush=True)
        res["konec"] = time.time() * 1000
        json.dump(res, open(pf, "w"), indent=1)
        print("Plan: %s" % pf, flush=True)


if __name__ == "__main__":
    main()
