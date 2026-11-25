# Development

## Code layout

```
tapecap/
├── install.sh              installer (apt packages, venv, Real-ESRGAN, systemd unit)
├── tapecap.service         example unit (install.sh generates the real one)
├── tapecap/
│   ├── __main__.py         entry point: starts capture thread, web server, processor process
│   ├── config.py           defaults, choices, load/save/validate of config.json
│   ├── devices.py          V4L2/ALSA/Vulkan detection, format choice, upscale plan
│   ├── capture.py          Capture thread: idle monitor, recorder, blank detection, finalise, recovery
│   ├── processor.py        processing worker (separate process): pipeline, checkpoints, status
│   ├── upscale.py          chunked Real-ESRGAN upscaling
│   ├── notify.py           Hermes notifications
│   ├── web.py              HTTP server + JSON API (stdlib http.server)
│   ├── util.py             logging, ffprobe wrapper, PNG encoder, fstab/mount checks, JSON I/O
│   └── static/index.html   the whole control panel (vanilla HTML/CSS/JS, no build step)
└── docs/
```

Dependencies are deliberately small:
- Python stdlib, plus `numpy` for frame analysis and `faster-whisper` for transcription, which is optional and skipped if it's missing
- ffmpeg/ffprobe
- `v4l2-ctl` and `vulkaninfo` for detection

There's no web framework and no frontend build.

## Running from source

```bash
python3 -m venv venv && venv/bin/pip install numpy faster-whisper
# stop the service first if it's installed – the capture device can only be opened once
sudo systemctl stop tapecap
venv/bin/python -m tapecap
```

Use a separate config and state folder for experiments:
```bash
export TAPECAP_CONFIG=/tmp/tc/config.json TAPECAP_STATE=/tmp/tc/state
echo '{"originals_dir":"/tmp/tc/orig","library_dir":"/tmp/tc/lib","work_dir":"/tmp/tc/work","web_port":8788}' > /tmp/tc/config.json
venv/bin/python -m tapecap
```

## Testing without a tape deck

**Processing only.** Run just the processor and drop a clip into the originals folder:
```bash
mkdir -p /tmp/tc/orig
ffmpeg -ss 120 -t 60 -i some_home_video.mp4 -c copy /tmp/tc/orig/VHS_2000-01-01_00-00-00.mp4
TAPECAP_CONFIG=/tmp/tc/config.json TAPECAP_STATE=/tmp/tc/state venv/bin/python -m tapecap.processor
```

**Upscaling without a GPU.** Point `upscale_binary` at a stand-in script and set `"upscale": "on", "upscale_gpu": "0"`:
```bash
#!/bin/bash
# fake-esrgan: same arguments as realesrgan-ncnn-vulkan, plain ffmpeg scaling
while [ $# -gt 0 ]; do case $1 in -i) IN=$2; shift;; -o) OUT=$2; shift;; -s) S=$2; shift;; esac; shift; done
for f in "$IN"/*.png; do ffmpeg -v error -y -i "$f" -vf "scale=iw*$S:ih*$S" "$OUT/$(basename "$f")"; done
```

**Capture without a tape.** Use a virtual V4L2 device. Install `v4l2loopback-dkms`, then:
```bash
sudo modprobe v4l2loopback video_nr=9 card_label="Fake VCR" exclusive_caps=1
# "tape playing":
ffmpeg -re -i some_home_video.mp4 -vf scale=720:480 -pix_fmt yuyv422 -f v4l2 /dev/video9
# "tape ended" (solid blue):
ffmpeg -re -f lavfi -i color=c=0x0000bf:s=720x480:r=30 -pix_fmt yuyv422 -f v4l2 /dev/video9
```
Set **Video device** to `/dev/video9` and **Audio input** to `none`. The loopback device isn't on USB, so Automatic won't pick it.

## Checks before committing

```bash
for f in tapecap/*.py; do python3 -m py_compile "$f"; done
```

## Design notes

- **One ffmpeg process while recording.** The device can only be opened once, so the recorder uses a filter `split` both to write the file and to feed the 5 fps analysis frames to Python.
- **Matroska while recording, MP4 at the end.** MKV survives being killed mid-write. The final MP4 is written to `.part` and renamed atomically.
- **The processor is a separate process**, so the GIL, CPU load and `nice` can never interfere with capture timing.
- **State in plain JSON files** that you can read, edit or back up by hand: `.processed.json` in the library travels with the library.
- **No auto-titles.** Transcript and vision-model titles were tested and were too often wrong.

## Ideas / roadmap

- Pre-roll buffer so not even the first second of a tape is missed
- Join several files from the same tape into one
- Editable titles and notes in the Library, written into the MP4 metadata
- Search inside transcripts from the panel
- Optional login for the panel
- Export straight to a Jellyfin/Plex library folder structure

Pull requests welcome.
