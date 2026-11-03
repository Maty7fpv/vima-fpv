#!/bin/bash
# Vima: mereni latence. Pouziti: ~/vima-board/latence/mer.sh <nazev-mereni> [pocet_vzorku]
# Spusti prijem (sudo), okno s videem a automaticke mereni. Stopky: http://127.0.0.1:8765/
VIMA_LATENCE=${1:?Pouziti: $0 <nazev> [vzorky]} VIMA_VZORKY=${2:-60} exec /home/mikes/vima-board/gs-video.sh
