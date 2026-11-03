#!/usr/bin/python3
# Vima krok 4: mereni kapacity spoje - cast na desce (spousti kapacita.py z laptopu pres ssh).
# Video z kamery se na dobu mereni zahodi (iptables: do wfb_tx videa smi jen zdrojovy port 5611)
# a do wfb_tx (UDP 5602) jdou testovaci pakety: 4 B poradi, 8 B cas odeslani v us, zbytek nuly.
# Pro kazde MCS a tok: davky po 10 ms, mereni CPU wfb_tx a statistik z /tmp/wfb_tx.log.
# Vykon ani kanal se nemeni, jen MCS videa (wfb_tx_cmd 8000 set_radio); na konci vzdy zpet.
# Pouziti: kapacita-deska.py '<json plan>'   plan = {"kroky": [[mcs, kbps], ...], "krok_s": 3, "velikost": 1400}
import json
import os
import socket
import subprocess
import sys
import time

PLAN = json.loads(sys.argv[1])
SIZE = int(PLAN.get("velikost", 1400))
STEP = float(PLAN.get("krok_s", 3))
RULE = ["INPUT", "-p", "udp", "--dport", "5602", "!", "--sport", "5611", "-j", "DROP"]
TXLOG = "/tmp/wfb_tx.log"
CMD = "/usr/bin/wfb_tx_cmd"


def out(d):
    print(json.dumps(d), flush=True)


def get_radio():
    r = {}
    for ln in subprocess.run([CMD, "8000", "get_radio"], capture_output=True, text=True, timeout=3).stdout.split():
        if "=" in ln:
            k, v = ln.split("=", 1)
            r[k] = v
    return r


def set_mcs(m, r0):
    subprocess.run([CMD, "8000", "set_radio", "-B", r0.get("bandwidth", "20"),
                    "-G", "short" if r0.get("short_gi") == "1" else "long",
                    "-S", r0.get("stbc", "0"), "-L", r0.get("ldpc", "0"), "-M", str(m)], check=True, timeout=3)


def video_pid():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                c = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if c and c[0].endswith(b"wfb_tx") and b"-p" in c and c[c.index(b"-p") + 1] == b"0":
                return int(p)
    return None


def ticks(pid):
    v = open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()
    return int(v[11]) + int(v[12])


def total():
    v = open("/proc/stat").readline().split()[1:]
    return sum(int(x) for x in v), int(v[3]) + int(v[4])


def txlog_new(pos):
    try:
        with open(TXLOG) as f:
            f.seek(0, 2)
            end = f.tell()
            if end < pos:   # log zkracen
                pos = 0
            f.seek(pos)
            return f.read(), end
    except OSError:
        return "", pos


def parse_tx(text):
    inj = drop = 0
    lat = []
    for ln in text.splitlines():
        p = ln.split("\t")
        if len(p) >= 3 and p[1] == "PKT":
            v = p[2].split(":")
            if len(v) >= 6:
                inj += int(v[3])
                drop += int(v[5])
        if len(p) >= 4 and p[1] == "TX_ANT":
            v = p[3].split(":")
            if len(v) >= 5:
                lat.append((int(v[2]), int(v[3]), int(v[4])))
    return {"injected": inj, "dropped": drop,
            "lat_avg_us": round(sum(x[1] for x in lat) / len(lat)) if lat else None,
            "lat_max_us": max((x[2] for x in lat), default=None)}


def send(sock, kbps, dur, seq0):
    pps = kbps * 1000.0 / 8 / SIZE
    buf = bytearray(SIZE)
    seq = seq0
    t0 = time.monotonic()
    sent = 0.0
    while True:
        now = time.monotonic()
        if now - t0 >= dur:
            break
        want = int((now - t0) * pps)
        while sent < want:
            buf[0:4] = (seq & 0xFFFFFFFF).to_bytes(4, "big")
            buf[4:12] = int(time.time() * 1e6).to_bytes(8, "big")
            try:
                sock.sendto(buf, ("127.0.0.1", 5602))
            except OSError:
                pass
            seq += 1
            sent += 1
        time.sleep(0.01)
    return seq


def main():
    r0 = get_radio()
    pid = video_pid()
    out({"start": time.time() * 1000, "radio": r0, "wfb_tx_pid": pid})
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 5611))
    seq = 0
    cur = None
    subprocess.run(["iptables", "-I"] + RULE, check=True)
    try:
        time.sleep(0.5)
        for m, kbps in PLAN["kroky"]:
            if m != cur:
                set_mcs(m, r0)
                cur = m
                time.sleep(0.5)
            pos = os.path.getsize(TXLOG) if os.path.exists(TXLOG) else 0
            c0, (a0, i0) = ticks(pid), total()
            t0 = time.time() * 1000
            s0 = seq
            seq = send(sock, kbps, STEP, seq)
            t1 = time.time() * 1000
            c1, (a1, i1) = ticks(pid), total()
            time.sleep(1.2)   # dobeh fronty a dalsi radek statistik wfb_tx
            text, _ = txlog_new(pos)
            d = {"mcs": m, "kbps": kbps, "t0": t0, "t1": t1, "seq0": s0, "seq1": seq,
                 "cpu_wfb_tx": round(100.0 * (c1 - c0) / max(1, a1 - a0), 1),
                 "cpu_celkem": round(100.0 * (1 - (i1 - i0) / max(1, a1 - a0)), 1)}
            d.update(parse_tx(text))
            out(d)
    finally:
        subprocess.run(["iptables", "-D"] + RULE)
        try:
            set_mcs(int(r0.get("mcs_index", 1)), r0)
        except Exception as e:  # noqa: BLE001
            out({"chyba_navratu_mcs": str(e)})
        out({"konec": time.time() * 1000, "radio": get_radio()})


if __name__ == "__main__":
    main()
