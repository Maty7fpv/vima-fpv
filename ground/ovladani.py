#!/usr/bin/python3
# Vima: ovladani desky ze zeme pres IP tunel (kroky 2 a 3).
#
#   ~/vima-board/ovladani.py stav
#   ~/vima-board/ovladani.py tok 1024            datovy tok videa (kbit/s)
#   ~/vima-board/ovladani.py fps 25              snimky za sekundu (GOP = fps -> klicovy snimek 1x za s)
#   ~/vima-board/ovladani.py gop 30              interval klicovych snimku
#   ~/vima-board/ovladani.py rozliseni 960x540
#   ~/vima-board/ovladani.py obraz 1152x648@60   rozliseni + fps; 60 fps (jen do 1152x648) i navrat na vetsi
#                                                rozliseni prepne rezim snimace = restart desky (~1 min bez obrazu)
#   ~/vima-board/ovladani.py vykon nizky|stredni|plny|<index>   vykon desky (video)
#   ~/vima-board/ovladani.py kanal 149           deska i laptop zaroven, pri neuspechu navrat
#   ~/vima-board/ovladani.py pasmo 2.4|5.8       na naposledy pouzity kanal v pasmu (vychozi 13 / 149)
#   ~/vima-board/ovladani.py najdi               laptop projde kanaly a najde desku (kdyby se rozesly)
#   ~/vima-board/ovladani.py klicovy             deska hned posle klicovy snimek
#   ~/vima-board/ovladani.py plynule zap|vyp     plynuly obraz: dlouhy GOP, klicovy snimek jen na zadost
#   ~/vima-board/ovladani.py zadosti zap|vyp     okno s videem zada o klicovy snimek pri ztrate (prijem.conf)
#   ~/vima-board/ovladani.py adaptivni zap|vyp   deska meni MCS a tok podle kvality prijmu (krok 4)
#   ~/vima-board/ovladani.py okno                okno s tlacitky
# Volba --kabel: k desce po ethernetu (10.42.0.2) misto tunelu.
#
# Deska: vima-ctl.py, UDP 5900 (dotaz -> odpoved, zacina vzdy laptop kvuli firewallu).
# Laptop: zmeny karty (kanal, vykon) dela root pomocnik "ovladani.py pomocnik", ktery spousti tunel.sh.
import json
import os
import random
import re
import socket
import struct
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
KONF = os.path.join(D, "kanal.conf")
SNIMKY = os.path.join(D, "snimky.log")
VIDEOLOG = os.path.join(D, "gs-video.log")
UDALOSTI = os.path.join(D, "udalosti.log")
OVLADANI_LOG = os.path.join(D, "ovladani.log")   # kazdy prikaz panelu/CLI a jeho vysledek
PRIJEM_CONF = os.path.join(D, "prijem.conf")
SOCK = "/run/user/%d/vima-pomocnik.sock" % int(os.environ.get("SUDO_UID", os.getuid()))
BOARD = ("10.5.0.2", 5900)
IF = "wfb0"
CH_2G = list(range(1, 14))
CH_5G = [149, 153, 157, 161, 165]
CH_ALLOWED = CH_2G + CH_5G
PASMO_VYCHOZI = {"2G": 13, "5G": 149}   # kanal.conf CH_2G_POSLEDNI / CH_5G_POSLEDNI
RESOLUTIONS = ["640x360", "960x540", "1152x648", "1280x720", "1920x1080", "2304x1296"]
FPS = ["15", "20", "25", "30", "55", "60"]   # 55 = nejnizsi zpozdeni (rkipc zapne wrap), 60 = bez wrapu
REZIM60_MAX = (1152, 648)   # rezim snimace 60 fps: obraz nejvys 1152x648 (sc3336-60fps)


