# Vima

**An open-source digital FPV video transmission system.**

Low-latency H.265 video over Wi-Fi, built on cheap, off-the-shelf hardware. No vendor lock-in, no proprietary goggles, no binding to one ecosystem.

> **Status: early development.** Hardware is on the way. The architecture is settled, the software stack is chosen, and the first parts are on the bench. Nothing flies yet. Follow along — I'm documenting the whole thing from zero.

---

## Why another FPV system?

Because in Europe, the legal situation makes 2.4 GHz the better band and nobody is using it.

EU regulations allow **100 mW EIRP on 2.4 GHz**, but only **25 mW on 5.8 GHz**. Every mainstream digital FPV system (DJI, Walksnail, HDZero) transmits on 5.8 GHz. Combined with the better propagation of the lower band, a legally-compliant 2.4 GHz link can outrange a legally-compliant 5.8 GHz link — by a lot.

Vima is built around that. One band, one channel, done properly.

Beyond that:

- **Open.** Firmware, carrier board schematics, and build instructions are public. Repair it, modify it, fork it.
- **Cheap.** The whole air unit is built from parts you can order today for a fraction of a DJI unit.
- **Not a walled garden.** The long-term goal is a ground station with HDMI output, so you can use goggles you already own.

## Target specifications (graduation-project version)

| | |
|---|---|
| Resolution | 1080p60 (1080p30 guaranteed, 60 experimental) |
| Codec | H.265 / HEVC, hardware encoder |
| Glass-to-glass latency | ~35–45 ms (target) |
| Band | 2.4 GHz, single fixed channel |
| Protocol | wfb-ng / wifibroadcast |
| Air unit size | 30×30 mm SoM on a custom carrier board |

## Hardware

**Air unit**
- **SoC:** Rockchip RV1106G3 — Luckfox Pico Pro Max for development, Luckfox Core1106 SoM (30×30 mm) as the production target
- **Camera:** SC3336 sensor over MIPI CSI
- **Wi-Fi:** RTL8812AU-based card in monitor mode with packet injection
- **Power:** VBAT from ESC pads → 5 V / 3–5 A step-down, with a low-ESR bulk capacitor right at the Wi-Fi card (TX bursts will otherwise brown it out — this bit is not optional)

**Ground station**
- Linux laptop running wfb-ng, same RTL8812AU card

> **A note on the Wi-Fi chipset:** the newer RTL8812**EU** has a known bug where 2.4 GHz monitor mode fails despite working fine in managed mode. The older **AU** variant is the correct choice here.

## Software

- **Buildroot** — minimal image, fast boot, no package manager overhead
- **wfb-ng / wifibroadcast** — the radio link layer
- **rockit / RKMPI** — the RV1106 video pipeline (note: this is *not* the same as Rockchip MPP, which is RK3576 and up)

## What makes it different

Two things I haven't seen done well elsewhere:

**Detachable IMU module for Gyroflow.** An onboard ICM-42688-P logs gyro data alongside the video for post-flight stabilization. On top of that: a tiny (~10×10 mm) external IMU module on a 4-wire I²C / JST-SH connector, which you can stick to *any* camera — a GoPro, an action cam, whatever — and get proper Gyroflow logs from it. Autodetected at boot via WHO_AM_I.

**Parallel microSD recording.** The same encoded H.265 stream that goes out over the air also gets written to a microSD card, with no re-encode and no extra encoder load.

## Roadmap

**Now — graduation project (fixed deadline, minimal budget)**
- [ ] Boot Buildroot on Luckfox Pico Pro Max
- [ ] Camera → hardware encoder pipeline running
- [ ] wfb-ng link up, air ↔ ground
- [ ] End-to-end video on the ground station
- [ ] Latency measurement (240 fps slow-motion against a stopwatch)
- [ ] Range test
- [ ] Custom carrier board for the Core1106 SoM
- [ ] H.265 recording to microSD *(stretch)*
- [ ] IMU logging + external IMU connector *(stretch)*

**Later**
- RC-over-link: transmitter → USB HID → wfb-ng tunnel → emulated CRSF receiver on the flight controller's UART
- Flagship air unit on RK3576, dual-band, dual-stream (4K recording + 1080p120 transmission)
- **Cortex VRX** — a ground station box with HDMI output, so existing goggles work

## How this is being built

I'm a secondary school student in the Czech Republic and this started as my graduation project. I'm solo on it, on a small budget, with a hard deadline.

I should be upfront about the workflow: **I'm not a programmer.** I do the system architecture, hardware selection, board design, bring-up, measurement and debugging. Claude writes most of the implementation code. I read it, flash it, test it on real hardware, and report back what actually happened — which, so far, is usually "not that."

I'm mentioning this because it will be obvious from the commit history anyway, and because I think it's a reasonable way to build things in 2026. Nothing here gets committed without running on real silicon first.

## Follow along

I'm recording the whole process — first boots, hardware arriving, things catching fire. Short clips go up as they happen.

- **Issues** — bugs, questions, hardware suggestions
- **Discussions** — everything else
- *(add your YouTube / Instagram / TikTok links here)*

If you know the wfb-ng / OpenIPC ecosystem and see me about to make an expensive mistake, please say so early.

## License

Software: **GPL-3.0** (wfb-ng-derived components require it).
Hardware designs: **CERN-OHL-S v2**.

See [LICENSE](LICENSE) and [hardware/LICENSE](hardware/LICENSE).

## Disclaimer

Radio regulations differ by country. Vima ships configured for EU limits. It is the operator's responsibility to comply with local law regarding transmit power, frequency use, and where and how you fly. Test without propellers.

---

### Česky

Vima je open-source digitální FPV systém — přenos videa v H.265 přes Wi-Fi na levném, běžně dostupném hardwaru. Vzniká jako maturitní projekt. Hlavní myšlenka: v EU je na 2,4 GHz povoleno 100 mW EIRP oproti 25 mW na 5,8 GHz, kde vysílá úplně všechno ostatní — legálně tedy delší dosah než komerční systémy.

Zatím se čeká na hardware. Vývoj dokumentuji průběžně, veškerý postup je veřejný.
