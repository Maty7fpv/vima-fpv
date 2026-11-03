#!/usr/bin/python3
# Vima: okno s videem z desky (UDP 5600 z wfb_rx) a zaznam casu kazdeho dekodovaneho snimku.
# Stejna cesta jako drive gst-launch v gs-video.sh (bez bufferu: sync=false), navic:
#   ~/vima-board/snimky.log   - "cas_ms sirka vyska" pro kazdy snimek (mereni vypadku obrazu)
#   ~/vima-board/udalosti.log - ztraty paketu, zadosti o klicovy snimek a jeho prichod (krok 3)
# Krok 3: pri ztrate, kterou FEC nezachranil (mezera v cislech RTP paketu), pozada desku pres
# tunel o klicovy snimek (vima-ctl.py, UDP 10.5.0.2:5900) - obraz se srovna hned, ne az
# s dalsim pravidelnym klicovym snimkem. Kdyz klicovy snimek neprijde do 250 ms, pozada znovu.
# Zaroven posila "rx_report" (krok 4) s kazdym intervalem statistik wfb_rx (gs-video.sh -l 200 =
# 5x za sekundu): signal, SNR, pakety opravene FEC, neopravitelne ztraty a ztraty obrazu. Deska podle
# nej meni MCS a tok (adaptivni spoj, posila se i pri ZADOST_KF=0) a pri ZADOST_KF=1 si smi dovolit
# plynuly obraz (dlouhy GOP). Kdyz hlaseni chybi, deska prejde na nejodolnejsi nastaveni.
# Bez statistik wfb_rx se posila aspon "rx_alive".
# Nastaveni ~/vima-board/prijem.conf (cte se za behu):
#   ZADOST_KF=1   zadat o klicovy snimek a posilat rx_alive (0 = nezadat)
#   MERENI=0      1 = ukladat do mereni-kf/ zmensene snimky, prichody snimku (cas, RTP cas, velikost)
#                 a casy dekodovani (jen pri startu okna)
#   PAUZA=0       1 = mereni kapacity spoje (krok 4): pakety se nezobrazuji, jen se zapisuji
#                 (poradi, cas odeslani z testovacich dat desky) do mereni-kf/kapacita-*.log
#   OKNO=wayland  obraz primo pres Wayland (waylandsink) - bez XWayland, nizsi zpozdeni (3. 11.);
#                 OKNO=x11 = puvodni okno (xvimagesink pres XWayland). Plati pri dalsim otevreni okna.
#   CELA_OBRAZOVKA=1  okno pres celou obrazovku (jen OKNO=wayland, meni se za behu): GNOME pak muze
#                 obnovovat displej v rytmu videa (promenna frekvence) a nema co skladat.
#                 Okno bez ramecku: zavrit Ctrl+C v terminalu s gs-video.sh (nebo CELA_OBRAZOVKA=0 a Alt+F4).
# SIGHUP = okno se zavre a gs-video.sh ho hned otevre znovu (navratovy kod 3).
# Pouziti: python3 prijem.py   (okno zavrit nebo Ctrl+C = konec)
import json
import os
import signal
import socket
import struct
import sys
import threading
import time

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo, GLib  # noqa: E402

D = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(D, "snimky.log")
EVLOG = os.path.join(D, "udalosti.log")
WFBLOG = os.path.join(D, "gs-video.log")     # statistiky wfb_rx (gs-video.sh)
CONF = os.path.join(D, "prijem.conf")
MAXLOG = 20 * 1024 * 1024
DESKA = ("10.5.0.2", 5900)   # vima-ctl.py na desce, pres tunel
ODSTUP_S = 0.3               # nejvyse 1 zadost za 300 ms (klicovy snimek je velky)
OPAKUJ_S = 0.25              # klicovy snimek neprisel -> zadat znovu
RYCHLE = 3                   # prvni 3 pokusy po 250 ms, dalsi 1x za sekundu
ALIVE_S = 1.0                # "rx_alive" pro desku
IDR = (19, 20)               # H.265 IDR_W_RADL, IDR_N_LP

def conf_soubor():
    """prijem.conf pri startu (pred sestavenim pipeline); za behu ho cte read_conf()."""
    c = {}
    try:
        for ln in open(os.path.join(D, "prijem.conf")):
            ln = ln.split("#", 1)[0].strip()
            if "=" in ln:
                k, v = ln.split("=", 1)
                c[k.strip()] = v.strip()
    except OSError:
        pass
    return c


