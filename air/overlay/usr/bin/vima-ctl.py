#!/usr/bin/python3
# Vima: ovladani desky ze zeme pres IP tunel (krok 2).
# UDP port 5900, dotaz i odpoved jsou JSON {"id": .., "op": .., ...}. Komunikaci vzdy zacina laptop
# (firewall laptopu pusti jen odpovedi). Prijima jen od 10.5.0.1 (tunel) a 10.42.0.1 (ethernet, stul);
# potvrzeni prepnuti kanalu jen pres tunel (overuje, ze spoj na novem kanalu opravdu funguje).
#
# Video (rkipc, socket /var/tmp/rkipc): datovy tok, fps, GOP a rozliseni za behu, bez restartu rkipc.
# Zmeny videa a vykonu jsou docasne: po restartu desky plati rkipc ini a vima.conf (bezpecne vychozi).
# Kanal: dvoufazove prepnuti s automatickym navratem, po potvrzeni se ulozi do vima.conf.
# Bezpecnost vysilani: pevne zakonne stropy indexu (2,4 GHz 50, 5,8 GHz 20), pred zmenou kanalu
# se vykon snizi, cilovy vykon az po overeni kanalu; hlidac srovnava kanal s vima.conf a vykon se stropem.
import fcntl
import json
import os
import random
import re
import select
import socket
import struct
import subprocess
import time

PORT = int(os.environ.get("VIMA_CTL_PORT", "5900"))
CONF = os.environ.get("VIMA_CONF", "/etc/vima/vima.conf")
RKIPC = "/var/tmp/rkipc"
VENC_INFO = "/proc/vcodec/enc/venc_info"
LOCK = "/var/run/vima-radio.lock"   # spolecny zamek s vima-wfb (setup_if)
TUN_PEER = "10.5.0.1"
ALLOWED_SRC = (TUN_PEER, "10.42.0.1")
CH_ALLOWED = list(range(1, 14)) + [149, 153, 157, 161, 165]
LEGAL_2G, LEGAL_5G = 50, 20         # zakonne stropy indexu desky (odhad EIRP, viz vima.conf)
RESOLUTIONS = ["640*360", "960*540", "1152*648", "1280*720", "1920*1080", "2304*1296"]
BITRATE_MIN, BITRATE_MAX = 128, 6144
FPS_MIN, FPS_MAX = 5, 60
# Rezim snimace SC3336 se vybira pri startu desky (modul /oem/usr/ko/sc3336.ko + rkipc ini v /oem):
#   30: snimac 2304x1296 do 30 fps, obraz do 2304x1296
#   60: snimac 2304x648 (svisle preskakovani radku), do 60 fps, obraz do 1152x648
# Prepnuti (set_mode) = jiny modul + ini a restart desky (~1 min bez obrazu). Uvnitr rezimu se
# rozliseni a fps meni za behu (set_resolution, set_fps). Viz ~/vima-board/sc3336-60fps.
REZIM_DIR = "/oem/usr/share/vima"         # sc3336-30.ko (puvodni), sc3336-60.ko (varianta D)
OEM_KO = "/oem/usr/ko/sc3336.ko"
OEM_INI = "/oem/usr/share/rkipc-300w.ini"
OEM_IQ = "/oem/usr/share/iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json"   # rezim 60 potrebuje LSC 2304x648
# Wrap (rkipc build ~/vima-board/wrap): VENC koduje uz behem vycitani snimace, -4 ms na desce. Kodér ve
# wrapu potrebuje mezi snimky pauzu snimace ~1-1,5 ms, jinak vynecha kazdy druhy snimek (27. 10.: 1152x648
# 60/58 fps -> 30/29, 55 fps OK; 2304x1296@30 -> 15). rkipc rozhodne o wrapu JEN pri startu (enable_wrap
# a fps snimace <= wrap_max_fps v ini); prepnuti wrapu za behu (rk_video_restart) 3. 11. rozbilo desku.
#   wrap_max = do tohoto fps smi wrap bezet; wrap_fps = volba "nizsi zpozdeni" (restart desky se zapnutym wrapem)
REZIMY = {30: {"max": (2304, 1296), "fps": 30, "jpeg": (1920, 1080), "wrap_max": 0, "wrap_fps": None},
          60: {"max": (1152, 648), "fps": 60, "jpeg": (1152, 648), "wrap_max": 55, "wrap_fps": 55}}


def log(msg):
    print(time.strftime("%H:%M:%S"), "vima-ctl:", msg, flush=True)


# ---------- konfigurace ----------
def read_conf():
    c = {}
    try:
        for line in open(CONF):
            m = re.match(r"\s*([A-Z0-9_]+)=([^#]*)", line)
            if m:
                c[m.group(1)] = m.group(2).strip().strip('"')
    except OSError:
        pass
    return c


