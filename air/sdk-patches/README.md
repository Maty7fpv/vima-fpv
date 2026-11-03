# Changes to the Luckfox Pico SDK

Patches against [LuckfoxTECH/luckfox-pico](https://github.com/LuckfoxTECH/luckfox-pico) at commit
`824b817f889c2cbff1d48fcdb18ab494a68f69d1`. Apply them in order from the SDK root:

```sh
cd ~/luckfox-pico
git checkout 824b817f889c2cbff1d48fcdb18ab494a68f69d1
for p in /path/to/vima-fpv/air/sdk-patches/*.patch; do git apply "$p"; done
```

Then copy [`../overlay`](../overlay) to `project/cfg/BoardConfig_IPC/overlay/overlay-vima`, add your own
wfb-ng key (see [`../README.md`](../README.md)) and build as usual (`./build.sh`, inside the `luckfox` distrobox).
For the 1152×648 @ 55 fps mode also replace the SDK's ISP tuning file with the output of
[`../sc3336-60fps/iq/vytvor-iq.sh`](../sc3336-60fps/iq/vytvor-iq.sh) and the SDK's `rkipc-300w.ini` with
[`../deska-20261103/rkipc-300w.ini`](../deska-20261103/rkipc-300w.ini).

All eight patches apply cleanly to that commit, and the result matches the files on the development laptop byte for byte.

| Patch | What it does | License |
|---|---|---|
| 0001 | rkipc: keyframe on request, ISP buffer count from the ini, ignore `wfb*` interfaces | BSD-3-Clause |
| 0002 | rkipc ini: default 1280×720 @ 30 fps, 3 ISP buffers | BSD-3-Clause |
| 0003 | rkipc: encoder wrap (lower latency), on-board latency log | BSD-3-Clause |
| 0004 | rkipc: `power_line_frequency_mode = close` turns anti-flicker off | BSD-3-Clause |
| 0005 | device tree: USB-C always in host mode, `coherent_pool=256K` | GPL-2.0 |
| 0006 | SC3336 driver: 1152×648 @ 60 fps mode (variant D) | GPL-2.0 |
| 0007 | Buildroot: libpcap, libsodium, iw, wireless-regdb for wfb-ng | GPL-2.0 (Buildroot) |
| 0008 | BoardConfig: add the `overlay-vima` overlay | as the SDK |

Since 3 Nov 2026 all eight patches, the ISP tuning file and the 55 fps ini are in the firmware running on the board.

**Known gap:** `vima-ctl` switches between the 30 and 60 fps camera modes with two modules in `/oem/usr/share/vima`
(`sc3336-30.ko` = the unmodified driver, `sc3336-60.ko` = the driver with patch 0006). They are not produced by the
SDK build yet. For the 3 Nov firmware they were copied into `output/out/oem` by hand, so `./build.sh clean` drops them.
The checksums are in [`../deska-20261103`](../deska-20261103).

Licenses: rkipc is BSD-3-Clause, Copyright Rockchip Electronics Co., Ltd. ([text](../../LICENSES/BSD-3-Clause-rkipc.txt)).
Kernel patches are GPL-2.0 ([text](../../LICENSES/GPL-2.0-only.txt)).