Gst.init(None)
_c0 = conf_soubor()
pipe = Gst.parse_launch(
    'udpsrc name=src port=5600 buffer-size=1048576 caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H265" '
    '! rtph265depay ! h265parse ! avdec_h265 name=dec max-threads=1 ! videoconvert '
    '! fpsdisplaysink name=fps sync=false text-overlay=true')
# max-threads=1: pojistka - u ziveho udpsrc libav stejne pouziva jen vlakna po radcich (0 snimku zpozdeni),
# u neziveho zdroje by vlakna po snimcich pridala az ~15 snimku.
vsink = None
if _c0.get("OKNO", "wayland") == "wayland" and os.environ.get("WAYLAND_DISPLAY"):
    vsink = Gst.ElementFactory.make("waylandsink", "vsink")
    if vsink is not None:
        vsink.set_property("fullscreen", _c0.get("CELA_OBRAZOVKA", "1") == "1")
        pipe.get_by_name("fps").set_property("video-sink", vsink)
cela_obrazovka = [None if vsink is None else _c0.get("CELA_OBRAZOVKA", "1") == "1"]
out = open(LOG, "w", buffering=1)
ev_out = open(EVLOG, "a", buffering=1)
size = [None]
restart = [False]

conf = {"ZADOST_KF": "1", "MERENI": "0"}
conf_mtime = [None]


def read_conf():
    try:
        mt = os.stat(CONF).st_mtime
    except OSError:
        return
    if mt == conf_mtime[0]:
        return
    conf_mtime[0] = mt
    try:
        for ln in open(CONF):
            ln = ln.split("#", 1)[0].strip()
            if "=" in ln:
                k, v = ln.split("=", 1)
                conf[k.strip()] = v.strip()
    except OSError:
        pass


def zadost_on():
    return conf.get("ZADOST_KF", "1") == "1" and not pauza_on()


def pauza_on():
    return conf.get("PAUZA", "0") == "1"


pz = {"f": None}


def pauza_paket(d, size):
    """Testovaci paket z desky (vima-testgen: 4 B poradi, 8 B cas odeslani v us)."""
    if pz["f"] is None:
        dd = os.path.join(D, "mereni-kf")
        os.makedirs(dd, exist_ok=True)
        pz["f"] = open(os.path.join(dd, "kapacita-%s.log" % time.strftime("%Y%m%d-%H%M%S")), "w")
        ev("PAUZA zacatek")
    if len(d) >= 12:
        pz["f"].write("%.3f %d %d %d\n" % (time.time() * 1000.0, int.from_bytes(d[0:4], "big"),
                                          int.from_bytes(d[4:12], "big"), size))


def ev(text):
    if ev_out.tell() > MAXLOG:
        ev_out.seek(0)
        ev_out.truncate()
    ev_out.write("%.1f %s\n" % (time.time() * 1000.0, text))


# ---------- zadost o klicovy snimek ----------
lock = threading.Lock()
st = {"seq": None, "ts": None, "need": True, "t_loss": time.monotonic(), "req_n": 0, "t_req": 0.0,
      "in_idr": False, "rid": 0, "err_t": 0.0, "alive_t": 0.0, "img_loss": 0, "rep_n": 0}
wl = {"pos": None, "ant": {}, "ts": None}
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(False)


def request(now):
    """Volat pod zamkem."""
    if now - st["t_req"] < ODSTUP_S:
        return
    st["t_req"] = now
    st["req_n"] += 1
    st["rid"] = (st["rid"] + 1) & 0x7fffffff
    try:
        sock.sendto(json.dumps({"op": "keyframe", "id": st["rid"]}).encode(), DESKA)
        ev("ZADOST %d" % st["req_n"])
    except OSError as e:   # tunel nebezi - nevadi, obraz se srovna s dalsim pravidelnym klicovym snimkem
        if now - st["err_t"] > 10:
            st["err_t"] = now
            ev("ZADOST neodesla: %s" % e)