def zapis_log(text):
    """Radek do ovladani.log (max ~1 MB, pak se zacne znovu)."""
    try:
        if os.path.exists(OVLADANI_LOG) and os.path.getsize(OVLADANI_LOG) > 1000000:
            os.replace(OVLADANI_LOG, OVLADANI_LOG + ".1")
        with open(OVLADANI_LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def lze(res, fps):
    """Jde obraz res pri fps vubec? Nad 30 fps jen v rezimu snimace 60 a ten da nejvys 1152x648."""
    w, h = (int(x) for x in str(res).replace("*", "x").split("x"))
    return int(fps) <= 30 or (w <= REZIM60_MAX[0] and h <= REZIM60_MAX[1])


def rezim_pro(res, fps, cur):
    """Rezim snimace (30/60) pro obraz; prednost ma bezici rezim cur."""
    w, h = (int(x) for x in str(res).replace("*", "x").split("x"))
    if int(fps) > 30:
        return 60
    if w > REZIM60_MAX[0] or h > REZIM60_MAX[1]:
        return 30
    return cur


def wrap_restart(rz, fps, st):
    """Wrap (nizsi zpozdeni) jde zapnout/vypnout jen restartem desky (rozhoduje rkipc pri startu).
    Bezi-li, fps nad wrap_max by kodér pulil; nebezi-li a je povolen, 55 fps ho zapne restartem."""
    m = (st.get("rezimy") or {}).get(str(rz)) or []
    if len(m) < 5:   # stara vima-ctl bez wrapu
        return False
    wrap_max, wrap_fps = m[3], m[4]
    if st.get("wrap"):
        return int(fps) > wrap_max
    return bool(st.get("wrap_en")) and wrap_fps is not None and int(fps) == wrap_fps


def restart_potreba(res, fps, st):
    """Restartuje volba desku? (jiny rezim snimace, nebo zapnuti/vypnuti wrapu)"""
    cur = st.get("rezim", 30)
    rz = rezim_pro(res, fps, cur or 30)
    return rz != cur or wrap_restart(rz, fps, st)


# ---------------- kanal.conf ----------------
def konf():
    c = {}
    try:
        for line in open(KONF):
            m = re.match(r"\s*([A-Z0-9_]+)=([^#\s]*)", line)
            if m:
                c[m.group(1)] = m.group(2)
    except OSError:
        pass
    return c


def konf_set(key, value):
    """Prepise jen radek KEY=, ostatni radky (vykony laptopu) nechá."""
    lines = open(KONF).read().splitlines(True) if os.path.exists(KONF) else []
    out, done = [], False
    for line in lines:
        if re.match(r"\s*%s=" % key, line):
            out.append("%s=%s\n" % (key, value))
            done = True
        else:
            out.append(line)
    if not done:
        out.append("%s=%s\n" % (key, value))
    tmp = KONF + ".tmp"
    with open(tmp, "w") as f:
        f.write("".join(out))
    os.replace(tmp, KONF)


LAPTOP_LEGAL_2G, LAPTOP_LEGAL_5G = 38, 8   # kalibrace 25. 10.: laptop o <=6 dB silnejsi nez deska pri stejnem indexu


def laptop_cap(ch):
    """Index laptopu pro pasmo: kanal.conf, ale vzdy 1..pevny strop (38 / 8)."""
    c = konf()
    legal = LAPTOP_LEGAL_2G if ch <= 14 else LAPTOP_LEGAL_5G
    try:
        v = int(c.get("LAPTOP_TXPWR_IDX_2G" if ch <= 14 else "LAPTOP_TXPWR_IDX_5G", legal))
    except ValueError:
        v = legal
    return max(1, min(v, legal))


def iw_info():
    out = subprocess.run(["iw", "dev", IF, "info"], capture_output=True, text=True, timeout=3).stdout
    m = re.search(r"channel (\d+) \((\d+) MHz\)", out)
    p = re.search(r"txpower (-?[\d.]+) dBm", out)
    return (int(m.group(1)) if m else None), (int(round(-float(p.group(1)))) if p else None)


# ---------------- root pomocnik (bezi pod sudo z tunel.sh) ----------------
def pomocnik_server():
    if os.geteuid() != 0:
        sys.exit("pomocnik musi bezet jako root (spousti ho tunel.sh)")
    uid = int(os.environ.get("SUDO_UID", "0"))
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chown(SOCK, uid, -1)
    os.chmod(SOCK, 0o600)
    srv.listen(4)
    print("pomocnik: posloucham na %s (uid %d)" % (SOCK, uid), flush=True)

    import threading
    lock = threading.Lock()
    pending = {}   # pojistka: {"tok", "prev", "deadline"} - bez potvrzeni se laptop sam vrati

    def iw(*args):
        subprocess.run(["iw", "dev", IF] + list(args), check=True, timeout=10)

    def vykon(idx):
        if not 1 <= idx <= LAPTOP_LEGAL_2G:
            raise ValueError("index vykonu %s mimo 1-%d (0 = tovarni neomezeny vykon)" % (idx, LAPTOP_LEGAL_2G))
        iw("set", "txpower", "fixed", "-%d00" % idx)

    def jedna_karta():
        n = 0
        for d in os.listdir("/sys/class/net"):
            if os.path.basename(os.path.realpath("/sys/class/net/%s/device/driver" % d)) == "rtl88xxau_wfb":
                n += 1
        if n != 1:
            raise RuntimeError("vykon ovladace je spolecny pro vsechny karty - zapojena musi byt jen jedna (je %d)" % n)

    def prepni(to):
        """Nejdriv nizsi vykon (obe pasma, aktualni index), pak kanal, cilovy vykon az po overeni kanalu."""
        jedna_karta()
        ch, idx = iw_info()
        lo = min([laptop_cap(to), laptop_cap(ch) if ch else LAPTOP_LEGAL_5G] + ([idx] if idx and idx >= 1 else []))
        vykon(lo)
        iw("set", "channel", str(to), "HT20")
        ch2, _ = iw_info()
        if ch2 != to:
            raise RuntimeError("karta hlasi kanal %s misto %s (vykon zustava %d)" % (ch2, to, lo))
        vykon(laptop_cap(to))
        return iw_info()

    def hlidac():
        while True:
            time.sleep(0.2)
            with lock:
                if pending and time.monotonic() > pending["deadline"]:
                    try:
                        prepni(pending["prev"])
                        print("pomocnik: POJISTKA - bez potvrzeni zpet na kanal %d" % pending["prev"], flush=True)
                    except Exception as e:  # noqa: BLE001
                        print("pomocnik: CHYBA pojistky: %s" % e, flush=True)
                    pending.clear()
    threading.Thread(target=hlidac, daemon=True).start()

    while True:
        conn, _ = srv.accept()
        try:
            cred = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _, peer_uid, _ = struct.unpack("3i", cred)
            if peer_uid not in (uid, 0):
                raise PermissionError("cizi uzivatel %d" % peer_uid)
            req = json.loads(conn.makefile().readline())
            with lock:
                ch, idx = iw_info()
                t0 = time.monotonic()
                if req["op"] == "kanal":
                    to = int(req["ch"])
                    if to not in CH_ALLOWED:
                        raise ValueError("kanal %d neni povoleny" % to)
                    pending.clear()
                    ch2, idx2 = prepni(to)
                    if req.get("navrat_s") and ch and ch != to:
                        pending.update(tok=req.get("tok"), prev=ch,
                                       deadline=time.monotonic() + min(float(req["navrat_s"]), 30.0))
                    res = {"ch": ch2, "idx": idx2, "ms": round((time.monotonic() - t0) * 1000)}
                elif req["op"] == "potvrdit":
                    if pending and pending.get("tok") == req.get("tok"):
                        pending.clear()
                    res = {"ch": ch}
                elif req["op"] == "vykon":
                    i = int(req["idx"])
                    if not 1 <= i <= laptop_cap(ch):
                        raise ValueError("index %d mimo 1-%d" % (i, laptop_cap(ch)))
                    jedna_karta()
                    vykon(i)
                    res = {"ch": ch, "idx": iw_info()[1]}
                elif req["op"] == "stav":
                    res = {"ch": ch, "idx": idx, "pojistka": bool(pending)}
                else:
                    raise ValueError("neznamy prikaz")
            print("pomocnik: %s -> %s" % (req, res), flush=True)
            conn.sendall((json.dumps({"ok": True, "res": res}) + "\n").encode())
        except Exception as e:  # noqa: BLE001
            print("pomocnik: chyba %s" % e, flush=True)
            try:
                conn.sendall((json.dumps({"ok": False, "err": str(e)}) + "\n").encode())
            except OSError:
                pass
        finally:
            conn.close()


def pomocnik(op, **kw):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(15)
    try:
        s.connect(SOCK)
    except OSError:
        raise RuntimeError("pomocnik nebezi - spust ~/vima-board/tunel.sh")
    try:
        s.sendall((json.dumps(dict(op=op, **kw)) + "\n").encode())
        r = json.loads(s.makefile().readline())
    finally:
        s.close()
    if not r.get("ok"):
        raise RuntimeError("laptop: " + r.get("err", "?"))
    return r["res"]


# ---------------- deska (UDP 5900) ----------------
TUNEL = ("10.5.0.2", 5900)


def deska(op, timeout=1.0, tries=3, cil=None, **kw):
    """Dotaz na desku; opakovani se stejnym id (deska ho neprovede dvakrat). Vraci res, chyba -> vyjimka."""
    rid = random.getrandbits(31)
    msg = json.dumps(dict(op=op, id=rid, **kw)).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        for _ in range(tries):
            s.sendto(msg, cil or BOARD)
            try:
                while True:
                    data, _ = s.recvfrom(4096)
                    r = json.loads(data.decode())
                    if r.get("id") == rid:
                        if op != "status":
                            zapis_log("  deska %s %s -> %s" % (op, json.dumps(kw), json.dumps(r.get("res") if r.get("ok") else r.get("err"))))
                        if not r.get("ok"):
                            raise RuntimeError("deska: " + r.get("err", "?"))
                        return r["res"]
            except socket.timeout:
                continue
    finally:
        s.close()
    if op != "status":
        zapis_log("  deska %s %s -> neodpovida (%d x %.1f s)" % (op, json.dumps(kw), tries, timeout))
    raise TimeoutError("deska neodpovida (%s)" % op)


# ---------------- mereni vypadku obrazu (snimky.log z prijem.py) ----------------
def obraz_mezera(t0_ms, t1_ms):
    """Nejdelsi mezera mezi dekodovanymi snimky v okne [t0, t1] (ms), None kdyz prijem.py nebezi."""
    try:
        with open(SNIMKY) as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400000))
            ts = []
            for line in f:
                p = line.split()
                if len(p) == 3:
                    try:
                        ts.append(float(p[0]))
                    except ValueError:
                        pass
    except OSError:
        return None
    pred = [t for t in ts if t <= t0_ms]
    if not pred or t0_ms - pred[-1] > 2000:   # prijem.py nebezi (snimky.log muze byt stary i dny)
        return None
    w = [pred[-1]] + [t for t in ts if t0_ms < t <= t1_ms] + [t1_ms]   # i mezera do konce okna (obraz nenabehl)
    return round(max(b - a for a, b in zip(w, w[1:])))


