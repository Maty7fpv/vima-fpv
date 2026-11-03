#!/usr/bin/python3
# Vima: pripoji se k RTSP serveru rkipc na desce a necha si posilat RTP video
# primo na UDP port wfb_tx (RTSP pres UDP, client_port). Samo nic nekopiruje,
# jen drzi RTSP relaci nazivu a pri vypadku se pripoji znovu.
# Pouziti: vima-video.py [rtsp_url] [udp_port]
import re
import socket
import sys
import time

URL = sys.argv[1] if len(sys.argv) > 1 else "rtsp://127.0.0.1:554/live/0"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5602
KEEPALIVE = 20

m = re.match(r"rtsp://([^:/]+)(?::(\d+))?(/.*)?", URL)
HOST, RPORT = m.group(1), int(m.group(2) or 554)


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "vima-video:", msg, flush=True)


class Rtsp:
    def __init__(self):
        self.s = socket.create_connection((HOST, RPORT), timeout=5)
        self.cseq = 0
        self.session = None
        self.buf = b""

    def request(self, method, url, headers=None):
        self.cseq += 1
        h = {"CSeq": str(self.cseq), "User-Agent": "vima-video"}
        if self.session:
            h["Session"] = self.session
        h.update(headers or {})
        msg = "%s %s RTSP/1.0\r\n" % (method, url)
        msg += "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n"
        self.s.sendall(msg.encode())
        return self.response()

    def response(self):
        while b"\r\n\r\n" not in self.buf:
            d = self.s.recv(4096)
            if not d:
                raise ConnectionError("RTSP spojeni zavreno")
            self.buf += d
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        lines = head.decode(errors="replace").split("\r\n")
        code = int(lines[0].split()[1])
        hdr = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                hdr[k.strip().lower()] = v.strip()
        n = int(hdr.get("content-length", 0))
        while len(self.buf) < n:
            d = self.s.recv(4096)
            if not d:
                raise ConnectionError("RTSP spojeni zavreno")
            self.buf += d
        body, self.buf = self.buf[:n], self.buf[n:]
        if code != 200:
            raise ConnectionError("RTSP %s: %s" % (code, lines[0]))
        return hdr, body.decode(errors="replace")


def run_once():
    r = Rtsp()
    hdr, sdp = r.request("DESCRIBE", URL, {"Accept": "application/sdp"})
    base = hdr.get("content-base", URL).rstrip("/")
    ctrl = None
    in_video = False
    for ln in sdp.splitlines():
        if ln.startswith("m="):
            in_video = ln.startswith("m=video")
        if in_video and ln.startswith("a=rtpmap:"):
            log("video: " + ln[9:])
        if in_video and ln.startswith("a=control:"):
            ctrl = ln[10:].strip()
            break
    if ctrl is None:
        track = base
    elif ctrl.startswith("rtsp://"):
        track = ctrl
    else:
        track = base + "/" + ctrl
    hdr, _ = r.request("SETUP", track, {
        "Transport": "RTP/AVP;unicast;client_port=%d-%d" % (PORT, PORT + 1)})
    r.session = hdr.get("session", "").split(";")[0]
    log("SETUP ok (%s), RTP -> UDP %d" % (hdr.get("transport", ""), PORT))
    r.request("PLAY", base, {"Range": "npt=0.000-"})
    log("PLAY ok, video tece do wfb_tx")
    while True:
        time.sleep(KEEPALIVE)
        r.request("OPTIONS", URL)


def main():
    while True:
        try:
            run_once()
        except Exception as e:
            log("chyba: %s, znovu za 3 s" % e)
            time.sleep(3)


if __name__ == "__main__":
    main()
