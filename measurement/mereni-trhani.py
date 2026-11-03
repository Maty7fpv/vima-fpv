#!/usr/bin/python3
# Vima: mereni zadrhavani obrazu bez ztrat. Pro kazde nastaveni 30 s zaznamu z okna s videem
# (prijem.py, MERENI=1): kdy snimek vznikl na desce (RTP cas), kdy dorazil a kdy se dekodoval.
# Bezi kdyz bezi tunel.sh a gs-video.sh; deska i na kabelu (nastaveni pres 10.42.0.2).
# Vysledek: mereni-kf/trhani-<cas>.json -> analyza-trhani.py
# Pouziti: python3 mereni-trhani.py
import json
import os
import socket
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(D, "prijem.conf")
OUT = os.path.join(D, "mereni-kf")
DESKA = ("10.42.0.2", 5900)
OKNO_S = 30

# (nazev, rozliseni, tok, fps, plynuly, stary zpusob fps = snimac zustane na 30)
NASTAVENI = [
    ("2304x1296 25 fps, plynuly, fps postaru (snimac 30)", "2304x1296", 3072, 25, True, True),
    ("2304x1296 25 fps, plynuly", "2304x1296", 3072, 25, True, False),
    ("2304x1296 25 fps, GOP 25", "2304x1296", 3072, 25, False, False),
    ("1280x720 30 fps, plynuly", "1280x720", 2048, 30, True, False),
    ("1280x720 30 fps, GOP 30", "1280x720", 2048, 30, False, False),
]
_id = [int(time.time()) & 0xffff]


def deska(op, **kw):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    _id[0] += 1
    try:
        for _ in range(3):
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


def rk_stary_fps(fps):
    """Puvodni chovani: snimac na 30 fps, rkipc snimky zahazuje (jen pro srovnani)."""
    subprocess.run(["ssh", "luckfox", "python3 - <<'EOF'\n"
                    "import importlib.util\n"
                    "sp = importlib.util.spec_from_file_location('v', '/usr/bin/vima-ctl.py'); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)\n"
                    "m.rk_set_int('rk_isp_set_frame_rate', 30); m.rk_set_str('rk_video_set_frame_rate', '%d')\n"
                    "EOF" % fps], check=True)


def nastav(res, kbps, fps, sm):
    st = deska("status")
    if st.get("res") != res.replace("x", "*"):
        deska("set_resolution", res=res)
    if st.get("kbps") != kbps:
        deska("set_bitrate", kbps=kbps)
    if (st.get("smooth") or {}).get("on") != sm:
        deska("set_smooth", on=sm)
    deska("set_fps", fps=fps)   # vzdy: srovna i snimac
    if not sm and deska("status").get("gop") != fps:
        deska("set_gop", gop=fps)


def main():
    if subprocess.run(["pgrep", "-f", "[p]ython3 -I /home/mikes/vima-board/prijem.py"], capture_output=True).returncode:
        sys.exit("Nebezi okno s videem (gs-video.sh) - nejdriv ho spust.")
    puvodni = deska("status")
    pc = open(CONF).read()
    plan = {"start": time.time() * 1000, "okna": []}
    pfile = os.path.join(OUT, "trhani-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        prijem_conf(1, 1)
        restart_okna()
        for name, res, kbps, fps, sm, stary in NASTAVENI:
            print("== %s" % name, flush=True)
            nastav(res, kbps, fps, sm)
            if stary:
                rk_stary_fps(fps)
            time.sleep(4)
            st = deska("status")
            w = {"nazev": name, "fps": fps, "gop": st.get("gop"), "sensor_fps": st.get("sensor_fps"),
                 "t0": time.time() * 1000}
            time.sleep(OKNO_S)
            w["t1"] = time.time() * 1000
            plan["okna"].append(w)
            print("   GOP %s, snimac %s fps" % (w["gop"], w["sensor_fps"]), flush=True)
            json.dump(plan, open(pfile, "w"), indent=1)
    finally:
        print("Vracim nastaveni...", flush=True)
        try:
            sm = bool((puvodni.get("smooth") or {}).get("on"))
            nastav((puvodni.get("res") or "1280*720").replace("*", "x"), puvodni.get("kbps") or 2048,
                   int(puvodni.get("fps") or 30), sm)
        except Exception as e:  # noqa: BLE001
            print("POZOR: desku se nepodarilo vratit: %s" % e, flush=True)
        with open(CONF + ".tmp", "w") as f:
            f.write(pc.replace("MERENI=1", "MERENI=0"))
        os.replace(CONF + ".tmp", CONF)
        restart_okna()
        plan["konec"] = time.time() * 1000
        json.dump(plan, open(pfile, "w"), indent=1)
        print("Plan: %s" % pfile, flush=True)


if __name__ == "__main__":
    main()