def write_conf_key(key, value):
    """Prepise jeden radek KEY=... ve vima.conf atomicky (tmp + fsync + rename + fsync adresare)."""
    lines = open(CONF).read().splitlines(True)
    out, done = [], False
    for line in lines:
        if re.match(r"\s*%s=" % re.escape(key), line):
            out.append("%s=%s\n" % (key, value))
            done = True
        else:
            out.append(line)
    if not done:
        out.append("%s=%s\n" % (key, value))
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write("".join(out))
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, CONF)
    fd = os.open(os.path.dirname(CONF), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def conf_int(c, key, default):
    try:
        return int(c.get(key, default))
    except (TypeError, ValueError):
        return default


def legal(ch):
    return LEGAL_2G if ch <= 14 else LEGAL_5G


def band_cap(ch, c=None):
    """Index vykonu pro pasmo kanalu: hodnota z vima.conf, ale vzdy 1..zakonny strop."""
    c = c or read_conf()
    base = conf_int(c, "WFB_TXPWR_IDX", 10)
    v = conf_int(c, "WFB_TXPWR_IDX_2G" if ch <= 14 else "WFB_TXPWR_IDX_5G", base)
    return max(1, min(v, legal(ch)))


# ---------- rkipc ----------
def _recvn(s, n):
    b = b""
    while len(b) < n:
        d = s.recv(n - len(b))
        if not d:
            raise ConnectionError("rkipc zavrel spojeni")
        b += d
    return b


def rk(name, args=b"", get=None, timeout=2.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(RKIPC)
        _recvn(s, 4)
        n = name.encode() + b"\0"
        s.sendall(struct.pack("<i", len(n)) + n + args)
        val = None
        if get == "int":
            val = struct.unpack("<i", _recvn(s, 4))[0]
        elif get == "str":
            ln = struct.unpack("<i", _recvn(s, 4))[0]
            val = _recvn(s, ln).decode(errors="replace").rstrip("\0")
        err = struct.unpack("<i", _recvn(s, 4))[0]
        _recvn(s, 4)
        return err, val
    finally:
        s.close()


def rk_get_int(name):
    return rk(name, struct.pack("<i", 0), "int")[1]


def rk_get_str(name):
    return rk(name, struct.pack("<i", 0), "str")[1]


def rk_set_int(name, v, timeout=2.0):
    return rk(name, struct.pack("<ii", 0, int(v)), timeout=timeout)[0]


def rk_set_str(name, v, timeout=2.0):
    b = v.encode() + b"\0"
    return rk(name, struct.pack("<ii", 0, len(b)) + b, timeout=timeout)[0]


def venc():
    """Zive hodnoty kanalu 0 enkoderu z /proc/vcodec/enc/venc_info."""
    d = {}
    try:
        lines = open(VENC_INFO).read().splitlines()
    except OSError:
        return d
    for i, line in enumerate(lines):
        if "|" not in line or not re.match(r"\s*(ID|ChnId)\|", line):
            continue
        keys = [k.strip() for k in line.split("|")]
        for nl in lines[i + 1:i + 3]:
            vals = [v.strip() for v in nl.split("|")]
            if vals and vals[0] == "0":
                for k, v in zip(keys, vals):
                    d.setdefault(k, v)
                break
    return d


def venc_seq():
    """Pocitadlo snimku, ktere enkoder opravdu vydal. pkt_total_cnt, ne seq_encoded: to roste i za
    snimky, ktere kodér ve wrapu vynechal (27. 10.: seq 73001, vydano 36615 = jen polovina fps)."""
    v = venc()
    try:
        return int(v.get("pkt_total_cnt") or v.get("seq_encoded") or "-1")
    except ValueError:
        return -1


def real_fps(duration=1.0):
    """Snimky za sekundu, ktere enkoder opravdu vydal (None = nejde zmerit, napr. restart kanalu)."""
    s0, t0 = venc_seq(), time.monotonic()
    time.sleep(duration)
    s1, t1 = venc_seq(), time.monotonic()
    if s0 < 0 or s1 < s0:
        return None
    return (s1 - s0) / (t1 - t0)


FPS_MER = {"t": None, "s": None, "fps": None}   # skutecne fps z pkt_total_cnt, meri timers() 1x za s


def fps_mer_tick():
    now = time.monotonic()
    if FPS_MER["t"] is not None and now - FPS_MER["t"] < 1.0:
        return
    s = venc_seq()
    if FPS_MER["t"] is not None and s >= 0 and FPS_MER["s"] is not None and s >= FPS_MER["s"] and now - FPS_MER["t"] < 5.0:
        FPS_MER["fps"] = (s - FPS_MER["s"]) / (now - FPS_MER["t"])
    else:
        FPS_MER["fps"] = None   # prvni vzorek, restart kanalu (pocitadlo od nuly) nebo dlouha pauza smycky
    FPS_MER["t"], FPS_MER["s"] = now, s


def wrap_on():
    """Bezi kanal 0 enkoderu ve wrapu (online z ISP)? venc_info: venc chn attr 1, sloupec Online."""
    return venc().get("Online") == "1"


def max_gap(duration, t_start=None):
    """Sleduje pocitadlo zakodovanych snimku; vrati (nejdelsi mezera ms, mezera na konci ms)."""
    t0 = t_start or time.monotonic()
    last_seq, last_t, gap = venc_seq(), t0, 0.0
    end = time.monotonic() + duration
    while time.monotonic() < end:
        time.sleep(0.005)
        s = venc_seq()
        if s != last_seq:
            now = time.monotonic()
            gap = max(gap, now - last_t)
            last_seq, last_t = s, now
    trailing = time.monotonic() - last_t
    return round(max(gap, trailing) * 1000), round(trailing * 1000)


# ---------- wfb_tx rizeni (127.0.0.1, pevne porty z vima-wfb) ----------
def wfb_cmd(port, cmd, payload=b"", resp_len=0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))   # zavreny port -> chyba hned, ne az timeout
        rid = random.getrandbits(32)
        s.send(struct.pack("!IB", rid, cmd) + payload)
        d = s.recv(64)
        _, rc = struct.unpack("!II", d[:8])
        return rc, d[8:8 + resp_len]
    finally:
        s.close()


def wfb_get(port):
    try:
        rc, fec = wfb_cmd(port, 3, resp_len=2)
        rc2, rad = wfb_cmd(port, 4, resp_len=7)
        if rc or rc2:
            return None
        return {"k": fec[0], "n": fec[1], "stbc": rad[0], "ldpc": rad[1], "bw": rad[3], "mcs": rad[4]}
    except (OSError, struct.error):
        return None


# ---------- karta ----------
def iw_info():
    out = subprocess.run(["iw", "dev", IF, "info"], capture_output=True, text=True, timeout=3).stdout
    m = re.search(r"channel (\d+) \((\d+) MHz\)", out)
    p = re.search(r"txpower (-?[\d.]+) dBm", out)
    ch = int(m.group(1)) if m else None
    mhz = int(m.group(2)) if m else None
    idx = int(round(-float(p.group(1)))) if p else None
    return ch, mhz, idx


def set_power(idx):
    # zaporne mBm = index override (kladne nebo 0 by znamenalo tovarni neomezeny vykon - nikdy)
    if not 1 <= idx <= LEGAL_2G:
        raise ValueError("index vykonu %s mimo 1-%d" % (idx, LEGAL_2G))
    subprocess.run(["iw", "dev", IF, "set", "txpower", "fixed", "-%d00" % idx], check=True, timeout=5)


def switch_channel(ch):
    """Prepne kartu za behu (bez link down): nejdriv nizsi vykon obou pasem, pak kanal,
    a cilovy vykon az kdyz karta opravdu hlasi novy kanal."""
    if ch not in CH_ALLOWED:
        raise ValueError("kanal %s neni povoleny" % ch)
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        c = read_conf()
        cur_ch, _, cur_idx = iw_info()
        caps = [band_cap(ch, c), band_cap(cur_ch, c) if cur_ch else min(band_cap(1, c), band_cap(149, c))]
        if cur_idx and cur_idx >= 1:
            caps.append(cur_idx)
        lo = min(caps)
        target = band_cap(ch, c)
        t0 = time.monotonic()
        set_power(lo)
        subprocess.run(["iw", "dev", IF, "set", "channel", str(ch), "HT20"], check=True, timeout=10)
        new_ch, _, _ = iw_info()
        if new_ch != ch:
            # ovladac vraci 0 i pri neuspechu - vykon nechat nizky, jak je
            raise RuntimeError("karta hlasi kanal %s misto %s (vykon zustava %d)" % (new_ch, ch, lo))
        set_power(target)
        _, _, idx = iw_info()
        ms = round((time.monotonic() - t0) * 1000)
    if idx != target:
        log("POZOR: index po prepnuti %s, ocekavano %d" % (idx, target))
    log("kanal %s -> %s (%d ms), vykon index %d" % (cur_ch, ch, ms, target))
    return ms


IF = read_conf().get("WFB_IF", "wfb0")
VIDEO_CTL = conf_int(read_conf(), "WFB_CTRL_PORT", 8000)
TUN_CTL = conf_int(read_conf(), "TUN_CTRL_PORT", 8001)


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception:  # noqa: BLE001
        return None


# ---------- rezim snimace ----------
def rezim():
    """60 = bezi modul s rezimem 60 fps (parametr bin60), 30 = puvodni modul, None = modul snimace nenabehl."""
    try:
        return 60 if open("/sys/module/sc3336/parameters/bin60").read().strip() == "Y" else 30
    except OSError:
        return 30 if os.path.isdir("/sys/module/sc3336") else None


def rezim_cap():
    return REZIMY.get(rezim(), REZIMY[30])


def wh(res):
    w, h = (int(x) for x in str(res).replace("x", "*").replace("X", "*").replace("\u00d7", "*").split("*"))
    return w, h


def rezim_pro(w, h, fps):
    """Rezim snimace, ktery umi obraz w x h pri fps (prednost ma bezici); None = nejde."""
    ok = [r for r, c in REZIMY.items() if w <= c["max"][0] and h <= c["max"][1] and fps <= c["fps"]]
    if not ok:
        return None
    cur = rezim()
    return cur if cur in ok else ok[0]


def ini_rezim(text, rz, w, h, fps):
    """rkipc ini pro rezim rz: nastavi jen klice video.0 / video.jpeg / isp.0.adjustment, zbytek necha."""
    mw, mh = REZIMY[rz]["max"]
    jw, jh = REZIMY[rz]["jpeg"]
    sets = {("video.0", "max_width"): mw, ("video.0", "max_height"): mh, ("video.0", "width"): w,
            ("video.0", "height"): h, ("video.0", "buffer_size"): w * h // 2,
            ("video.0", "src_frame_rate_num"): fps, ("video.0", "dst_frame_rate_num"): fps, ("video.0", "gop"): fps,
            ("video.jpeg", "width"): jw, ("video.jpeg", "height"): jh, ("isp.0.adjustment", "fps"): fps}
    # nepovinne (chybi-li, doplni se na konec sekce): do jakeho fps snimace smi rkipc zapnout wrap
    opt = {("video.source", "wrap_max_fps"): REZIMY[rz]["wrap_max"]}
    vse = dict(sets)
    vse.update(opt)
    out, sec, done = [], None, set()

    def doplnit(sekce):
        for k, v in opt.items():
            if k[0] == sekce and k not in done:
                out.append("%s = %s\n" % (k[1], v))
                done.add(k)

    for line in text.splitlines(True):
        t = line.rstrip("\r\n")
        m = re.match(r"\[(.*)\]", t)
        if m:
            doplnit(sec)
            sec = m.group(1)
        else:
            m = re.match(r"(\s*)([A-Za-z0-9_.]+)(\s*=\s*)([^;]*?)(\s*;.*)?$", t)
            if m and (sec, m.group(2)) in vse:
                k = (sec, m.group(2))
                line = "%s%s%s%s%s\n" % (m.group(1), m.group(2), m.group(3), vse[k],
                                          " " + m.group(5).strip() if m.group(5) else "")
                done.add(k)
        out.append(line)
    doplnit(sec)
    if not set(sets) <= done:
        raise RuntimeError("v rkipc ini chybi %s" % ", ".join("[%s] %s" % k for k in sorted(set(sets) - done)))
    return "".join(out)


def ini_hodnota(path, sekce, klic):
    """Hodnota klice z rkipc ini (bez komentare), None = chybi."""
    sec = None
    try:
        for line in open(path):
            t = line.strip()
            m = re.match(r"\[(.*)\]", t)
            if m:
                sec = m.group(1)
                continue
            m = re.match(r"([A-Za-z0-9_.]+)\s*=\s*([^;]*?)\s*(;.*)?$", t)
            if m and sec == sekce and m.group(1) == klic:
                return m.group(2)
    except OSError:
        pass
    return None


def wrap_povolen():
    """enable_wrap = 1 v /oem ini (rkipc ho nacte pri pristim startu desky)."""
    return ini_hodnota(OEM_INI, "video.source", "enable_wrap") == "1"


def wrap_restart(rz, fps, wrap_ted):
    """Je kvuli wrapu potreba restart desky? Bezi-li wrap, nad wrap_max by kodér pulil snimky;
    nebezi-li a je povolen, volba wrap_fps (55 = nizsi zpozdeni) ho zapne az po startu."""
    c = REZIMY[rz]
    if wrap_ted:
        return fps > c["wrap_max"]
    return wrap_povolen() and fps == c["wrap_fps"]


def zapis_atomicky(path, data):
    tmp = path + ".novy"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)
    fd = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def op_set_mode(req):
    """Prepne rezim snimace 30 <-> 60 fps a restartuje desku; obraz po startu = res + fps."""
    w, h = wh(req["res"])
    fps = int(req["fps"])
    res = "%d*%d" % (w, h)
    if res not in RESOLUTIONS or not FPS_MIN <= fps <= FPS_MAX:
        raise ValueError("obraz %s pri %d fps neni v nabidce" % (res, fps))
    rz, cur = rezim_pro(w, h, fps), rezim()
    if rz is None:
        raise ValueError("%dx%d pri %d fps nejde: 60 fps jen do 1152x648" % (w, h, fps))
    wrap_ted = wrap_on()
    if rz == cur and not wrap_restart(cur, fps, wrap_ted):
        raise ValueError("rezim snimace %d fps uz bezi - rozliseni a fps jdou zmenit za behu" % cur)
    if rz == 60:
        try:
            iq_ok = b'"2304x648"' in open(OEM_IQ, "rb").read()
        except OSError:
            iq_ok = False
        if not iq_ok:
            raise ValueError("IQ na desce nema LSC 2304x648 - nejdriv nahraj IQ z ~/vima-board/sc3336-60fps/iq")
    data_ko = open(os.path.join(REZIM_DIR, "sc3336-%d.ko" % rz), "rb").read()
    ini = ini_rezim(open(OEM_INI).read(), rz, w, h, fps).encode()
    # Poradi zapisu: pri vypadku napajeni mezi zapisy zustane kombinace, ktera jeste da obraz
    # (ini 60 s modulem 30 jede; ini 30 s modulem 60 ne - rkipc chce vic, nez snimac da).
    try:
        ko_stejny = open(OEM_KO, "rb").read() == data_ko   # jen restart kvuli wrapu: modul neprepisovat
    except OSError:
        ko_stejny = False
    if rz == 60:
        zapis_atomicky(OEM_INI, ini)
        if not ko_stejny:
            zapis_atomicky(OEM_KO, data_ko)
    else:
        if not ko_stejny:
            zapis_atomicky(OEM_KO, data_ko)
        zapis_atomicky(OEM_INI, ini)
    # log pred restartem a bez %d (cur muze byt None = modul snimace nenabehl, oprava pres set_mode):
    # chyba formatovani po zapisu souboru by z uspechu udelala chybu
    log("rezim snimace %s -> %s (obraz %dx%d @ %d fps, wrap %s -> %s), restart desky" % (
        cur, rz, w, h, fps, wrap_ted, wrap_povolen() and fps <= REZIMY[rz]["wrap_max"]))
    subprocess.Popen(["sh", "-c", "sleep 1; sync; reboot"], start_new_session=True)
    return {"rezim": rz, "old": cur, "res": res, "fps": fps, "reboot": True}


