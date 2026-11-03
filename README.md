# Vima

**An open-source digital FPV video transmission system.**

Low-latency H.265 video over Wi-Fi (wfb-ng), built on cheap, off-the-shelf hardware: a Rockchip RV1106 board, a 3 MP camera and an RTL8812AU Wi-Fi adapter. No vendor lock-in, no proprietary goggles.

> **Status (November 2026): working prototype on the bench.** Live video goes from the air unit to a Linux laptop over the air, and a two-way link runs back to the board. Best measured glass-to-glass latency so far: **52 ms**. Not flying yet. Outdoor range tests and lab measurements of transmit power and listen-before-talk come next.

---

## What works today

- Camera → hardware H.265 encoder → RTP → wfb-ng, all on the RV1106 board, started automatically at boot
- **1152×648 at 55 or 60 fps** from a custom 2×2-binning mode of the SC3336 sensor
- Ground station on a Linux laptop: wfb-ng receiver, full-screen GStreamer playback, control panel
- **Two-way link:** an IP tunnel over the air (SSH to the air unit while it is transmitting, ~16 ms ping)
- **Keyframe on request:** after packet loss the ground station asks for a new keyframe, and the picture recovers in ~100 ms instead of ~490 ms
- **Adaptive link:** the ground station reports link quality five times per second, and the air unit picks the MCS (0–4) and bitrate to match
- Bitrate, frame rate, resolution, transmit power, channel and band can all be changed from the ground
- Regulatory domain CZ, transmit power caps hard-coded in the firmware

## Measurements

Glass-to-glass latency: a stopwatch on screen, filmed at 480 fps together with the ground station display (240 Hz laptop panel), indoors.

| Date | Video mode | Latency |
|---|---|---|
| 25 Oct 2026 | 2304×1296 @ 25 fps | 106 ms (72–174) |
| 25 Oct 2026 | 1280×720 @ 30 fps | 83 ms (60–140) |
| 27 Oct 2026 | 1152×648 @ 60 fps | 52 ms |

Newer settings (encoder wrap, 4 ms exposure cap, smaller FEC blocks) cut the delay on the board from 22.5 ms to 18.5 ms per frame. Their glass-to-glass latency has not been measured yet.

- 30 s transfer at MCS 4: 54.6 fps received, longest gap 42 ms, 0 lost packets
- Link capacity at MCS 4: ~9.7 Mbit/s. Above that, the board's single Cortex-A7 core is the bottleneck.
- Range indoors: ~10 m through walls at low power. Outdoor range is not measured yet.

## Why 2.4 GHz

The lower band propagates better, and with listen-before-talk (LBT, "adaptivity") it allows more power:

