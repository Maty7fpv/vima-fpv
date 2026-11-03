# Ground station

Linux laptop with an RTL8812AU adapter (svpcom driver) and wfb-ng built in `~/wfb-ng`, with the ground key `gs.key` there.

| File | What it does |
|---|---|
| `tunel.sh` | IP tunnel to the air unit over the air (laptop 10.5.0.1 ↔ board 10.5.0.2) and the root helper for the control panel |
| `gs-video.sh`, `prijem.py`, `prijem.conf` | Receive the video, show it full screen, ask for a keyframe after packet loss, report link quality 5× per second |
| `ovladani.py` | Control panel and command line: bitrate, fps, resolution, TX power, channel and band, adaptive link (`ovladani.py okno` opens the window) |
| `deska.sh`, `rx-test.sh` | Board status and channel switch, receive test |
| `flash.sh` | Flashes a firmware image (needs Rockchip's `upgrade_tool`, not included) |
| `kanal.conf` | Channel shared by the scripts and the laptop's TX power for the tunnel |

Usual start: `tunel.sh`, then `gs-video.sh`, then `ovladani.py okno`. If the board and laptop end up on different channels: `ovladani.py najdi`.

The scripts still use absolute paths from the development laptop (`/home/mikes/vima-board`, `/home/mikes/wfb-ng`).