# ---------- prikazy ----------
def status():
    ch, mhz, idx = iw_info()
    st = {"ch": ch, "mhz": mhz, "pwr": idx, "pwr_max": band_cap(ch) if ch else None,
          "switch": sw["phase"] if sw else None,
          "rezim": rezim(), "wrap_en": wrap_povolen(),
          "rezimy": {str(k): [c["max"][0], c["max"][1], c["fps"], c["wrap_max"], c["wrap_fps"]] for k, c in REZIMY.items()}}
    if sw:   # behem prepinani jen levne udaje, at se nezdrzuji casovace
        st.update({"alink": alink_state(), "smooth": smooth_state()})
        return st
    v = safe(venc) or {}
    st.update({"res": safe(rk_get_str, "rk_video_get_resolution"), "fps": safe(rk_get_str, "rk_video_get_frame_rate"),
               "gop": safe(rk_get_int, "rk_video_get_gop"), "kbps": safe(rk_get_int, "rk_video_get_max_rate"),
               "kf": dict(kf), "smooth": smooth_state(), "alink": alink_state(),
               # skutecne fps z vydanych snimku (RealFps z venc_info po restartu kanalu zustava 0)
               "real_fps": round(FPS_MER["fps"], 1) if FPS_MER["fps"] is not None else int(v.get("RealFps*10", "0") or 0) / 10.0,
               "venc_realfps": int(v.get("RealFps*10", "0") or 0) / 10.0,
               "sensor_fps": v.get("SrcFr"), "enc_w": v.get("Width"), "enc_h": v.get("Height"),
               "wrap": v.get("Online") == "1",
               "video": wfb_get(VIDEO_CTL), "tunel": wfb_get(TUN_CTL)})
    return st


def check_video(width=None, height=None, fps=None, kbps=None, gop=None, wait=1.5, src_fps=None):
    """rkipc vraci vzdy 0 - zmenu overit podle zivych hodnot enkoderu."""
    end = time.monotonic() + wait
    while True:
        v = venc()
        ok = True
        if width and (v.get("Width") != str(width) or v.get("Height") != str(height)):
            ok = False
        if fps and v.get("TarFr") != str(fps):
            ok = False
        if src_fps and v.get("SrcFr") != str(src_fps):
            ok = False
        if kbps and v.get("Br(kbps)") != str(kbps):
            ok = False
        if gop and v.get("Gop") != str(gop):
            ok = False
        if ok or time.monotonic() > end:
            return ok
        time.sleep(0.05)


