# Board state on 3 Nov 2026

What runs on the air unit today but is not in the last firmware image (26 Oct 2026). Taken from a backup of the board. Use it to check a new firmware build: the IQ file and the ini must match exactly. rkipc and the kernel module only match if they are built the same way.

| File on the board | md5 | Source in this repository |
|---|---|---|
| `/oem/usr/bin/rkipc` | `84a9691c6b5e7bd4a5e0289f9da31a1c` | rkipc + [sdk-patches](../sdk-patches) 0001, 0003, 0004 |
| `/oem/usr/ko/sc3336.ko`, `/oem/usr/share/vima/sc3336-60.ko` | `c5c169ce8fed752c9e14885a81cba8f9` | [sdk-patches](../sdk-patches) 0006 (variant D) |
| `/oem/usr/share/vima/sc3336-30.ko` | `58bc20e2aee467189d873e7647d5023f` | unmodified SDK driver |
| `/oem/usr/share/iqfiles/sc3336_CMK-OT2119-PC1_30IRC-F16.json` | `e96785879c4ad2eba6b486c96420dc32` | [`../sc3336-60fps/iq/vytvor-iq.sh`](../sc3336-60fps/iq/vytvor-iq.sh) |
| `/oem/usr/share/rkipc-300w.ini` (same as `/userdata/rkipc.ini`) | `b2322e1fcad29a9d2594f8663b2bc7d8` | [`rkipc-300w.ini`](rkipc-300w.ini) in this folder |

`rkipc-300w.ini`: 1152×648 @ 55 fps, encoder wrap (`enable_wrap`, `buffer_line`, `wrap_max_fps` in `[video.source]`), anti-flicker off. It is the SDK ini from patch 0002 run through [`ini-60fps.awk`](../sc3336-60fps/rkipc/ini-60fps.awk) with `FPS=55`, plus the wrap keys written by [`nasad-wrap.sh zap`](../rkipc-wrap/nasad-wrap.sh) and `power_line_frequency_mode = close`.

`vima-ctl` switches between the 30 and 60 fps camera modes by copying `sc3336-30.ko` or `sc3336-60.ko` to `/oem/usr/ko/sc3336.ko` and rebooting.
