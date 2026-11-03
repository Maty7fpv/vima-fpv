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

All eight patches apply cleanly to that commit, and the result matches the files on the development laptop byte for byte.

| Patch | What it does | License | In the last firmware image (26 Oct 2026) |
|---|---|---|---|
| 0001 | rkipc: keyframe on request, ISP buffer count from the ini, ignore `wfb*` interfaces | BSD-3-Clause | yes |
| 0002 | rkipc ini: default 1280×720 @ 30 fps, 3 ISP buffers | BSD-3-Clause | yes |
| 0003 | rkipc: encoder wrap (lower latency), on-board latency log | BSD-3-Clause | **no** — only in `/oem` on the board |
| 0004 | rkipc: `power_line_frequency_mode = close` turns anti-flicker off | BSD-3-Clause | **no** — only in `/oem` on the board |
| 0005 | device tree: USB-C always in host mode, `coherent_pool=256K` | GPL-2.0 | yes |
| 0006 | SC3336 driver: 1152×648 @ 60 fps mode (variant D) | GPL-2.0 | **no** — module built out of tree, in `/oem` on the board |
| 0007 | Buildroot: libpcap, libsodium, iw, wireless-regdb for wfb-ng | GPL-2.0 (Buildroot) | yes |
| 0008 | BoardConfig: add the `overlay-vima` overlay | as the SDK | yes |

**Known gap:** patches 0003, 0004 and 0006, the ISP tuning file and the 60 fps rkipc ini are not in a firmware
image yet. A firmware built from the SDK alone boots in the old 30 fps mode without wrap. See
[`../rkipc-wrap`](../rkipc-wrap) and [`../sc3336-60fps`](../sc3336-60fps) for how they are put on the board today,
and [`../deska-20261103`](../deska-20261103) for the files and checksums on the board.

Licenses: rkipc is BSD-3-Clause, Copyright Rockchip Electronics Co., Ltd. ([text](../../LICENSES/BSD-3-Clause-rkipc.txt)).
Kernel patches are GPL-2.0 ([text](../../LICENSES/GPL-2.0-only.txt)).