def s_merenim(fn, wait=3.0):
    """Provede zmenu a zmeri nejdelsi vypadek obrazu na laptopu."""
    t0 = time.time() * 1000
    res = fn()
    time.sleep(wait)
    res["obraz_mezera_ms"] = obraz_mezera(t0, time.time() * 1000)
    return res


# ---------------- prikazy ----------------
def prikaz_stav():
    t0 = time.monotonic()
    st = deska("status")
    st["rtt_ms"] = round((time.monotonic() - t0) * 1000)
    st["laptop_ch"], st["laptop_pwr"] = iw_info()
    st.update(prijem())
    return st


def prijem():
    """Kvalita prijmu videa za posledni ~5 s z gs-video.log (wfb_rx)."""
    r = {}
    try:
        with open(VIDEOLOG, errors="replace") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 20000))
            lines = f.read().splitlines()[1:]
    except OSError:
        return r
    pkt = [ln.split("\t") for ln in lines if "\tPKT\t" in ln]
    ant = [ln.split("\t") for ln in lines if "\tRX_ANT\t" in ln][-10:]
    if pkt:   # poslednich ~5 s podle casu wfb_rx (interval -l 200 nebo 1000 ms)
        t_end = int(pkt[-1][0])
        pkt = [p for p in pkt if t_end - int(p[0]) < 5000]
        v = [list(map(int, p[2].split(":"))) for p in pkt]
        dur = max(1.0, (t_end - int(pkt[0][0])) / 1000.0 + (0.2 if len(pkt) > 6 else 1.0))
        allp = sum(x[0] for x in v) or 1
        r["ztraty"] = sum(x[5] for x in v)
        r["fec_pct"] = round(100.0 * sum(x[4] for x in v) / allp, 1)
        r["kbps_real"] = round(sum(x[8] for x in v) * 8 / 1000 / dur)
    if ant:
        rs = [int(a[4].split(":")[2]) for a in ant if len(a) > 4]
        if rs:
            r["rssi"] = max(rs)
    r.update(obnovy())
    return r


def obnovy(okno_s=60):
    """Ztraty obrazu za posledni minutu a jak rychle prisel klicovy snimek (udalosti.log z prijem.py)."""
    r = {"zadosti": prijem_conf().get("ZADOST_KF", "1") == "1"}
    try:
        with open(UDALOSTI, errors="replace") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 30000))
            lines = f.read().splitlines()[1:]
    except OSError:
        return r
    od = time.time() * 1000 - okno_s * 1000
    n, ms, po_ztrate = 0, [], False
    for ln in lines:
        p = ln.split()
        try:
            if len(p) < 2 or float(p[0]) < od:
                continue
        except ValueError:
            continue
        if p[1] == "ZTRATA":
            n += 1
            po_ztrate = True
        elif p[1] == "START":
            po_ztrate = False   # klicovy snimek po otevreni okna neni obnova po ztrate
        elif p[1] == "KLICOVY" and po_ztrate and len(p) > 2 and p[2].startswith("po_ztrate_ms="):
            ms.append(float(p[2].split("=")[1]))
            po_ztrate = False
    r["ztraty_obrazu"] = n
    if ms:
        r["obnova_ms"] = round(sum(ms) / len(ms))
    return r


def prijem_conf():
    c = {}
    try:
        for ln in open(PRIJEM_CONF):
            ln = ln.split("#", 1)[0].strip()
            if "=" in ln:
                k, v = ln.split("=", 1)
                c[k.strip()] = v.strip()
    except OSError:
        pass
    return c


def prijem_conf_set(key, value):
    """Prepise jeden radek v prijem.conf (prijem.py ho cte za behu)."""
    try:
        lines = open(PRIJEM_CONF).read().splitlines(True)
    except OSError:
        lines = []
    out, done = [], False
    for ln in lines:
        if re.match(r"\s*%s=" % re.escape(key), ln):
            out.append("%s=%s\n" % (key, value))
            done = True
        else:
            out.append(ln)
    if not done:
        out.append("%s=%s\n" % (key, value))
    with open(PRIJEM_CONF + ".tmp", "w") as f:
        f.write("".join(out))
    os.replace(PRIJEM_CONF + ".tmp", PRIJEM_CONF)


def vykon_desky(arg, st=None):
    st = st or deska("status")
    mx = st["pwr_max"]
    lv = {"nizky": max(1, round(mx * 0.5)), "stredni": max(1, round(mx * 0.75)), "plny": mx}
    idx = lv[arg] if arg in lv else int(arg)
    return deska("set_power", idx=idx)


class Neuspech(Exception):
    """Prepnuti se nepovedlo, ale stav obou koncu je znamy (uz osetreno)."""