def flowing(trailing_ms):
    return trailing_ms < 500


def op_set_bitrate(req):
    kbps = int(req["kbps"])
    if not BITRATE_MIN <= kbps <= BITRATE_MAX:
        raise ValueError("datovy tok %d mimo %d-%d kbit/s" % (kbps, BITRATE_MIN, BITRATE_MAX))
    old = rk_get_int("rk_video_get_max_rate")
    user_old = user_kbps()
    user_kbps_save(kbps)
    real = alink_kbps() if alink["on"] and alink["p"] is not None else kbps   # adaptivni spoj: strop profilu
    t0 = time.monotonic()
    rk_set_int("rk_video_set_max_rate", real)
    gap, trail = max_gap(1.0, t0)
    if not check_video(kbps=real) or not flowing(trail):
        rk_set_int("rk_video_set_max_rate", old)
        user_kbps_save(user_old)
        raise RuntimeError("enkoder zmenu neprijal, vraceno na %d" % old)
    log("datovy tok %d -> %d kbit/s%s, nejdelsi mezera snimku %d ms" % (
        old, real, " (pozadovano %d, strop profilu)" % kbps if real != kbps else "", gap))
    return {"kbps": kbps, "real": real, "old": old, "gap_ms": gap}


def op_set_fps(req):
    fps = int(req["fps"])
    cap = min(FPS_MAX, rezim_cap()["fps"])
    if not FPS_MIN <= fps <= cap:
        raise ValueError("fps %d mimo %d-%d (rezim snimace %s fps; 60 fps prepina okno spolu s rozlisenim)" % (
            fps, FPS_MIN, cap, rezim()))
    old_wrap = wrap_on()
    if wrap_restart(rezim() or 30, fps, old_wrap):
        raise ValueError("%d fps %s - jen s restartem desky (okno: Obraz > Nastavit (restart desky); "
                         "prikazova radka: obraz <rozliseni>@%d)" % (
                             fps, "by vypnulo wrap" if old_wrap else "se zapnutym wrapem (nizsi zpozdeni)", fps))
    old_fps = rk_get_str("rk_video_get_frame_rate")
    old_gop = rk_get_int("rk_video_get_gop")
    old_sensor = rk_get_int("rk_isp_get_frame_rate")
    if old_sensor is None or old_sensor <= 0:
        old_sensor = 30
    gop = int(req.get("gop", SMOOTH_GOP if smooth_active() else fps))  # vychozi: klicovy snimek 1x za sekundu
    t0 = time.monotonic()

    def nastav(sensor, video, g):
        # Nejdriv snimac primo na fps: samotne rk_video_set_frame_rate by z 30 fps snimace snimky
        # nepravidelne zahazovalo (25 fps = 5x za sekundu mezera 67 ms misto 40 ms -> zadrhavani).
        rk_set_int("rk_isp_set_frame_rate", sensor)
        rk_set_str("rk_video_set_frame_rate", str(video))
        rk_set_int("rk_video_set_gop", g)

    nastav(fps, fps, gop)
    t_call = time.monotonic() - t0
    gap, trail = max_gap(1.5, t0)
    ok = check_video(fps=fps, gop=gop, src_fps=fps) and flowing(trail)
    real = real_fps(1.0) if ok else None
    if not ok or real is None or real < 0.8 * fps:
        log("fps %s -> %d NEPRIJATO (skutecne %s fps, wrap %s, mezera na konci %d ms) - vracim" % (
            old_fps, fps, "?" if real is None else "%.1f" % real, wrap_on(), trail))
        nastav(old_sensor, old_fps, old_gop)
        po = real_fps(1.5)
        if not po:
            log("fps: po navratu na %s fps enkoder nevydava snimky" % old_fps)
            raise RuntimeError("enkoder zmenu neprijal a po navratu na %s fps nebezi video - restartuj desku" % old_fps)
        raise RuntimeError("enkoder zmenu neprijal (skutecne %s fps), vraceno na %s fps (ted %.0f fps)" % (
            "?" if real is None else "%.0f" % real, old_fps, po))
    w = wrap_on()
    log("fps %s -> %d (GOP %d, skutecne %.1f fps, wrap %s, volani %d ms), nejdelsi mezera snimku %d ms" % (
        old_fps, fps, gop, real, w, t_call * 1000, gap))
    return {"fps": fps, "gop": gop, "old": old_fps, "gap_ms": gap, "real_fps": round(real, 1), "wrap": w,
            "call_ms": round(t_call * 1000)}


def op_set_gop(req):
    gop = int(req["gop"])
    if not 1 <= gop <= GOP_MAX:
        raise ValueError("GOP %d mimo 1-%d" % (gop, GOP_MAX))
    if smooth["on"]:
        raise RuntimeError("je zapnuty plynuly obraz (GOP ridi sam) - nejdriv ho vypni")
    old = rk_get_int("rk_video_get_gop")
    rk_set_int("rk_video_set_gop", gop)
    if not check_video(gop=gop):
        rk_set_int("rk_video_set_gop", old)
        raise RuntimeError("enkoder zmenu neprijal")
    log("GOP %d -> %d" % (old, gop))
    return {"gop": gop, "old": old}


def op_set_resolution(req):
    res = str(req["res"]).replace("x", "*").replace("X", "*").replace("×", "*")
    if res not in RESOLUTIONS:
        raise ValueError("rozliseni %s neni v %s" % (res, ", ".join(RESOLUTIONS)))
    w, h = (int(x) for x in res.split("*"))
    mw, mh = rezim_cap()["max"]
    if w > mw or h > mh:
        raise ValueError("rozliseni %s jde jen v rezimu snimace 30 fps (v okne zvol rozliseni + fps, deska se prepne)" % res)
    old = rk_get_str("rk_video_get_resolution")
    t0 = time.monotonic()
    rk_set_str("rk_video_set_resolution", res)
    t_call = time.monotonic() - t0
    gap, trail = max_gap(2.0, t0)
    if not check_video(width=w, height=h, wait=1.0) or not flowing(trail):
        rk_set_str("rk_video_set_resolution", old)
        raise RuntimeError("enkoder rozliseni neprijal nebo prestal kodovat, vraceno na %s" % old)
    real = real_fps(1.0)
    log("rozliseni %s -> %s (volani %d ms, nejdelsi mezera snimku %d ms, skutecne %s fps, wrap %s)" % (
        old, res, t_call * 1000, gap, "?" if real is None else "%.1f" % real, wrap_on()))
    return {"res": res, "old": old, "call_ms": round(t_call * 1000), "gap_ms": gap,
            "real_fps": None if real is None else round(real, 1)}


def op_set_power(req):
    ch, _, cur = iw_info()
    cap = band_cap(ch)
    idx = int(req["idx"])
    if not 1 <= idx <= cap:
        raise ValueError("index %d mimo 1-%d (kanal %d)" % (idx, cap, ch))
    t0 = time.monotonic()
    set_power(idx)
    ms = round((time.monotonic() - t0) * 1000)
    _, _, now = iw_info()
    if now != idx:
        raise RuntimeError("karta hlasi index %s" % now)
    log("vykon index %s -> %d (%d ms)" % (cur, idx, ms))
    return {"idx": idx, "old": cur, "max": cap, "ms": ms}


# ---------- kanal: dvoufazove prepnuti ----------
sw = None   # rozpracovane prepnuti


