# Air unit

Luckfox Pico Pro Max (Rockchip RV1106G3) running the Luckfox Pico SDK (Buildroot 2023.02.6, Linux 5.10.160).

| Folder | What's inside |
|---|---|
| [`overlay`](overlay) | Files added to the board's root filesystem (SDK overlay `overlay-vima`): boot services, `vima-wfb` (Wi-Fi card, monitor mode, power caps, `wfb_tx`, IP tunnel), `vima-video.py` (camera RTP → `wfb_tx`), `vima-ctl.py` (control from the ground over the tunnel, UDP 5900), `vima.conf` |
| [`sdk-patches`](sdk-patches) | Changes to the SDK itself, one patch per topic, with license and firmware status |
| [`rkipc-wrap`](rkipc-wrap) | Builds rkipc with encoder wrap outside the SDK and copies it to the board's `/oem` |
| [`sc3336-60fps`](sc3336-60fps) | 1152×648 @ 60 fps camera mode: ISP tuning generator (`iq/vytvor-iq.sh`), rkipc ini script, deploy scripts |
| [`tun`](tun) | Builds `tun.ko` from the SDK kernel's own `drivers/net/tun.c` (the SDK kernel doesn't include it) |
| [`deska-20261103`](deska-20261103) | What runs on the board now outside the firmware: checksums and the rkipc ini |

The scripts in `rkipc-wrap` and `sc3336-60fps/deska` are development scripts. They use paths and build outputs from the development laptop, so for now read them as a record of how the board was set up.

## Not in this repository

- **wfb-ng keys.** Whoever has either `drone.key` or `gs.key` can decrypt the video and pretend to be the ground station, including sending commands to `vima-ctl`. Generate your own pair with `wfb_keygen` from wfb-ng, put `drone.key` in `overlay/etc/vima/drone.key` and keep `gs.key` on the ground station. Never commit either one.
- **SSH key.** For key login, add your own public key as `overlay/root/.ssh/authorized_keys` (`S01vimaroot` fixes its owner and permissions at boot).
- **Binaries.** Cross-compiled with the SDK toolchain and placed in the overlay: `88XXau_wfb.ko` ([svpcom/rtl8812au](https://github.com/svpcom/rtl8812au) v5.2.20, commit `6e75916`) and `tun.ko` in `lib/modules/5.10.160/extra/`, `wfb_tx`, `wfb_rx`, `wfb_tx_cmd`, `wfb_tun` ([wfb-ng](https://github.com/svpcom/wfb-ng) 25.01) in `usr/bin/`.
- **Firmware images.** Every image built with the overlay contains `drone.key`, so images are not published.

## Power limits

`vima-wfb` and `vima-ctl.py` cap the TX power index at 50 on 2.4 GHz and 20 on 5.8 GHz. The resulting EIRP is only estimated from RSSI (about ±10 dB) and has not been measured yet.