def najdi_desku(kanaly, zprava=print, kola=3, dwell=2.5):
    """Hleda desku stridanim kanalu laptopu (vzduchem); vrati kanal, kde odpovida, laptop tam zustane."""
    for _ in range(kola):
        for ch in kanaly:
            try:
                if pomocnik("stav")["ch"] != ch:
                    pomocnik("kanal", ch=ch)
            except Exception as e:  # noqa: BLE001
                zprava("laptop: %s" % e)
                continue
            end = time.monotonic() + dwell
            while time.monotonic() < end:
                try:
                    st = deska("status", timeout=0.4, tries=1, cil=TUNEL)
                    if st.get("ch") == ch and not st.get("switch"):
                        return ch
                except Exception:  # noqa: BLE001
                    time.sleep(0.1)
    return None


def prepnout_kanal(to, zprava=print):
    """Dvoufazove prepnuti: deska i laptop za 1,5 s, potvrzeni vzduchem na novem kanalu, jinak oba zpet.
    Kdyz neni jasne, kde deska je (ztracena odpoved), laptop ji najde stridanim kanalu."""
    to = int(to)
    if to not in CH_ALLOWED:
        raise ValueError("kanal %d neni povoleny (%s)" % (to, CH_ALLOWED))
    pom = pomocnik("stav")
    if pom.get("pojistka"):
        raise RuntimeError("pomocnik jeste ceka na predchozi prepnuti, zkus to za 10 s")
    st = deska("status")
    if st.get("switch"):
        raise RuntimeError("deska prave prepina kanal (%s), zkus to za 10 s" % st["switch"])
    frm = st["ch"]
    if pom["ch"] != frm:
        raise RuntimeError("laptop je na kanalu %s, deska na %s - pouzij 'ovladani.py najdi'" % (pom["ch"], frm))
    if to == frm:
        return {"ch": to, "beze_zmeny": True}
    tok = "%08x" % random.getrandbits(32)
    t_obraz = time.time() * 1000
    # 1) priprava: deska potvrdi a prepne za in_ms od prvni kopie dotazu
    t_req = time.monotonic()
    try:
        ack = deska("ch_prepare", timeout=0.25, tries=4, cil=TUNEL, tok=tok, to=to, **{"from": frm},
                    in_ms=1500, confirm_ms=4000, commit_ms=3000)
    except Exception:
        for _ in range(5):
            try:
                deska("ch_abort", timeout=0.2, tries=1, cil=TUNEL, tok=tok)
                break
            except Exception:  # noqa: BLE001
                pass
        raise
    t_ack = time.monotonic()
    t_switch = t_ack + ack["in_ms"] / 1000.0 - min((t_ack - t_req) / 2, 0.1)
    zprava("Deska pripravena, prepnuti na kanal %d za %.1f s" % (to, t_switch - time.monotonic()))
    laptop_prepnut = False
    try:
        time.sleep(max(0, t_switch - time.monotonic()))
        # 2) laptop prepne; pojistka v pomocnikovi ho vrati sam, kdyby tento program skoncil pred potvrzenim
        r = pomocnik("kanal", ch=to, tok=tok, navrat_s=9.0)
        laptop_prepnut = True
        zprava("Laptop na kanalu %d (%d ms), overuji spojeni vzduchem..." % (to, r["ms"]))
        # 3) potvrzeni na novem kanalu (laptop ceka 3 s, deska 4 s)
        conf = None
        end = time.monotonic() + 3.0
        while time.monotonic() < end and not conf:
            try:
                conf = deska("ch_confirm", timeout=0.25, tries=1, cil=TUNEL, tok=tok)
            except Exception:  # noqa: BLE001  (timeout nebo deska jeste neprepnula)
                time.sleep(0.05)
        if not conf:
            zprava("Spojeni na kanalu %d se neobnovilo, vracim laptop na %d" % (to, frm))
            pomocnik("kanal", ch=frm)
            found = najdi_desku([frm, to], zprava)
            if found == frm:
                raise Neuspech("prepnuti na kanal %d se nepovedlo, oba jsou zpet na %d" % (to, frm))
            if found == to:
                konf_set("CH", to)
                raise Neuspech("deska zustala na kanalu %d, laptop je tam taky" % to)
            raise Neuspech("deska nenalezena na %d ani %d - zkontroluj ji ethernetem (deska.sh stav)" % (frm, to))
        pomocnik("potvrdit", tok=tok)   # od teď laptop zustava na novem kanalu
        # 4) ulozeni: posilat dokud deska nepotvrdi (nebo neuplyne jeji lhuta + 1 s)
        commit = None
        end = time.monotonic() + conf.get("commit_left_ms", 3000) / 1000.0 + 1.0
        while time.monotonic() < end and not commit:
            try:
                commit = deska("ch_commit", timeout=0.25, tries=1, cil=TUNEL, tok=tok, to=to)
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
        if not commit:
            zprava("Odpoved na ulozeni neprisla, hledam desku...")
            found = najdi_desku([to, frm], zprava)
            if found is None:
                raise Neuspech("deska nenalezena na %d ani %d - zkontroluj ji ethernetem (deska.sh stav)" % (to, frm))
            konf_set("CH", found)
            if found != to:
                raise Neuspech("prepnuti se nepovedlo, oba jsou zpet na %d" % found)
    except Neuspech:
        raise
    except BaseException:
        # necekana chyba / Ctrl+C: zrusit na desce a laptop zpet na puvodni kanal
        try:
            deska("ch_abort", timeout=0.3, tries=2, cil=TUNEL, tok=tok)
        except Exception:  # noqa: BLE001
            pass
        if laptop_prepnut:
            try:
                pomocnik("kanal", ch=frm)
            except Exception:  # noqa: BLE001
                pass
        raise
    try:
        konf_set("CH", to)
    except OSError as e:
        zprava("Varovani: kanal.conf se nepodarilo prepsat (%s)" % e)
    time.sleep(2.0)
    return {"ch": to, "z": frm, "laptop_ms": r["ms"], "deska_ms": conf.get("switch_ms"),
            "obraz_mezera_ms": obraz_mezera(t_obraz, time.time() * 1000)}