def op_ch_prepare(req, addr):
    global sw
    tok = str(req["tok"])
    if sw and sw["tok"] == tok:
        return {"tok": tok, "phase": sw["phase"], "in_ms": max(0, round((sw["t_switch"] - time.monotonic()) * 1000))}
    if sw:
        raise RuntimeError("prave probiha jine prepnuti kanalu (%s)" % sw["phase"])
    to = int(req["to"])
    frm = int(req["from"])
    cur, _, _ = iw_info()
    if to not in CH_ALLOWED:
        raise ValueError("kanal %d neni povoleny (%s)" % (to, CH_ALLOWED))
    if frm != cur:
        raise ValueError("deska je na kanalu %s, ne %d" % (cur, frm))
    in_ms = min(max(int(req.get("in_ms", 1500)), 300), 5000)
    sw = {"tok": tok, "from": frm, "to": to, "phase": "prepared",
          "t_switch": time.monotonic() + in_ms / 1000.0,
          "confirm_s": min(max(int(req.get("confirm_ms", 4000)), 1000), 15000) / 1000.0,
          "commit_s": min(max(int(req.get("commit_ms", 3000)), 1000), 15000) / 1000.0}
    log("pripraveno prepnuti %d -> %d za %d ms" % (frm, to, in_ms))
    return {"tok": tok, "phase": "prepared", "in_ms": in_ms}


def op_ch_abort(req, addr):
    global sw
    if not sw or sw["tok"] != str(req["tok"]):
        return {"aborted": False, "ch": iw_info()[0]}
    if sw["phase"] == "prepared":
        log("prepnuti zruseno pred provedenim")
        sw = None
        return {"aborted": True, "ch": iw_info()[0]}
    start_revert("zruseno laptopem")
    return {"aborted": True, "reverting": True, "ch": iw_info()[0]}


def op_ch_confirm(req, addr):
    if addr[0] != TUN_PEER:
        raise RuntimeError("potvrzeni kanalu jen vzduchem (tunel)")
    if not sw or sw["tok"] != str(req["tok"]) or sw["phase"] not in ("switched", "confirmed"):
        raise RuntimeError("zadne provedene prepnuti s timto tokenem")
    if sw["phase"] == "switched":
        sw["phase"] = "confirmed"
        log("laptop potvrdil spojeni na kanalu %d" % sw["to"])
    sw["deadline"] = time.monotonic() + sw["commit_s"]   # kazde potvrzeni prodlouzi lhutu pro commit
    return {"tok": sw["tok"], "phase": "confirmed", "ch": iw_info()[0], "switch_ms": sw.get("switch_ms"),
            "commit_left_ms": round(sw["commit_s"] * 1000)}


def op_ch_commit(req, addr):
    global sw
    tok = str(req["tok"])
    to = int(req.get("to", -1))
    if not sw:
        # opakovany commit (odpoved se ztratila, nebo restart demona): ulozeny kanal = to -> hotovo
        c = read_conf()
        if conf_int(c, "WFB_CHANNEL", -1) == to and c.get("WFB_CHANNEL_TOK") == tok:
            return {"committed": True, "ch": to}
        raise RuntimeError("prepnuti neni potvrzene")
    if addr[0] != TUN_PEER:
        raise RuntimeError("potvrzeni kanalu jen vzduchem (tunel)")
    if sw["tok"] != tok or sw["phase"] != "confirmed":
        raise RuntimeError("prepnuti neni potvrzene")
    write_conf_key("WFB_CHANNEL_TOK", tok)
    write_conf_key("WFB_CHANNEL", sw["to"])
    log("kanal %d ulozen do %s" % (sw["to"], CONF))
    ch = sw["to"]
    sw = None
    return {"committed": True, "ch": ch}


def start_revert(why):
    if not sw:
        return
    sw["phase"] = "reverting"
    sw["why"] = why
    sw["tries"] = 0
    sw["next_try"] = 0.0


def do_revert():
    """Navrat na puvodni kanal; pri chybe se opakuje kazdou sekundu, nakonec restart wfb_tx (setup_if)."""
    global sw
    sw["tries"] += 1
    try:
        switch_channel(sw["from"])
        log("NAVRAT na kanal %d (%s)" % (sw["from"], sw["why"]))
        sw = None
    except Exception as e:  # noqa: BLE001
        log("CHYBA navratu na kanal %d (pokus %d): %s" % (sw["from"], sw["tries"], e))
        sw["next_try"] = time.monotonic() + 1.0
        if sw["tries"] >= 10:
            log("navrat se nedari - restartuji video wfb_tx, vima-wfb nastavi kanal z vima.conf")
            subprocess.run(["pkill", "-f", "[w]fb_tx .* -p 0 "], timeout=5)
            sw = None


last_watch = [0.0]


def watchdog():
    """Bez rozpracovaneho prepnuti: kanal musi odpovidat vima.conf a vykon zakonnemu stropu."""
    if sw or time.monotonic() - last_watch[0] < 2.0:
        return
    last_watch[0] = time.monotonic()
    try:
        ch, _, idx = iw_info()
        c = read_conf()
        want = conf_int(c, "WFB_CHANNEL", ch)
        if ch and want in CH_ALLOWED and ch != want:
            log("kanal karty %s neodpovida vima.conf (%s) - vracim" % (ch, want))
            switch_channel(want)
            return
        if ch and idx is not None and not 1 <= idx <= band_cap(ch, c):
            log("vykon index %s mimo 1-%d pro kanal %d - opravuji" % (idx, band_cap(ch, c), ch))
            set_power(band_cap(ch, c))
    except Exception as e:  # noqa: BLE001
        log("hlidac: %s" % e)


def timers():
    try:
        fps_mer_tick()
    except Exception:  # noqa: BLE001
        pass
    if not sw:
        watchdog()
        smooth_tick()
        alink_tick()
        return
    now = time.monotonic()
    if sw["phase"] == "prepared" and now >= sw["t_switch"]:
        try:
            sw["switch_ms"] = switch_channel(sw["to"])
            sw["phase"] = "switched"
            sw["deadline"] = time.monotonic() + sw["confirm_s"]
        except Exception as e:  # noqa: BLE001
            log("CHYBA prepnuti: %s" % e)
            start_revert("chyba prepnuti")
    elif sw["phase"] == "switched" and now > sw["deadline"]:
        start_revert("laptop nepotvrdil spojeni na novem kanalu")
    elif sw["phase"] == "confirmed" and now > sw["deadline"]:
        start_revert("neprislo ulozeni (commit)")
    if sw and sw["phase"] == "reverting" and now >= sw["next_try"]:
        do_revert()


# ---------- krok 3: klicovy snimek na zadost, plynuly obraz ----------
# Klicovy snimek je velky (~35 kB pri 720p, vzduchem 100-190 ms), pri GOP 30 chodi kazdou
# sekundu a je videt jako kratke trhnuti. Plynuly obraz: dlouhy GOP a klicovy snimek jen na
# zadost prijimace po ztrate paketu. Bezpecne jen kdyz prijimac zadat umi: prijem.py posila
# 1x za sekundu "rx_alive"; kdyz ALIVE_S nic neprijde (vypadek tunelu, zavrene okno), vrati se
# GOP na fps a obraz se po ztrate srovna sam s dalsim pravidelnym klicovym snimkem.
# (Postupne obnovovani - intra refresh - MPP v tomto SDK neumi, viz rkipc video.c.)
GOP_MAX = 500           # vic enkoder neumi (venc_info ukaze 500)
SMOOTH_GOP = 500        # 16,7 s pri 30 fps
ALIVE_S = 3.0
KF_MIN_S = 0.1          # zadosti castejsi nez 10x/s se zahodi (kazdy klicovy snimek je velky)
kf = {"n": 0, "limited": 0, "err": 0}
kf_last = [0.0]
smooth = {"on": read_conf().get("VIDEO_SMOOTH", "0") == "1", "alive": -1e9, "next": 0.0, "gop": None}


def smooth_active():
    return smooth["on"] and time.monotonic() - smooth["alive"] < ALIVE_S


def smooth_state():
    ago = time.monotonic() - smooth["alive"]
    return {"on": smooth["on"], "active": smooth_active(), "rx_alive_ms": round(ago * 1000) if ago < 1e6 else None}


