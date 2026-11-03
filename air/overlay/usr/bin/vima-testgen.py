#!/usr/bin/python3
# Vima: testovaci data pro wfb_tx (dokud nebezi video).
# Posila UDP pakety 1024 B s poradovym cislem (prvni 4 B, big endian)
# a casem odeslani v us (dalsich 8 B), rychlost v kbit/s.
# Pouziti: vima-testgen.py <host> <port> <kbit/s>
import socket
import sys
import time

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 5602
kbps = float(sys.argv[3]) if len(sys.argv) > 3 else 2000.0

SIZE = 1024
interval = SIZE * 8 / (kbps * 1000.0)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
buf = bytearray(SIZE)
seq = 0
t = time.monotonic()
while True:
    buf[0:4] = seq.to_bytes(4, "big")
    buf[4:12] = int(time.time() * 1e6).to_bytes(8, "big")
    try:
        s.sendto(buf, (host, port))
    except OSError:
        pass
    seq = (seq + 1) & 0xFFFFFFFF
    t += interval
    d = t - time.monotonic()
    if d > 0:
        time.sleep(d)
    elif d < -1.0:
        t = time.monotonic()