def nal_types(p):
    """Typy NAL jednotek v RTP payloadu H.265 (u FU jen prvni fragment)."""
    if len(p) < 3:
        return ()
    t = (p[0] >> 1) & 0x3f
    if t == 49:                       # FU: typ v 3. bajtu, S bit = zacatek
        return (p[2] & 0x3f,) if p[2] & 0x80 else ()
    if t == 48:                       # AP: vic NAL v jednom paketu
        out_t, i = [], 2
        while i + 2 < len(p):
            n = (p[i] << 8) | p[i + 1]
            out_t.append((p[i + 2] >> 1) & 0x3f)
            i += 2 + n
        return out_t
    return (t,)


def rtp_probe(pad, info):
    buf = info.get_buffer()
    ok, m = buf.map(Gst.MapFlags.READ)
    if not ok:
        return Gst.PadProbeReturn.OK
    try:
        d = bytes(m.data[:64])
    finally:
        buf.unmap(m)
    if pauza_on():
        pauza_paket(d, buf.get_size())
        return Gst.PadProbeReturn.DROP
    if pz["f"] is not None:   # konec pauzy: obraz znovu od klicoveho snimku
        pz["f"].close()
        pz["f"] = None
        ev("PAUZA konec")
        with lock:
            st["seq"] = None
            st["need"] = True
            st["t_loss"] = time.monotonic()
            st["req_n"] = 0
    if len(d) < 14:
        return Gst.PadProbeReturn.OK
    now = time.monotonic()
    seq = (d[2] << 8) | d[3]
    ts = struct.unpack_from("!I", d, 4)[0]
    marker = d[1] & 0x80
    hl = 12 + 4 * (d[0] & 0x0f)
    if d[0] & 0x10 and len(d) >= hl + 4:
        hl += 4 + 4 * ((d[hl + 2] << 8) | d[hl + 3])
    if mer["au"] is not None:
        au = mer["au"]
        if au["t0"] is None:
            au["t0"], au["ts"], au["n"], au["b"], au["idr"] = now, ts, 0, 0, False
        au["n"] += 1
        au["b"] += buf.get_size()
    with lock:
        if st["seq"] is not None:
            gap = (seq - st["seq"] - 1) & 0xffff
            if 0 < gap < 3000:   # ztracene pakety (velke cislo = restart streamu na desce)
                span = ((ts - st["ts"]) & 0xffffffff) / 90.0
                ev("ZTRATA paketu=%d videa_ms=%.0f" % (gap, span))
                st["img_loss"] += 1
                st["need"] = True
                st["t_loss"] = now
                st["req_n"] = 0
                st["in_idr"] = False
                if zadost_on():
                    st["t_req"] = 0.0
                    request(now)
            elif gap:
                ev("RESTART streamu (seq %d -> %d)" % (st["seq"], seq))
        st["seq"], st["ts"] = seq, ts
        if any(t in IDR for t in nal_types(d[hl:])):
            st["in_idr"] = True
            if mer["au"] is not None:
                mer["au"]["idr"] = True
        if marker and mer["au"] is not None and mer["au"]["t0"] is not None:
            au = mer["au"]
            mer["pf"].write("%.2f %.2f %d %d %d %d\n" % (time.time() * 1000.0 - (now - au["t0"]) * 1000.0,
                            time.time() * 1000.0, au["ts"], au["b"], au["n"], au["idr"]))
            au["t0"] = None
        if marker and st["in_idr"]:   # posledni paket klicoveho snimku
            st["in_idr"] = False
            if st["need"]:
                ev("KLICOVY po_ztrate_ms=%.0f zadosti=%d" % ((now - st["t_loss"]) * 1000.0, st["req_n"]))
                st["need"] = False
            else:
                ev("KLICOVY pravidelny")
    return Gst.PadProbeReturn.OK


def send_ctl(msg):
    """Volat pod zamkem."""
    st["rid"] = (st["rid"] + 1) & 0x7fffffff
    msg["id"] = st["rid"]
    try:
        sock.sendto(json.dumps(msg).encode(), DESKA)
    except OSError:
        pass