def smooth_tick(force=False):
    """Plynuly obraz zapnuty: GOP = SMOOTH_GOP dokud prijimac zije, jinak GOP = fps."""
    now = time.monotonic()
    if not force and (not smooth["on"] and smooth["gop"] is None or now < smooth["next"]):
        return
    smooth["next"] = now + 1.0
    try:
        fps = int(float(rk_get_str("rk_video_get_frame_rate")))
        gop = rk_get_int("rk_video_get_gop")
    except Exception:  # noqa: BLE001  rkipc jeste nebezi
        return
    if smooth["on"]:
        want = SMOOTH_GOP if smooth_active() else fps
    else:
        want = fps if smooth["gop"] is not None else gop   # po vypnuti jednou zpet na fps
    if gop != want:
        rk_set_int("rk_video_set_gop", want)
        log("plynuly obraz: GOP %d -> %d (%s)" % (gop, want, "prijimac zada o klicove snimky" if want == SMOOTH_GOP
                                                 else "prijimac se neozval %.0f s" % ALIVE_S if smooth["on"] else "vypnuto"))
    smooth["gop"] = want if smooth["on"] else None


def op_rx_alive(req):
    was = smooth_active()
    smooth["alive"] = time.monotonic()
    if smooth["on"] and not was:
        smooth_tick(force=True)
    return {"smooth": smooth["on"]}


def op_set_smooth(req):
    on = bool(req["on"])
    write_conf_key("VIDEO_SMOOTH", "1" if on else "0")
    if on and not smooth["on"]:
        smooth["alive"] = -1e9   # dlouhy GOP az po dalsim rx_alive
    smooth["on"] = on
    if not on:
        smooth["gop"] = 0
    smooth_tick(force=True)
    log("plynuly obraz %s" % ("zapnut" if on else "vypnut"))
    return {"on": on, **smooth_state()}


def op_keyframe(req):
    now = time.monotonic()
    kf_min = KF_MIN_S
    if alink["on"] and alink["p"] is not None:   # pri pomalem MCS jde klicovy snimek vzduchem stovky ms -
        kf_min = max(KF_MIN_S, PROFILY[alink["p"]]["kf_min_s"])   # dalsi zadost by spoj jen zahltila
    if now - kf_last[0] < kf_min:
        kf["limited"] += 1
        return {"sent": False, "ago_ms": round((now - kf_last[0]) * 1000)}
    kf_last[0] = now
    err = rk("rk_video_request_idr", struct.pack("<i", 0), timeout=0.5)[0]
    if err:
        kf["err"] += 1
        raise RuntimeError("enkoder odmitl klicovy snimek (%#x)" % (err & 0xffffffff))
    kf["n"] += 1
    return {"sent": True, "seq": venc_seq()}


# ---------- krok 4: adaptivni spoj ----------
# Laptop (prijem.py) posila 5x za sekundu "rx_report": pakety videa, opravene FEC, neopravitelne
# ztraty, SNR (wfb_rx -l 200) a ztraty obrazu. Deska podle nej vybira profil = MCS videa + strop toku.
# Dolu rychle (ztrata, hodne oprav FEC, nizke SNR), nahoru pomalu (UP_S s bez problemu a SNR
# s rezervou HYST_DB). Po kazde zmene SETTLE_S nerozhodovat (statistiky by michaly stare a nove MCS).
# Bez zprav ALINK_TIMEOUT_S -> nejodolnejsi profil (MCS 0). Inspirace: OpenIPC adaptive-link.
# MCS 5-7 (64-QAM) zamerne ne: s pevnym indexem vykonu (bez snizeni pro 64-QAM) hrozi zkresleni.
# Kapacita z mereni 26. 10. (FEC 8/16, kdy se jeste netvori fronta): MCS 0 ~2,1, MCS 1 ~3,3,
# MCS 2 ~6,3, MCS 3 ~6,5-8, MCS 4 ~9,7 Mbit/s (vys uz brzdi procesor desky). Strop toku profilu je
# ~40-55 % kapacity: klicovy snimek 2304x1296 ma az 90 kB a pri MCS 0 jde vzduchem pres 300 ms
# (srovnani 26. 10.: s 60 % se spoj na hranici dosahu zahltil). Vyssi MCS = kratsi cas ve vzduchu
# = mensi zpozdeni a mene ztrat z ruseni (srovnani 26. 10.: MCS 3-4 o 60 % mene zadrhu nez MCS 1).
# Tok nikdy neprekroci tok nastaveny uzivatelem (user_kbps). Vykon se nemeni.
PROFILY = [
    {"mcs": 0, "kbps": 800, "snr": 0, "kf_min_s": 0.8},
    {"mcs": 1, "kbps": 1600, "snr": 8, "kf_min_s": 0.4},
    {"mcs": 2, "kbps": 2800, "snr": 11, "kf_min_s": 0.1},
    {"mcs": 3, "kbps": 3800, "snr": 14, "kf_min_s": 0.1},
    {"mcs": 4, "kbps": 5500, "snr": 18, "kf_min_s": 0.1},
]
ALINK_START = 1          # po zapnuti (= puvodni pevne nastaveni MCS 1)
ALINK_SAFE = 0           # laptop se neozyva
HYST_DB = 3
UP_S = 3.0
UP_BLOCK_S = 6.0
UP_BLOCK_MAX_S = 30.0
FAILED_PROBE_S = 10.0    # pad do 10 s po kroku nahoru = nepovedeny pokus -> pristi pokus az za dvojnasobek
FEC_DOWN_PCT = 15.0      # opraveno FEC nad 15 % paketu (FEC 8/16 unese 50 %) -> dolu
FEC_UP_PCT = 8.0
WIN_S = 1.0              # FEC a SNR se hodnoti z hlaseni za posledni ~1 s, ne z jednoho 200ms vzorku;
WIN_MAX_S = 3.0          # pri malem toku (MCS 0) se okno natahne, dokud nema WIN_MIN_PKT paketu
WIN_MIN_PKT = 150
SETTLE_S = 0.6
LOSS_MARGIN_DB = 4       # ztraty pri SNR >= prah profilu + 4 dB jsou ruseni, ne slaby signal: nizsi MCS
LOSS_EVENTS = 3          # nepomuze (vysila dele) -> dolu az kdyz se ztraty opakuji (3 hlaseni za 3 s)
ALINK_TIMEOUT_S = 1.5    # (nejmene 2,5 intervalu hlaseni)
RESYNC_S = 1.0           # kontrola, ze karta a enkoder opravdu maji MCS a tok profilu (restart wfb_tx apod.)
USER_KBPS_FILE = "/var/run/vima-user-kbps"   # tok nastaveny uzivatelem, plati do restartu desky
alink = {"on": read_conf().get("ALINK", "0") == "1", "p": None, "user_kbps": None, "last_rep": -1e9, "rep_dt": 0.2,
         "settle_until": 0.0, "good_since": None, "block_until": 0.0, "block_s": UP_BLOCK_S, "last_down": -1e9,
         "last_up": -1e9, "why": "", "rep": None, "win": [], "zero": 0, "retry_at": 0.0, "fail_logged": False,
         "next_resync": 0.0, "n_up": 0, "n_down": 0, "n_safe": 0}


def user_kbps():
    """Tok od uzivatele = strop pro vsechny profily. Po restartu vima-ctl ze souboru (enkoder uz muze mit
    tok snizeny adaptivnim spojem), po startu desky z enkoderu (adaptivni spoj ho jeste nemenil)."""
    if alink["user_kbps"] is None:
        try:
            alink["user_kbps"] = int(open(USER_KBPS_FILE).read().strip())
        except (OSError, ValueError):
            user_kbps_save(rk_get_int("rk_video_get_max_rate") or 2048)
    return alink["user_kbps"]


