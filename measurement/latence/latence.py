#!/usr/bin/python3
# Vima: mereni latence "sklo-sklo".
# 1) HTTP server na 127.0.0.1:8765 servíruje stopky.html a prijima casy prepnuti ctverce.
# 2) GStreamer prijima video z wfb_rx (UDP 5600), zobrazuje ho v okne s minimalnim zpozdenim
#    a soucasne posila zmensene snimky do analyzy.
# 3) Analyza najde v obraze blikajici ctverec, zaznamena, kdy se zmenil, a porovna to
#    s casem prepnuti na obrazovce. Rozdil = latence (obrazovka -> kamera -> kodér -> vzduch
#    -> dekodér), bez zpozdeni zobrazeni prijateho okna.
# Pouziti: python3 latence.py [nazev] [pocet_vzorku]
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gst, GLib  # noqa: E402
import numpy as np  # noqa: E402
import cv2  # noqa: E402

NAME = sys.argv[1] if len(sys.argv) > 1 else "test"
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 60
done = False
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "vzorky-%s.csv" % NAME)
PORT = 8765

flips = []            # (t_ms, state)
flips_lock = threading.Lock()
reset_requested = threading.Event()   # POST /reset = znovu najit ctverec a zacit od nuly


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in ("/", "/stopky.html"):
            data = open(os.path.join(HERE, "stopky.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/reset":
            reset_requested.set()
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/flip":
            n = int(self.headers.get("Content-Length", 0))
            try:
                d = json.loads(self.rfile.read(n))
                with flips_lock:
                    flips.append((float(d["t"]), int(d["s"])))
                    del flips[:-200]
            except Exception:
                pass
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)


def serve():
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


threading.Thread(target=serve, daemon=True).start()
print("Stopky: http://127.0.0.1:%d/  (otevri ve Firefoxu, okno vlevo)" % PORT, flush=True)

# ---- analyza ----
W, H = 320, 180
calib = []            # snimky pro hledani ctverce
roi = None
levels = []           # posledni jasy v ROI
cur_state = None
samples = []
t_start = None
t_roi = None          # kdy byl nalezen ctverec (prvnich 10 s se zahazuje - nabeh expozice)
rejected = 0          # zmeny, ktere nesly sparovat (prehlednute bliknuti)
WARMUP_MS = 10000
MAX_LAT_MS = 500      # bliknuti jsou 600-1000 ms od sebe, delsi "latence" = prehlednuta zmena


def find_roi(frames):
    st = np.std(np.stack(frames).astype(np.float32), axis=0)
    if st.max() < 20:
        return None
    mask = (st > 0.5 * st.max()).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, a = stats[i]
    if a < 30:
        return None
    # vnitrek oblasti (bez okraju)
    dx, dy = max(1, w // 6), max(1, h // 6)
    return (x + dx, y + dy, max(2, w - 2 * dx), max(2, h - 2 * dy))


# ---- zpozdeni laptopu: posledni RTP paket snimku -> snimek predan oknu (depay+dekoder+prevod) ----
from collections import OrderedDict  # noqa: E402
pkt_rts = OrderedDict()   # PTS paketu z udpsrc -> RTP timestamp
mark_t = OrderedDict()    # RTP timestamp -> cas prichodu posledniho paketu snimku (marker)
dec_lat = []              # ms


def probe_rtp(pad, info):
    buf = info.get_buffer()
    ok, mi = buf.map(Gst.MapFlags.READ)
    if ok:
        try:
            d = mi.data
            if len(d) >= 12:
                rts = int.from_bytes(d[4:8], "big")
                pkt_rts[buf.pts] = rts
                if d[1] & 0x80:
                    mark_t[rts] = time.time() * 1000.0
        finally:
            buf.unmap(mi)
    while len(pkt_rts) > 3000:
        pkt_rts.popitem(last=False)
    while len(mark_t) > 300:
        mark_t.popitem(last=False)
    return Gst.PadProbeReturn.OK


def probe_disp(pad, info):
    rts = pkt_rts.get(info.get_buffer().pts)
    t = mark_t.get(rts) if rts is not None else None
    if t is not None:
        dec_lat.append(time.time() * 1000.0 - t)
        del dec_lat[:-3000]
    return Gst.PadProbeReturn.OK


def report_dec():
    if not dec_lat:
        print("  laptop (paket->okno): nezmereno", flush=True)
        return
    a = np.array(dec_lat)
    msg = ("laptop (posledni paket -> okno): %d snimku, median %.1f ms, prumer %.1f ms, 95 %% pod %.1f ms, max %.1f ms"
           % (len(a), np.median(a), a.mean(), np.percentile(a, 95), a.max()))
    print("  " + msg, flush=True)
    with open(os.path.join(HERE, "dekoder-%s.txt" % NAME), "w") as f:
        f.write(msg + "\n")


def report():
    report_dec()
    if not samples:
        return
    a = np.array([s for _, s in samples])
    print("  vzorku %d: prumer %.0f ms, median %.0f ms, min %.0f ms, max %.0f ms, sm. odch. %.0f ms (vyrazeno %d)"
          % (len(a), a.mean(), np.median(a), a.min(), a.max(), a.std(), rejected), flush=True)


def on_frame(gray, t_ms):
    global roi, cur_state, t_start, t_roi, rejected, done
    if reset_requested.is_set():
        reset_requested.clear()
        roi, cur_state, t_start = None, None, None
        calib.clear(); levels.clear(); samples.clear(); rejected = 0; done = False
        open(CSV, "w").write("t_ms,latence_ms\n")
        print("RESET: hledam ctverec znovu, vzorky od nuly.", flush=True)
    if t_start is None:
        t_start = t_ms
        print("Prijimam video, hledam blikajici ctverec (5 s)...", flush=True)
    if roi is None:
        calib.append(gray)
        if t_ms - t_start > 5000:
            roi = find_roi(calib[-150:])
            calib.clear()
            t_start = t_ms
            if roi is None:
                print("Ctverec v obraze nenalezen - miri kamera na stopky? Zkousim znovu.", flush=True)
            else:
                t_roi = t_ms
                print("Ctverec nalezen (oblast %s). 10 s nabeh, pak meram..." % (roi,), flush=True)
        return
    x, y, w, h = roi
    v = float(gray[y:y + h, x:x + w].mean())
    levels.append(v)
    del levels[:-300]
    lo, hi = min(levels), max(levels)
    if hi - lo < 25:
        return
    th_hi, th_lo = lo + 0.6 * (hi - lo), lo + 0.4 * (hi - lo)
    new = cur_state
    if v > th_hi:
        new = 1
    elif v < th_lo:
        new = 0
    if cur_state is None:
        cur_state = new
        return
    if new != cur_state:
        cur_state = new
        with flips_lock:
            cand = [t for t, s in flips if s == new and t < t_ms and t_ms - t < 1500]
        if t_ms - t_roi < WARMUP_MS:
            return
        lat = (t_ms - max(cand)) if cand else None
        if lat is None or lat > MAX_LAT_MS:
            rejected += 1
            print("  (vyrazeno: zmena bez odpovidajiciho bliknuti)", flush=True)
            return
        if not done:
            samples.append((t_ms, lat))
            print("vzorek %2d: %.0f ms" % (len(samples), lat), flush=True)
            with open(CSV, "a") as f:
                f.write("%.1f,%.1f\n" % (t_ms, lat))
            if len(samples) % 10 == 0:
                report()
            if len(samples) >= TARGET:
                done = True
                print("HOTOVO (%s), okno zustava otevrene pro foceni telefonem. Konec: Ctrl+C" % NAME, flush=True)
                report()


def on_sample(sink):
    s = sink.emit("pull-sample")
    t_ms = time.time() * 1000.0
    buf = s.get_buffer()
    ok, mi = buf.map(Gst.MapFlags.READ)
    if ok:
        try:
            gray = np.frombuffer(mi.data, dtype=np.uint8)[:W * H].reshape(H, W).copy()
        finally:
            buf.unmap(mi)
        on_frame(gray, t_ms)
    return Gst.FlowReturn.OK


Gst.init(None)
open(CSV, "w").write("t_ms,latence_ms\n")
pipe = Gst.parse_launch(
    'udpsrc name=src port=5600 buffer-size=1048576 caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H265" '
    '! rtph265depay ! h265parse ! avdec_h265 max-threads=1 ! tee name=t '
    't. ! queue max-size-buffers=1 leaky=downstream ! videoconvert name=conv ! autovideosink sync=false '
    't. ! queue max-size-buffers=2 leaky=downstream ! videoscale ! video/x-raw,width=%d,height=%d '
    '! videoconvert ! video/x-raw,format=GRAY8 ! appsink name=sink emit-signals=true sync=false max-buffers=2 drop=true'
    % (W, H))
pipe.get_by_name("sink").connect("new-sample", on_sample)
pipe.get_by_name("src").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, probe_rtp)
pipe.get_by_name("conv").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, probe_disp)
loop = GLib.MainLoop()
bus = pipe.get_bus()
bus.add_signal_watch()
bus.connect("message::error", lambda b, m: (print("CHYBA:", m.parse_error()[0].message, flush=True), loop.quit()))
pipe.set_state(Gst.State.PLAYING)
print("Cil: %d vzorku, vysledky do %s. Ukonceni: Ctrl+C" % (TARGET, CSV), flush=True)
try:
    loop.run()
except KeyboardInterrupt:
    print("Preruseno.", flush=True)
    report()
pipe.set_state(Gst.State.NULL)