def wfb_report():
    """Nove radky statistik wfb_rx (1x za sekundu): PKT all:bytes:dec_err:dec_ok:fec:lost:bad:out:out_bytes,
    RX_ANT freq:mcs:bw ant count:rssi_min:rssi_avg:rssi_max:snr_min:snr_avg:snr_max. Vraci zpravu pro desku."""
    try:
        f = open(WFBLOG, errors="replace")
    except OSError:
        return None
    with f:
        f.seek(0, 2)
        end = f.tell()
        if wl["pos"] is None or end < wl["pos"]:   # start / novy log: bez stare historie
            wl["pos"] = end
            wl["pkt_ts"] = None
            return None
        f.seek(wl["pos"])
        data = f.read()
    cut = data.rfind("\n") + 1
    wl["pos"] += len(data[:cut].encode(errors="replace"))
    msg = None
    for ln in data[:cut].splitlines():   # pri zpozdeni muze prijit vic intervalu najednou -> secist
        p = ln.split("\t")
        if len(p) >= 5 and p[1] == "RX_ANT":
            if wl["ts"] != p[0]:
                wl["ant"], wl["ts"] = {}, p[0]
            try:
                v = [int(x) for x in p[4].split(":")]
                wl["ant"][p[3]] = v
            except ValueError:
                pass
        elif len(p) >= 3 and p[1] == "PKT":
            try:
                v = [int(x) for x in p[2].split(":")]
                t = int(p[0])
                if len(v) < 9:
                    raise ValueError
            except ValueError:
                continue
            ant = list(wl["ant"].values()) if wl["ts"] == p[0] else []
            dt = (t - wl["pkt_ts"]) / 1000.0 if wl.get("pkt_ts") and 0 < t - wl["pkt_ts"] < 5000 else 1.0
            wl["pkt_ts"] = t
            m = {"pkt": v[0], "dec_err": v[2], "fec": v[4], "lost": v[5], "bytes": v[8], "dt": dt,
                 "rssi": max((a[2] for a in ant), default=None), "snr": max((a[5] for a in ant), default=None),
                 "snr_min": max((a[4] for a in ant), default=None)}
            if msg:
                for k in ("pkt", "dec_err", "fec", "lost", "bytes", "dt"):
                    m[k] += msg[k]
                for k in ("rssi", "snr", "snr_min"):
                    if m[k] is None or (msg[k] is not None and msg[k] < m[k]):
                        m[k] = msg[k]   # horsi hodnota z intervalu
            msg = m
    if msg:
        msg["kbps"] = round(msg.pop("bytes") * 8 / 1000 / max(0.05, msg["dt"]))
        msg["dt"] = round(msg["dt"], 2)
    return msg


last_conf = [0.0]


def tick():
    try:
        tick_body()
    except Exception as e:  # noqa: BLE001  casovac nesmi skoncit (GLib by ho zrusil)
        ev("CHYBA tick: %s" % e)
    return True


def tick_body():
    now = time.monotonic()
    if now - last_conf[0] >= 1.0:
        last_conf[0] = now
        read_conf()
        if vsink is not None:
            fs = conf.get("CELA_OBRAZOVKA", "1") == "1"
            if fs != cela_obrazovka[0]:
                vsink.set_property("fullscreen", fs)
                cela_obrazovka[0] = fs
                ev("OKNO cela obrazovka %s" % fs)
    with lock:
        if st["need"] and zadost_on():
            wait = OPAKUJ_S if st["req_n"] < RYCHLE else 1.0
            if now - st["t_req"] >= wait:
                request(now)
        if pauza_on():
            wl["pos"] = None            # po pauze bez nahromadene historie
            rep = None
        else:
            rep = wfb_report()
        if rep is not None:             # kvalita prijmu pro adaptivni spoj (i kdyz se o snimky nezada)
            st["alive_t"] = now
            st["rep_n"] += 1
            rep.update(op="rx_report", n=st["rep_n"], img_loss=st["img_loss"], zadost=zadost_on())
            st["img_loss"] = 0
            send_ctl(rep)
        elif zadost_on() and now - st["alive_t"] >= ALIVE_S + 0.5:   # wfb_rx nic nehlasi -> aspon rx_alive
            st["alive_t"] = now
            send_ctl({"op": "rx_alive"})
    while True:   # odpovedi desky (jen zahozene zadosti stoji za zminku)
        try:
            r = json.loads(sock.recv(2048).decode())
        except (BlockingIOError, InterruptedError):
            break
        except (OSError, ValueError):
            break
        if not r.get("ok"):
            ev("ODPOVED chyba: %s" % r.get("err"))
        elif isinstance(r.get("res"), dict) and r["res"].get("sent") is False:
            with lock:   # deska zadost odlozila (pri pomalem MCS jeste leti predchozi klicovy snimek)
                st["req_n"] = max(0, st["req_n"] - 1)   # nepocitat ji - dalsi pokus za OPAKUJ_S
    return True