def popis_stavu(st):
    pasmo = "2,4 GHz" if (st.get("ch") or 0) <= 14 else "5,8 GHz"
    v = st.get("video") or {}
    rows = [
        "Kanal %s (%s), deska vykon %s/%s, laptop kanal %s vykon %s" % (
            st.get("ch"), pasmo, st.get("pwr"), st.get("pwr_max"), st.get("laptop_ch"), st.get("laptop_pwr")),
        "Obraz %s, %s fps (skutecne %.0f), GOP %s, tok %s kbit/s (skutecne %s), rezim snimace %s fps%s" % (
            str(st.get("res")).replace("*", "x"), st.get("fps"), st.get("real_fps") or 0, st.get("gop"),
            st.get("kbps"), st.get("kbps_real", "?"), st.get("rezim", 30), ", wrap (nizsi zpozdeni)" if st.get("wrap") else ""),
        "Prijem: ztraty %s, opraveno FEC %s %%, signal %s dBm, odezva tunelu %s ms, MCS %s, FEC %s/%s" % (
            st.get("ztraty", "?"), st.get("fec_pct", "?"), st.get("rssi", "?"), st.get("rtt_ms"),
            v.get("mcs", "?"), v.get("k", "?"), v.get("n", "?")),
    ]
    al = st.get("alink") or {}
    rep = al.get("rep") or {}
    if not al and st.get("switch"):
        rows.append("Adaptivni spoj: ? (probiha prepnuti kanalu)")
    elif al.get("on"):
        rows.append("Adaptivni spoj zap: %s; laptop hlasi SNR %s dB, FEC %s %%, ztraty %s" % (
            ("profil %s/4, MCS %s, tok %s kbit/s (strop %s)" % (al.get("p"), al.get("mcs"), al.get("kbps"), al.get("user_kbps")))
            if al.get("p") is not None else "ceka na zpravu z okna s videem",
            rep.get("snr", "?"), rep.get("fec_pct", "?"), rep.get("lost", "?")))
    else:
        rows.append("Adaptivni spoj vyp (pevne MCS %s)" % v.get("mcs", "?"))
    sm = st.get("smooth") or {}
    rows.append("Plynuly obraz %s; zadosti o klicovy snimek %s; ztraty obrazu za minutu %s%s" % (
        ("zap" + (" (GOP %s)" % st.get("gop") if sm.get("active") else " - ceka na prijimac, GOP %s" % st.get("gop")))
        if sm.get("on") else "vyp",
        "zap" if st.get("zadosti") else "vyp", st.get("ztraty_obrazu", "?"),
        ", obnova za %s ms" % st["obnova_ms"] if st.get("obnova_ms") is not None else ""))
    return "\n".join(rows)


def popis_vysledku(res):
    t = []
    if "obraz_mezera_ms" in res and res["obraz_mezera_ms"] is not None:
        t.append("nejdelsi mezera obrazu na laptopu %d ms" % res["obraz_mezera_ms"])
    if "gap_ms" in res:
        t.append("enkoder: nejdelsi mezera %d ms" % res["gap_ms"])
    return ", ".join(t)


def provest(cmd, arg, zprava=print):
    """Provede prikaz a zapise ho i s vysledkem do ovladani.log."""
    if cmd == "stav":
        return _provest(cmd, arg, zprava)
    zapis_log("PRIKAZ %s %s" % (cmd, arg if arg is not None else ""))
    t0 = time.time()
    try:
        out = _provest(cmd, arg, zprava)
    except Exception as e:
        zapis_log("CHYBA  %s %s (%.1f s): %s" % (cmd, arg if arg is not None else "", time.time() - t0, e))
        raise
    zapis_log("HOTOVO %s %s (%.1f s): %s" % (cmd, arg if arg is not None else "", time.time() - t0, out))
    return out