def user_kbps_save(k):
    alink["user_kbps"] = int(k)
    try:
        with open(USER_KBPS_FILE + ".tmp", "w") as f:
            f.write("%d\n" % int(k))
        os.rename(USER_KBPS_FILE + ".tmp", USER_KBPS_FILE)
    except OSError:
        pass


def alink_kbps(i=None):
    prof = PROFILY[alink["p"] if i is None else i]
    return min(prof["kbps"], user_kbps())


def alink_state():
    """Bez I/O (vola se i behem prepinani kanalu)."""
    p = alink["p"]
    u = alink["user_kbps"]
    return {"on": alink["on"], "p": p, "mcs": PROFILY[p]["mcs"] if p is not None else None,
            "kbps": min(PROFILY[p]["kbps"], u or PROFILY[p]["kbps"]) if p is not None else None, "user_kbps": u,
            "why": alink["why"], "rep": alink["rep"], "n_up": alink["n_up"], "n_down": alink["n_down"],
            "n_safe": alink["n_safe"],
            "rep_ago_ms": round((time.monotonic() - alink["last_rep"]) * 1000) if alink["last_rep"] > 0 else None}


def wfb_set_mcs(mcs):
    rc, rad = wfb_cmd(VIDEO_CTL, 4, resp_len=7)      # GET_RADIO: stbc, ldpc, short_gi, bw, mcs, vht, nss
    if rc or len(rad) < 7:
        raise RuntimeError("wfb_tx neodpovida (get_radio)")
    r = bytearray(rad)
    r[4] = mcs
    rc, _ = wfb_cmd(VIDEO_CTL, 2, bytes(r))          # SET_RADIO, platne od dalsiho paketu
    if rc:
        raise RuntimeError("wfb_tx odmitl MCS %d (%d)" % (mcs, rc))


def alink_apply(i, why):
    """Dolu: nejdriv tok, pak MCS (aby se pomalejsi spoj nezahltil). Nahoru: nejdriv MCS, tok az kdyz
    rychlejsi MCS plati. Tok a MCS kazdy zvlast - kdyz jedno selze, druhe se stejne zkusi.
    Profil se zmeni, jen kdyz se nastavilo MCS; chyba se nakonec vyhodi (zaloguje volajici)."""
    old = alink["p"]
    kbps = alink_kbps(i)
    err = []

    def rate():
        try:
            rk_set_int("rk_video_set_max_rate", kbps)
        except Exception as e:  # noqa: BLE001
            err.append("tok: %s" % e)

    def mcs():
        try:
            wfb_set_mcs(PROFILY[i]["mcs"])
            return True
        except Exception as e:  # noqa: BLE001
            err.append("MCS: %s" % e)
            return False

    if old is None or i <= old:
        rate()
        ok = mcs()
    else:
        ok = mcs()
        if ok:
            rate()
    if ok:
        alink["p"] = i
        alink["why"] = why
        alink["settle_until"] = time.monotonic() + SETTLE_S
        alink["win"] = []
        log("adaptivni spoj: %s -> profil %d (MCS %d, %d kbit/s): %s" % (
            "start" if old is None else "profil %d" % old, i, PROFILY[i]["mcs"], kbps, why))
    if err:
        raise RuntimeError("; ".join(err))
    return ok


def alink_stall(dur):
    """Smycka stala dur s (dlouhy prikaz): hlaseni cekala ve fronte, nejde o vypadek laptopu."""
    if alink["last_rep"] > 0:
        alink["last_rep"] += dur
    if smooth["alive"] > 0:
        smooth["alive"] += dur
    alink["settle_until"] = max(alink["settle_until"], time.monotonic() + 1.0)   # i mezera enkoderu


def op_rx_report(req):
    now = time.monotonic()
    if req.get("zadost", True):
        op_rx_alive(req)      # plynuly obraz jen kdyz prijimac umi zadat o klicovy snimek
    pkt = int(req.get("pkt") or 0)
    fec, lost, img = int(req.get("fec") or 0), int(req.get("lost") or 0), int(req.get("img_loss") or 0)
    snr = req.get("snr")
    try:
        alink["rep_dt"] = min(2.0, max(0.1, float(req.get("dt") or 0.2)))
    except (TypeError, ValueError):
        pass
    alink["last_rep"] = now
    alink["rep"] = {"pkt": pkt, "fec_pct": round(100.0 * fec / pkt, 1) if pkt else 0.0, "lost": lost, "img_loss": img,
                    "snr": snr, "rssi": req.get("rssi"), "kbps": req.get("kbps")}
    alink["win"].append((now, pkt, fec, snr if isinstance(snr, (int, float)) else None, 1 if (lost or img) else 0))
    alink["win"] = [w for w in alink["win"] if now - w[0] <= WIN_MAX_S]
    alink["zero"] = alink["zero"] + 1 if pkt == 0 else 0
    if not alink["on"]:
        return {"alink": False}
    if sw:   # prepinani kanalu: hlaseni michaji stary a novy kanal
        alink["good_since"] = None
        alink["win"] = []
        alink["settle_until"] = now + SETTLE_S + 1.0
        return {"alink": True, "p": alink["p"]}
    if alink["p"] is None:
        alink_apply(ALINK_START, "zapnuto, start od MCS 1")
        alink["good_since"] = now
        return {"alink": True, "p": alink["p"]}
    if now < alink["settle_until"]:
        return {"alink": True, "p": alink["p"]}
    p = alink["p"]
    sel, wp = [], 0
    for w in reversed(alink["win"]):      # od nejnovejsiho: aspon WIN_S a WIN_MIN_PKT paketu
        sel.append(w)
        wp += w[1]
        if now - w[0] >= WIN_S - 0.05 and wp >= WIN_MIN_PKT:
            break
    fec_pct = 100.0 * sum(w[2] for w in sel) / wp if wp >= WIN_MIN_PKT / 3 else None
    snrs = [w[3] for w in sel if w[3] is not None]
    snr_avg = sum(snrs) / len(snrs) if snrs else None
    snr_min = min(snrs) if snrs else None
    loss_events = sum(w[4] for w in alink["win"])       # hlaseni se ztratou za poslednich WIN_MAX_S
    strong = snr_avg is not None and snr_avg >= PROFILY[p]["snr"] + LOSS_MARGIN_DB
    bad = None
    if (lost or img) and (not strong or loss_events >= LOSS_EVENTS):
        bad = "ztraty (pakety %d, obraz %d%s)" % (lost, img, ", opakovane" if strong else "")
    elif alink["zero"] >= 2:
        bad = "z videa nedoslo nic (%d hlaseni)" % alink["zero"]
    elif fec_pct is not None and fec_pct > FEC_DOWN_PCT:
        bad = "FEC opravil %.0f %% paketu" % fec_pct
    elif snr_avg is not None and snr_avg < PROFILY[p]["snr"]:
        bad = "SNR %.0f dB < %d" % (snr_avg, PROFILY[p]["snr"])
    if bad:
        alink["good_since"] = None
        if p > 0 and now - alink["last_down"] >= 1.0:
            step = 2 if (alink["zero"] >= 2 or lost > 10 or img > 2) else 1
            if alink["last_up"] > alink["last_down"]:      # prvni pad od posledniho kroku nahoru
                if now - alink["last_up"] < FAILED_PROBE_S:
                    alink["block_s"] = min(UP_BLOCK_MAX_S, alink["block_s"] * 2)   # nepovedeny pokus
                else:
                    alink["block_s"] = UP_BLOCK_S                                 # profil dlouho drzel
            alink["block_until"] = now + alink["block_s"]
            alink["last_down"] = now
            alink["n_down"] += 1
            alink_apply(max(0, p - step), bad)
        return {"alink": True, "p": alink["p"]}
    if alink["good_since"] is None:
        alink["good_since"] = now
    nxt = p + 1
    if (nxt < len(PROFILY) and now >= alink["block_until"] and now - alink["good_since"] >= UP_S
            and loss_events == 0 and fec_pct is not None and fec_pct < FEC_UP_PCT
            and snr_min is not None and snr_min >= PROFILY[nxt]["snr"] + HYST_DB):
        alink["n_up"] += 1
        alink["last_up"] = now
        alink_apply(nxt, "%.0f s bez problemu, SNR %d dB, FEC %.1f %%" % (now - alink["good_since"], snr_min, fec_pct))
        alink["good_since"] = now
    return {"alink": True, "p": alink["p"]}