# ---------- mereni: zmensene snimky (jas) pro vyhodnoceni obnovy obrazu ----------
mer = {"f": None, "vi": None, "caps": None, "au": None, "pf": None, "df": None}


def mer_open():
    import numpy   # noqa: F401  jen pro mereni
    dd = os.path.join(D, "mereni-kf")
    os.makedirs(dd, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    p = os.path.join(dd, "nahledy-%s.bin" % stamp)
    mer["f"] = open(p, "wb")
    # prichody: cas 1. paketu, cas posledniho paketu (ms), RTP cas (90 kHz), bajty, pakety, klicovy
    mer["pf"] = open(os.path.join(dd, "prichody-%s.log" % stamp), "w", buffering=1)
    mer["df"] = open(os.path.join(dd, "dekod-%s.log" % stamp), "w", buffering=1)   # cas_ms pts_ns
    mer["au"] = {"t0": None}
    ev("MERENI nahledy %s" % os.path.basename(p))


def mer_frame(buf, caps, t_ms):
    import numpy as np
    if caps is not mer["caps"]:
        mer["caps"] = caps
        mer["vi"] = GstVideo.VideoInfo.new_from_caps(caps)
    vi = mer["vi"]
    w, h = vi.width, vi.height
    ok, m = buf.map(Gst.MapFlags.READ)
    if not ok:
        return
    try:
        y = np.frombuffer(m.data, dtype=np.uint8, count=vi.stride[0] * h, offset=vi.offset[0]).reshape(h, vi.stride[0])
        sh, sw = max(1, h // 180), max(1, w // 320)
        sub = y[::sh, ::sw][:180, :320]
        if sub.shape != (180, 320):
            return
        small = sub.reshape(45, 4, 80, 4).mean(axis=(1, 3)).astype(np.uint8)
    finally:
        buf.unmap(m)
    mer["f"].write(struct.pack("<dHH", t_ms, 80, 45) + small.tobytes())


def probe(pad, info):
    caps = pad.get_current_caps()
    w = h = 0
    t_ms = time.time() * 1000.0
    if caps:
        s = caps.get_structure(0)
        w, h = s.get_value("width"), s.get_value("height")
        if size[0] != (w, h):
            size[0] = (w, h)
            print("rozliseni videa: %dx%d" % (w, h), flush=True)
    if out.tell() > MAXLOG:
        out.seek(0)
        out.truncate()
    out.write("%.1f %d %d\n" % (t_ms, w, h))
    if mer["df"]:
        mer["df"].write("%.2f %d\n" % (t_ms, info.get_buffer().pts))
    if mer["f"] and caps:
        try:
            mer_frame(info.get_buffer(), caps, t_ms)
        except Exception as e:  # noqa: BLE001  mereni nesmi shodit okno
            print("mereni: %s" % e, flush=True)
            mer["f"] = None
    return Gst.PadProbeReturn.OK


def on_hup():
    restart[0] = True
    loop.quit()
    return GLib.SOURCE_REMOVE


read_conf()
ev("START zadost_kf=%s mereni=%s okno=%s cela_obrazovka=%s" % (conf.get("ZADOST_KF"), conf.get("MERENI"),
                                                                "wayland" if vsink is not None else "x11", cela_obrazovka[0]))
if conf.get("MERENI") == "1":
    mer_open()
pipe.get_by_name("src").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, rtp_probe)
pipe.get_by_name("dec").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, probe)
loop = GLib.MainLoop()
bus = pipe.get_bus()
bus.add_signal_watch()
bus.connect("message::error", lambda b, m: (print("CHYBA:", m.parse_error()[0].message, flush=True), loop.quit()))
bus.connect("message::eos", lambda b, m: loop.quit())
try:
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix
    sig_add = GLibUnix.signal_add
except (ImportError, ValueError):
    sig_add = GLib.unix_signal_add
sig_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, loop.quit)
sig_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, loop.quit)
sig_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, on_hup)
GLib.timeout_add(50, tick)
pipe.set_state(Gst.State.PLAYING)
loop.run()
pipe.set_state(Gst.State.NULL)
ev("KONEC")
if mer["f"]:
    mer["f"].close()
sys.exit(3 if restart[0] else 0)