def _provest(cmd, arg, zprava=print):
    if cmd == "stav":
        return popis_stavu(prikaz_stav())
    if cmd == "tok":
        r = s_merenim(lambda: deska("set_bitrate", timeout=4, tries=2, kbps=int(arg)))
        return "Datovy tok %s -> %s kbit/s%s; %s" % (
            r["old"], r["kbps"], " (adaptivni spoj ted %s, vic MCS neunese)" % r["real"]
            if r.get("real") and r["real"] != r["kbps"] else "", popis_vysledku(r))
    if cmd == "fps":
        st = deska("status", timeout=1.5, tries=3)
        if st.get("res") and restart_potreba(str(st["res"]).replace("*", "x"), arg, st):
            return provest("obraz", "%s@%s" % (str(st["res"]).replace("*", "x"), arg), zprava)
        # deska po zmene meri skutecne fps (~3 s)
        r = s_merenim(lambda: deska("set_fps", timeout=6, tries=2, fps=int(arg)))
        return "Snimky %s -> %s fps (skutecne %s, GOP %s%s); %s" % (
            r["old"], r["fps"], r.get("real_fps", "?"), r["gop"], ", wrap" if r.get("wrap") else "", popis_vysledku(r))
    if cmd == "gop":
        r = deska("set_gop", timeout=3, tries=2, gop=int(arg))
        return "GOP %s -> %s" % (r["old"], r["gop"])
    if cmd == "rozliseni":
        r = s_merenim(lambda: deska("set_resolution", timeout=7, tries=2, res=arg), wait=3.5)
        return "Rozliseni %s -> %s (volani %d ms); %s" % (
            r["old"].replace("*", "x"), r["res"].replace("*", "x"), r["call_ms"], popis_vysledku(r))
    if cmd == "obraz":
        res, _, fps = str(arg).partition("@")
        if res not in RESOLUTIONS or not fps.isdigit() or not 5 <= int(fps) <= 60:
            raise ValueError("pouziti: obraz <%s>@<5-60, napr. %s>" % ("|".join(RESOLUTIONS), "|".join(FPS)))
        if not lze(res, fps):
            raise ValueError("%s pri %s fps nejde: 60 fps jen do %dx%d" % ((res, fps) + REZIM60_MAX))
        st = deska("status", timeout=1.5, tries=3)
        cur = st.get("rezim", 30)   # None = modul snimace na desce nenabehl -> prepnout (opravit) vzdy
        rz = rezim_pro(res, fps, cur or 30)
        if rz != cur or wrap_restart(rz, fps, st):
            if rz != cur:
                zprava("Prepinam rezim snimace %s -> %s fps: deska se restartuje, asi minutu bez obrazu..." % (cur, rz))
            else:
                zprava("%s fps %s: deska se restartuje, asi minutu bez obrazu..." % (
                    fps, "vypne wrap" if st.get("wrap") else "zapne wrap (nizsi zpozdeni)"))
            t0 = time.time()
            try:
                deska("set_mode", timeout=5, tries=2, res=res, fps=int(fps))
            except TimeoutError:   # odpoved se mohla ztratit, deska se uz restartuje - poznat podle stavu
                zprava("Deska nepotvrdila prepnuti, cekam, jestli se restartuje...")
            time.sleep(15)
            while time.time() - t0 < 180:
                try:
                    st2 = deska("status", timeout=1.5, tries=1)
                except Exception:  # noqa: BLE001  deska jeste startuje
                    time.sleep(3)
                    continue
                if st2.get("rezim") == cur and rz != cur:   # po skutecnem prepnuti uz stary rezim hlasit nemuze
                    raise RuntimeError("deska se nerestartovala, rezim snimace porad %s fps - zkus to znovu" % cur)
                if rz == cur and time.time() - t0 < 40 and str(st2.get("fps")) != str(fps):
                    time.sleep(3)   # restart jen kvuli wrapu: stara deska jeste muze odpovidat
                    continue
                if st2.get("rezim") == rz and st2.get("res") and st2.get("real_fps"):
                    time.sleep(2)   # RealFps se po startu kodéru teprve ustaluje
                    st2 = deska("status", timeout=1.5, tries=3)
                    real = st2.get("real_fps") or 0
                    txt = "Rezim snimace %s fps: obraz %s, %s fps (skutecne %.0f%s, deska zpet za %d s)" % (
                        rz, str(st2["res"]).replace("*", "x"), st2.get("fps"), real,
                        ", wrap" if st2.get("wrap") else "", time.time() - t0)
                    if real < 0.8 * int(fps):
                        raise RuntimeError(txt + " - POZOR: enkoder dava mene snimku, nez ma")
                    return txt
                time.sleep(3)
            raise RuntimeError("deska se po prepnuti rezimu do 3 min neozvala s obrazem - zkontroluj ji (ssh luckfox)")
        out = []
        if str(st.get("res")).replace("*", "x") != res:
            out.append(provest("rozliseni", res, zprava))
        if str(st.get("fps")) != fps:
            out.append(provest("fps", fps, zprava))
        if out:
            return "; ".join(out)
        real = st.get("real_fps") or 0
        if real < 0.8 * int(fps):
            raise RuntimeError("Obraz je nastaveny na %s @ %s fps, ale enkoder dava jen %.0f fps - zkus jine fps "
                               "a zpet, pripadne restartuj desku" % (res, fps, real))
        return "Obraz uz je %s @ %s fps (skutecne %.0f)" % (res, fps, real)
    if cmd == "vykon":
        r = s_merenim(lambda: vykon_desky(arg), wait=2.0)
        return "Vykon desky index %s -> %s (max %s, %d ms); %s" % (r["old"], r["idx"], r["max"], r["ms"], popis_vysledku(r))
    if cmd == "klicovy":
        r = deska("keyframe", timeout=1.0, tries=2)
        return "Klicovy snimek vyzadan" if r.get("sent") else "Deska zadost zahodila (predchozi pred %s ms)" % r.get("ago_ms")
    if cmd == "adaptivni":
        if arg not in ("zap", "vyp"):
            raise ValueError("pouziti: adaptivni zap|vyp")
        r = deska("set_alink", timeout=3, tries=2, on=arg == "zap")
        if arg == "vyp":
            return "Adaptivni spoj vypnut: pevne MCS z vima.conf, tok %s kbit/s" % r.get("user_kbps")
        return ("Adaptivni spoj zapnut: zacne od MCS 1 a podle kvality prijmu pujde nahoru"
                + ("" if prijem_conf().get("ZADOST_KF", "1") == "1" else " - POZOR: okno s videem nehlasi kvalitu (zadosti vyp)"))
    if cmd in ("plynule", "zadosti"):
        if arg not in ("zap", "vyp"):
            raise ValueError("pouziti: %s zap|vyp" % cmd)
        on = arg == "zap"
        if cmd == "zadosti":
            prijem_conf_set("ZADOST_KF", "1" if on else "0")
            return ("Okno s videem bude pri ztrate zadat o klicovy snimek" if on else
                    "Okno s videem uz nebude zadat o klicovy snimek (plynuly obraz se na desce vypne sam do 3 s)")
        r = deska("set_smooth", timeout=3, tries=2, on=on)
        if not on:
            return "Plynuly obraz vypnut, GOP zpet na fps (klicovy snimek 1x za sekundu)"
        return "Plynuly obraz zapnut" + ("" if r.get("active") else " - dlouhy GOP az se ozve okno s videem (zadosti zap)")
    if cmd == "najdi":
        ch = najdi_desku(CH_ALLOWED, zprava, kola=2, dwell=2.0)
        if ch is None:
            raise RuntimeError("deska nenalezena na zadnem povolenem kanalu")
        konf_set("CH", ch)
        return "Deska nalezena na kanalu %d, laptop prepnut tam (kanal.conf CH=%d)" % (ch, ch)
    if cmd == "pasmo":
        a = (arg or "").replace(",", ".")
        if a not in ("2.4", "5.8"):
            raise ValueError("pouziti: pasmo 2.4|5.8")
        key = "2G" if a == "2.4" else "5G"
        try:
            ch = int(konf().get("CH_%s_POSLEDNI" % key, PASMO_VYCHOZI[key]))
        except ValueError:
            ch = PASMO_VYCHOZI[key]
        if ch not in (CH_2G if key == "2G" else CH_5G):
            ch = PASMO_VYCHOZI[key]
        cmd, arg = "kanal", str(ch)
    if cmd == "kanal":
        r = prepnout_kanal(arg, zprava)
        konf_set("CH_2G_POSLEDNI" if r["ch"] <= 14 else "CH_5G_POSLEDNI", r["ch"])
        if r.get("beze_zmeny"):
            return "Kanal %s uz je nastaveny" % r["ch"]
        return "Kanal %s -> %s: deska %s ms, laptop %s ms; %s" % (
            r["z"], r["ch"], r["deska_ms"], r["laptop_ms"], popis_vysledku(r))
    raise ValueError("neznamy prikaz %s" % cmd)