| Band and mode | Limit (EIRP, antenna gain included) | Rule |
|---|---|---|
| 2.4 GHz with LBT | 100 mW | EN 300 328 |
| 2.4 GHz without LBT | power × share of time transmitting ≤ 10 mW, bursts ≤ 10 ms (for Vima's video roughly 30–40 mW peak, estimated) | EN 300 328 |
| 2.4 GHz, short-range device | 25 mW, no LBT, no time limits | Czech VO-R/10 only (EU-wide it is 10 mW) |
| 5.8 GHz | 25 mW | EN 300 440 |

The catch: 2.4 GHz is crowded wherever there is Wi-Fi. In a test at school, a 2.4 GHz channel lost 30–85 % of packets while 5.8 GHz channel 149 was clean.

So Vima uses both bands: **5.8 GHz in towns, 2.4 GHz away from buildings.** Until the transmit power and LBT are measured in a lab, the target is at most 25 mW on both bands. 100 mW with LBT comes after that. The Wi-Fi driver supports LBT, but it is not switched on yet. Today the power is only estimated from RSSI (~8 mW EIRP at the 2.4 GHz setting, uncertainty about ±10 dB), so meeting the limit is not verified yet.

## Hardware

**Air unit (current prototype)**
- **Board:** Luckfox Pico Pro Max — Rockchip RV1106G3, single Cortex-A7, 256 MB RAM, 256 MB SPI NAND
- **Camera:** SmartSens SC3336, 3 MP, MIPI CSI
- **Wi-Fi:** RTL8812AU USB adapter on the board's USB-C port (host mode), monitor mode with packet injection
- **Enclosure:** 3D-printed test box (in progress)

**Ground station**
- Linux laptop with an RTL8812AU adapter running wfb-ng

**Control link:** the drone is flown over a separate ELRS 868 MHz link, so the RC failsafe stays independent of the video link.

> **A note on the Wi-Fi chipset:** the newer RTL8812**EU** has a known bug where 2.4 GHz monitor mode fails. The older **AU** is the safe choice.

## Software

**Air unit:** Luckfox Pico SDK (Buildroot 2023.02.6, Linux 5.10.160) with
- [svpcom's RTL8812AU driver](https://github.com/svpcom/rtl8812au) (`88XXau_wfb`) and [wfb-ng](https://github.com/svpcom/wfb-ng) 25.01, cross-compiled
- a modified `rkipc` (Rockchip's camera application): H.265 RTP straight into `wfb_tx`, keyframe on request, encoder wrap mode for lower latency
- a custom 1152×648 @ 60 fps mode in the SC3336 kernel driver, with its own ISP tuning
- boot services for the radio, video, the IP tunnel and a small control daemon (`vima-ctl`)

**Ground station:** `wfb_rx` → GStreamer window, plus Python tools for link-quality feedback and remote control.

## Repository layout

| Folder | What's inside |
|---|---|
| [`air`](air) | Air unit: root filesystem overlay, patches to the Luckfox SDK, low-latency camera and encoder setup ([details](air/README.md)) |
| [`ground`](ground) | Ground station: IP tunnel, video window, control panel, flashing ([details](ground/README.md)) |
| [`measurement`](measurement) | Latency, keyframe recovery, link capacity and adaptive link measurements |
| [`docs`](docs) | Measurement data, graphs and development notes (in Czech) |

Not included: the wfb-ng keys (generate your own), the Luckfox SDK itself, compiled binaries and firmware images. Most scripts still use absolute paths from the development laptop.

## Roadmap

**Graduation project (deadline April 2027)**
- [x] Buildroot on the Luckfox Pico Pro Max
- [x] Camera → hardware encoder pipeline
- [x] wfb-ng link, air ↔ ground, both directions
- [x] End-to-end video on the ground station
- [x] Latency measurement (480 fps camera against a stopwatch)
- [ ] Outdoor range test, 2.4 and 5.8 GHz
- [ ] Transmit power and LBT measured in a lab, LBT switched on
- [ ] Stability: hardware watchdog, flash checks
- [ ] Test enclosure, then onto a drone
- [ ] H.265 recording to microSD *(stretch)*
- [ ] IMU logging for Gyroflow + external IMU connector *(stretch)*

**Later**
- Custom carrier board for the Luckfox Core1106 SoM
- Flagship air unit on RK3576, dual-band, dual-stream (4K recording + 1080p120 transmission)
- **Cortex VRX** — a ground station box with HDMI output, so existing goggles work

## How this is being built

I'm a secondary school student in the Czech Republic and this is my graduation project: solo, on a small budget, with a hard deadline.

**I'm not a programmer.** I do the system architecture, hardware selection, bring-up, the physical work and the testing. Claude (Anthropic's AI, through Claude Code with access to my laptop) writes most of the code, builds the firmware and runs the measurements. Commits it worked on say so with a `Co-Authored-By: Claude` line.

## Follow along

Short clips from the bench go up as things happen:

- **Instagram:** [@maty7_fpv](https://www.instagram.com/maty7_fpv/)
- **YouTube:** [@matyasmikes9073](https://www.youtube.com/@matyasmikes9073)
- **Issues** here for bugs, questions and hardware suggestions

If you know the wfb-ng / OpenIPC ecosystem and see me about to make an expensive mistake, please say so early.

## License

- Vima's own code: **GPL-3.0** ([LICENSE](LICENSE))
- Patches to third-party code keep its license: rkipc patches **BSD-3-Clause**, Linux kernel patches **GPL-2.0** ([air/sdk-patches](air/sdk-patches), texts in [LICENSES](LICENSES))
- Hardware designs (when added): **CERN-OHL-S v2**

## Disclaimer

Radio regulations differ by country. The firmware is set to the CZ regulatory domain with hard-coded power caps, but the actual output power has not been measured yet. You are responsible for complying with local law on transmit power, frequency use, and where and how you fly. Test without propellers.

---

### Česky

Vima je open-source digitální FPV systém: přenos videa v H.265 přes Wi-Fi (wfb-ng) na levném, běžně dostupném hardwaru. Vzniká jako maturitní projekt.

Stav v listopadu 2026: obraz z kamery jde vzduchem do notebooku, spoj funguje oběma směry a nejlepší naměřená latence sklo–sklo je 52 ms. Na řadě je test dosahu venku a změření výkonu a LBT v laboratoři. Na 2,4 GHz smí zařízení s LBT vysílat až 100 mW EIRP (EN 300 328), bez LBT v ČR 25 mW (VO-R/10), na 5,8 GHz 25 mW. Vima proto používá ve městě 5,8 GHz a mimo zástavbu 2,4 GHz; 100 mW s LBT až po změření výkonu a LBT v laboratoři.