def alink_tick():
    if not alink["on"] or sw:
        return
    now = time.monotonic()
    if now < alink["retry_at"]:
        return
    try:
        timeout = max(ALINK_TIMEOUT_S, 2.5 * alink["rep_dt"])
        if now - alink["last_rep"] > timeout:     # i hned po startu (last_rep -1e9), kdy p je None
            alink["good_since"] = None
            alink["win"] = []
            if alink["p"] != ALINK_SAFE:
                if alink_apply(ALINK_SAFE, "laptop se neozval %.1f s - nejodolnejsi profil" % timeout):
                    alink["n_safe"] += 1
        if alink["p"] is not None and now >= alink["next_resync"]:
            alink["next_resync"] = now + RESYNC_S
            r = wfb_get(VIDEO_CTL)
            want = PROFILY[alink["p"]]["mcs"]
            if r and r["mcs"] != want:
                alink_apply(alink["p"], "karta mela MCS %d misto %d (restart wfb_tx?) - znovu nastaveno" % (r["mcs"], want))
            elif rk_get_int("rk_video_get_max_rate") != alink_kbps():
                rk_set_int("rk_video_set_max_rate", alink_kbps())
        alink["fail_logged"] = False
    except Exception as e:  # noqa: BLE001
        alink["retry_at"] = now + 1.0
        if not alink["fail_logged"]:
            log("adaptivni spoj: nastaveni se nepodarilo (%s), zkousim kazdou sekundu" % e)
            alink["fail_logged"] = True


def op_set_alink(req):
    on = bool(req["on"])
    write_conf_key("ALINK", "1" if on else "0")
    was = alink["on"]
    alink["on"] = on
    errs = []
    if on and not was:
        alink.update(p=None, block_s=UP_BLOCK_S, block_until=0.0, good_since=None, win=[], zero=0, retry_at=0.0,
                     last_rep=time.monotonic())   # prvni hlaseni zacne od MCS 1, bez hlaseni -> MCS 0
    if not on and was:
        alink["p"] = None
        try:   # pevne nastaveni: tok jak ho nastavil uzivatel, MCS z vima.conf
            rk_set_int("rk_video_set_max_rate", user_kbps())
        except Exception as e:  # noqa: BLE001
            errs.append("tok: %s" % e)
        try:
            wfb_set_mcs(conf_int(read_conf(), "WFB_MCS", 1))
        except Exception as e:  # noqa: BLE001
            errs.append("MCS: %s" % e)
    log("adaptivni spoj %s%s" % ("zapnut" if on else "vypnut", (" - navrat se nepodaril: " + "; ".join(errs)) if errs else ""))
    if errs:
        raise RuntimeError("adaptivni spoj vypnut, ale navrat se nepodaril (%s) - zkus to znovu" % "; ".join(errs))
    return alink_state()


OPS = {
    "status": lambda r, a: status(),
    "keyframe": lambda r, a: op_keyframe(r),
    "rx_alive": lambda r, a: op_rx_alive(r),
    "rx_report": lambda r, a: op_rx_report(r),
    "set_alink": lambda r, a: op_set_alink(r),
    "set_smooth": lambda r, a: op_set_smooth(r),
    "set_bitrate": lambda r, a: op_set_bitrate(r),
    "set_fps": lambda r, a: op_set_fps(r),
    "set_gop": lambda r, a: op_set_gop(r),
    "set_resolution": lambda r, a: op_set_resolution(r),
    "set_mode": lambda r, a: op_set_mode(r),
    "set_power": lambda r, a: op_set_power(r),
    "ch_prepare": op_ch_prepare,
    "ch_abort": op_ch_abort,
    "ch_confirm": op_ch_confirm,
    "ch_commit": op_ch_commit,
}
BUSY_OK = ("status", "keyframe", "rx_alive", "rx_report", "ch_prepare", "ch_abort", "ch_confirm", "ch_commit")
NO_CACHE = ("status", "keyframe", "rx_alive", "rx_report", "ch_prepare", "ch_abort", "ch_confirm", "ch_commit")   # idempotentni samy o sobe


def handle(req, addr):
    try:
        op = req.get("op")
        if op not in OPS:
            raise ValueError("neznamy prikaz %r" % op)
        if sw and op not in BUSY_OK:
            raise RuntimeError("probiha prepnuti kanalu, zkus to za chvili")
        return {"id": req.get("id"), "ok": True, "res": OPS[op](req, addr)}
    except Exception as e:  # noqa: BLE001
        return {"id": req.get("id"), "ok": False, "err": str(e)}


# Odpoved musi odejit ze stejne adresy, na kterou prisel dotaz: eth0 ma i adresu z DHCP
# (10.42.0.x vedle 10.42.0.2) a odpoved z ni by firewall laptopu zahodil. IP_PKTINFO = 8.
IP_PKTINFO = getattr(socket, "IP_PKTINFO", 8)


def recv_req(s):
    data, anc, _, addr = s.recvmsg(2048, socket.CMSG_SPACE(12))
    dst = None
    for lvl, typ, val in anc:
        if lvl == socket.IPPROTO_IP and typ == IP_PKTINFO and len(val) >= 12:
            dst = val[8:12]   # in_pktinfo.ipi_addr = cilova adresa dotazu
    return data, addr, dst


def send_resp(s, data, addr, dst):
    if dst is None:
        s.sendto(data, addr)
    else:
        s.sendmsg([data], [(socket.IPPROTO_IP, IP_PKTINFO, struct.pack("<i", 0) + dst + bytes(4))], 0, addr)


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.IPPROTO_IP, IP_PKTINFO, 1)
    s.bind(("0.0.0.0", PORT))
    log("posloucham na UDP %d (karta %s, rizeni wfb_tx video %d / tunel %d)" % (PORT, IF, VIDEO_CTL, TUN_CTL))
    last_watch[0] = 0.0
    watchdog()   # po (re)startu demona: karta zpet na ulozeny kanal (rozpracovane prepnuti se ztratilo)
    cache = {}   # (addr, id) -> odpoved, opakovany dotaz se neprovede znovu
    while True:
        try:
            r, _, _ = select.select([s], [], [], 0.05)
            timers()
            if not r:
                continue
            data, addr, dst = recv_req(s)
            if addr[0] not in ALLOWED_SRC:
                continue
            try:
                req = json.loads(data.decode())
                if not isinstance(req, dict):
                    raise ValueError
            except ValueError:
                continue
            rid = req.get("id")
            if not isinstance(rid, int):
                rid = None
                req["id"] = None
            key = (addr, rid)
            if rid is not None and req.get("op") not in NO_CACHE and key in cache:
                resp = cache[key]
            else:
                t_h = time.monotonic()
                resp = handle(req, addr)
                if time.monotonic() - t_h > 0.3:
                    alink_stall(time.monotonic() - t_h)
                if rid is not None and req.get("op") not in NO_CACHE:
                    cache[key] = resp
                    if len(cache) > 200:
                        cache.pop(next(iter(cache)))
            try:
                send_resp(s, json.dumps(resp).encode(), addr, dst)
            except OSError as e:   # napr. EPERM z omezeni toku tunelu - jako ztraceny paket, laptop zopakuje
                log("odpoved neodesla: %s" % e)
            timers()
        except Exception as e:  # noqa: BLE001  smycka nesmi spadnout (prepnuti by zustalo bez navratu)
            log("chyba ve smycce: %s" % e)
            time.sleep(0.1)


if __name__ == "__main__":
    main()