# ---------------- okno (GTK 4) ----------------
def okno():
    import threading
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
    try:
        gi.require_version("Adw", "1")
        from gi.repository import Adw
        App = Adw.Application
    except (ValueError, ImportError):
        App = Gtk.Application

    app = App(application_id="cz.vima.ovladani")
    ui = {}
    busy = [False]

    def msg(t):
        def f():
            buf = ui["log"].get_buffer()
            buf.insert(buf.get_end_iter(), time.strftime("%H:%M:%S ") + t + "\n")
            ui["log"].scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
        GLib.idle_add(f)

    def set_busy(b, text=""):
        busy[0] = b
        for w in ui["buttons"]:
            w.set_sensitive(not b and (ui["synced"] or w not in ui["rowbtn"]))
        ui["spin"].set_spinning(b)
        ui["busy"].set_text(text)

    def run(cmd, arg):
        if busy[0]:
            return
        set_busy(True, "Provadim: %s %s..." % (cmd, arg))

        def work():
            try:
                msg(provest(cmd, arg, msg))
            except Exception as e:  # noqa: BLE001
                msg("CHYBA: %s" % e)
            GLib.idle_add(lambda: (set_busy(False, ""), refresh(True), False)[-1])
        threading.Thread(target=work).start()   # ne daemon: zavreni okna nepreusi prepnuti

    def aktualni(st):
        """Hodnoty, ktere jsou na desce a v okne s videem opravdu nastavene (pro rozbalovaci seznamy)."""
        mx, pwr = st.get("pwr_max"), st.get("pwr")
        vyk = None
        if mx and pwr is not None:
            lv = {"nizky": max(1, round(mx * 0.5)), "stredni": max(1, round(mx * 0.75)), "plny": mx}
            vyk = next((k for k, v in lv.items() if v == pwr), str(pwr))
        al = st.get("alink") or {}
        tok = al.get("user_kbps") if al.get("on") and al.get("user_kbps") else st.get("kbps")   # ne strop profilu
        return {"tok": "%s kbit/s" % tok if tok else None,
                "fps": str(st["fps"]) if st.get("fps") else None,
                "rozliseni": str(st["res"]).replace("*", "x") if st.get("res") else None,
                "plynule": ("zap" if st["smooth"].get("on") else "vyp") if st.get("smooth") else None,
                "adaptivni": ("zap" if st["alink"].get("on") else "vyp") if st.get("alink") else None,
                "zadosti": "zap" if st.get("zadosti") else "vyp",
                "vykon": vyk,
                "kanal": str(st["ch"]) if st.get("ch") else None,
                "pasmo": ("2,4 GHz" if st["ch"] <= 14 else "5,8 GHz") if st.get("ch") else None}

    def nastav_seznamy(st):
        ui["nastavuji"] = True
        try:
            _nastav_seznamy(st)
        finally:
            ui["nastavuji"] = False

    def _nastav_seznamy(st):
        if st.get("ch") and "kanal" in ui["dd"]:   # v seznamu kanalu jen kanaly aktualniho pasma
            dd, values = ui["dd"]["kanal"]
            nove = [str(c) for c in (CH_2G if st["ch"] <= 14 else CH_5G)]
            if values != nove:
                dd.get_model().splice(0, len(values), nove)
                values[:] = nove
        for cmd, val in aktualni(st).items():
            if cmd not in ui["dd"] or val is None:
                continue
            dd, values = ui["dd"][cmd]
            if val not in values:   # hodnota nastavena jinak nez z okna (napr. tok 1500)
                values.append(val)
                dd.get_model().append(val)
            dd.set_selected(values.index(val))
        for dd, _ in ui["dd"].values():
            dd.set_sensitive(True)
        for b in ui["rowbtn"]:
            b.set_sensitive(not busy[0])
        ui["obraz_stav"] = (str(st.get("res")).replace("*", "x"), str(st.get("fps")), st.get("rezim", 30))
        ui["st"] = st
        ui["dotknuto"] = False
        popis_tlacitka()

    def refresh(sync=False):
        if busy[0]:
            return True
        def work():
            st = None
            try:
                st = prikaz_stav()
                txt, ok = popis_stavu(st), True
            except Exception as e:  # noqa: BLE001
                txt, ok = "Deska neodpovida: %s\nBezi tunel.sh?" % e, False

            def ui_upd():
                ui["stav"].set_text(txt)
                if st:   # tlacitko Obraz rozhoduje o restartu podle aktualniho stavu, i kdyz uzivatel prave vybira
                    ui["st"] = st
                    popis_tlacitka()
                ui["dot"].set_markup('<span foreground="%s" size="x-large">●</span>' % ("#2e9d4a" if ok else "#c0392b"))
                if st and (sync or not ui["synced"]) and not busy[0]:
                    nastav_seznamy(st)   # po otevreni okna a po kazde zmene: seznamy ukazuji skutecny stav
                    ui["synced"] = True
                elif st and ui["synced"] and not busy[0] and not ui.get("dotknuto") and st.get("res") and \
                        (str(st["res"]).replace("*", "x"), str(st.get("fps")), st.get("rezim", 30)) != ui.get("obraz_stav"):
                    nastav_seznamy(st)   # obraz zmenen jinak (prikazova radka, restart desky) - neposilat stare hodnoty
                elif not st and sync:
                    ui["synced"] = False   # po zmene se stav nenacetl - nacist pri pristim uspesnem dotazu
                return False
            GLib.idle_add(ui_upd)
        threading.Thread(target=work, daemon=True).start()
        return True

    def row(box, label, values, cmd, note=None):
        values = list(values)
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lab = Gtk.Label(label=label, xalign=0)
        lab.set_size_request(150, -1)
        dd = Gtk.DropDown.new_from_strings(values)
        dd.set_sensitive(False)   # do nacteni skutecnych hodnot
        ui["dd"][cmd] = (dd, values)
        btn = Gtk.Button(label="Nastavit")
        btn.connect("clicked", lambda *_: run(cmd, values[dd.get_selected()].split(" ")[0]))
        btn.set_sensitive(False)   # do nacteni skutecnych hodnot
        ui["buttons"].append(btn)
        ui["rowbtn"].append(btn)
        h.append(lab)
        h.append(dd)
        h.append(btn)
        box.append(h)
        if note:
            n = Gtk.Label(label=note, xalign=0)
            n.add_css_class("dim-label")
            box.append(n)

    def dd_sede(values, cmd):
        """Rozbalovaci seznam, ve kterem jsou nemozne volby zasedle a nejdou vybrat."""
        model = Gtk.StringList.new(values)
        f = Gtk.SignalListItemFactory()

        def setup(_f, li):
            li.set_child(Gtk.Label(xalign=0))

        def bind(_f, li):
            val = li.get_item().get_string()
            li.get_child().set_label(val)
            ok = povoleno(cmd, val)
            li.get_child().set_sensitive(ok)
            li.set_activatable(ok)
            li.set_selectable(ok)
        f.connect("setup", setup)
        f.connect("bind", bind)
        dd = Gtk.DropDown(model=model)
        dd.set_factory(f)
        return dd

    def vybrano(cmd):
        dd, values = ui["dd"][cmd]
        i = dd.get_selected()
        return values[i] if 0 <= i < len(values) else None

    def povoleno(cmd, val):
        if "rozliseni" not in ui["dd"] or "fps" not in ui["dd"]:
            return True
        if cmd == "fps":
            res = vybrano("rozliseni")
            return res is None or lze(res, val)
        fps = vybrano("fps")
        return fps is None or lze(val, fps)

    def prekresli(cmd):
        """Po zmene jednoho seznamu znovu vykreslit polozky druheho (zasedle podle nove volby)."""
        if ui.get("prekresluji"):
            return
        ui["prekresluji"] = True
        try:
            dd, values = ui["dd"][cmd]
            i = dd.get_selected()
            m = dd.get_model()
            m.splice(0, m.get_n_items(), values)   # nove polozky = nove vykresleni (bind) i v otevrenem seznamu
            dd.set_selected(i)
        finally:
            ui["prekresluji"] = False

    def popis_tlacitka():
        """Tlacitko rekne predem, kdy volba restartuje desku (prepnuti rezimu snimace)."""
        btn = ui.get("obraz_btn")
        res, fps = vybrano("rozliseni"), vybrano("fps")
        if not btn or res is None or fps is None:
            return
        st = ui.get("st") or {"rezim": (ui.get("obraz_stav") or (None, None, 30))[2]}
        btn.set_label("Nastavit (restart desky)" if restart_potreba(res, fps, st) else "Nastavit")

    def zmena_vyberu(druhy):
        if not ui.get("prekresluji") and not ui.get("nastavuji"):
            ui["dotknuto"] = True   # uzivatel vybira - periodicky stav mu vyber neprepise
        prekresli(druhy)
        popis_tlacitka()

    def row_obraz(box):
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lab = Gtk.Label(label="Obraz:", xalign=0)
        lab.set_size_request(150, -1)
        h.append(lab)
        for cmd, values in (("rozliseni", RESOLUTIONS), ("fps", FPS)):
            dd = dd_sede(values, cmd)
            dd.set_sensitive(False)   # do nacteni skutecnych hodnot
            ui["dd"][cmd] = (dd, list(values))
            h.append(dd)
            if cmd == "fps":
                h.append(Gtk.Label(label="fps"))
        ui["dd"]["rozliseni"][0].connect("notify::selected", lambda *_: zmena_vyberu("fps"))
        ui["dd"]["fps"][0].connect("notify::selected", lambda *_: zmena_vyberu("rozliseni"))
        btn = Gtk.Button(label="Nastavit")
        ui["obraz_btn"] = btn
        btn.connect("clicked", lambda *_: run("obraz", "%s@%s" % (vybrano("rozliseni"), vybrano("fps"))))
        btn.set_sensitive(False)
        ui["buttons"].append(btn)
        ui["rowbtn"].append(btn)
        h.append(btn)
        box.append(h)
        n = Gtk.Label(label="55 a 60 fps jen do 1152x648 (zašedlé nejde). 55 fps má nejnižší zpoždění (kodér kóduje už "
                            "během snímání), 60 fps je plynulejší. Restart desky (asi minutu bez obrazu) při přepnutí "
                            "režimu snímače (volba 55/60 fps, nebo v režimu 60 rozlišení nad 1152x648) a při přechodu "
                            "mezi 55 a 60 fps – tlačítko to napíše. Jinak obraz zmizí jen na zlomek sekundy.", xalign=0, wrap=True)
        n.add_css_class("dim-label")
        box.append(n)

    def frame(title):
        f = Gtk.Frame(label=title)
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8, margin_bottom=8,
                    margin_start=10, margin_end=10)
        f.set_child(b)
        return f, b

    def activate(a):
        ui["buttons"] = []
        ui["dd"] = {}
        ui["rowbtn"] = []
        ui["synced"] = False
        win = Gtk.ApplicationWindow(application=a, title="Vima – ovládání")
        win.set_default_size(600, 720)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12,
                       margin_start=12, margin_end=12)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ui["dot"] = Gtk.Label()
        ui["stav"] = Gtk.Label(label="Zjistuji stav...", xalign=0, wrap=True)
        top.append(ui["dot"])
        top.append(ui["stav"])
        root.append(top)

        f, b = frame("Obraz")
        row(b, "Datový tok:", ["512 kbit/s", "1024 kbit/s", "2048 kbit/s", "3072 kbit/s"], "tok")
        row_obraz(b)
        row(b, "Plynulý obraz:", ["zap", "vyp"], "plynule",
            "bez trhnutí každou sekundu: klíčový snímek jen po ztrátě, na žádost okna s videem")
        row(b, "Žádat klíčový snímek:", ["zap", "vyp"], "zadosti", "okno s videem po ztrátě paketů požádá desku")
        kb = Gtk.Button(label="Poslat klíčový snímek teď")
        kb.connect("clicked", lambda *_: run("klicovy", None))
        ui["buttons"].append(kb)
        b.append(kb)
        root.append(f)

        f, b = frame("Vysílání")
        row(b, "Adaptivní spoj:", ["zap", "vyp"], "adaptivni",
            "deska podle kvality příjmu mění MCS a tok (nejvýš nastavený datový tok)")
        row(b, "Výkon desky:", ["nizky", "stredni", "plny"], "vykon", "nízký = 1/2, střední = 3/4 maxima pro pásmo")
        row(b, "Pásmo:", ["2,4 GHz", "5,8 GHz"], "pasmo",
            "přepne na naposledy použitý kanál v pásmu, výkon se sám nastaví na limit pásma")
        row(b, "Kanál (deska i laptop):", [str(c) for c in CH_ALLOWED], "kanal",
            "když se spojení do 4 s neobnoví, oba se vrátí na původní kanál")
        root.append(f)

        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ui["spin"] = Gtk.Spinner()
        ui["busy"] = Gtk.Label(xalign=0)
        hb.append(ui["spin"])
        hb.append(ui["busy"])
        root.append(hb)

        ui["log"] = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.set_child(ui["log"])
        root.append(sc)
        win.set_child(root)
        win.connect("close-request", lambda *_: busy[0])   # behem prace okno nejde zavrit
        win.present()
        refresh()
        GLib.timeout_add_seconds(3, refresh)

    app.connect("activate", activate)
    import signal
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    except (ImportError, ValueError):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    app.run([])


def main(argv):
    global BOARD
    if "--kabel" in argv:
        argv.remove("--kabel")
        BOARD = ("10.42.0.2", 5900)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__ or open(__file__).read().split("\nimport")[0])
        return 1
    cmd, arg = argv[0], (argv[1] if len(argv) > 1 else None)
    if cmd == "pomocnik":
        pomocnik_server()
        return 0
    if cmd == "okno":
        okno()
        return 0
    try:
        print(provest(cmd, arg))
        return 0
    except Exception as e:  # noqa: BLE001
        print("CHYBA:", e)
        return 2 if "zpet" in str(e) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
