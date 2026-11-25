# How it works

## Architecture

```
tapecap.service (systemd, runs as your user)
└── python -m tapecap                          main process
    ├── Capture thread      (capture.py)        device detection, start/stop, recording, trimming
    ├── Web server thread   (web.py)            control panel + JSON API on :8787
    └── Processor           (processor.py)      separate child process, nice 15, idle I/O
          └── upscale.py                        Real-ESRGAN chunks (optional)
```

- **Capture** runs at normal priority in the main process. All the heavy lifting is done by ffmpeg subprocesses; Python only looks at small thumbnails.
- **Processing** runs as a **separate low-priority process**. It can use every spare CPU core without ever making the recorder drop frames. If it crashes it's restarted automatically after 10 s.
- The two talk through files only:
  - the processor writes its status to `~/.local/state/tapecap/processor.json`
  - finished originals appear in the originals folder
  - the panel requests a cancel or retry through marker files and `.processed.json` / `failed.json`

## Device detection

At startup, and again whenever the device goes missing or settings change, TapeCap does the following (`devices.py`):

1. Lists `/sys/class/video4linux/video*` and keeps only devices on the **USB bus** that offer capture formats. That skips codec, ISP and metadata nodes.
2. Uses the stable `/dev/v4l/by-id/…` name when there is one, so it doesn't matter which `/dev/videoN` number the stick gets.
3. Reads the supported formats with `v4l2-ctl --list-formats-ext` and picks the best one (see [`video_format`](configuration.md#capture-device)).
4. Finds the audio input by following each ALSA card's sysfs path to its **USB parent device**. The card that shares a USB device with the video node is the stick's own audio.
5. Lists GPUs with `vulkaninfo --summary` and classes each as discrete ✅, integrated ⚠️ or CPU ❌.

## Start / stop detection

The capture stick and VCR show a **solid colour** (usually blue) when nothing is playing.

While idle, one ffmpeg process decodes the stick at **5 frames per second, scaled to 320×240**, and pipes raw RGB to Python. For each frame:

```
take every 2nd pixel (160×120 grid)
median colour = per-channel median of all pixels
close         = pixels within ±blank_tolerance (24) of the median on every channel
blank         = close ≥ blank_fraction (92 %) of pixels
```

A solid blue or black frame scores about 100 %. Real footage, even a dark room, a sky or static/snow, scores far lower because of noise and detail. The test costs about 5 % of one CPU core.

- **Start:** `start_seconds` × 5 consecutive non-blank frames (1 s by default).
- **Recording:** a **single** ffmpeg process reads the device at full rate (720×480 @ 30 + ALSA audio) and uses a filter `split` to:
  - write the recording (x264 `veryfast`, CRF 20, AAC 160 kb/s, with `aresample=async` to keep audio in sync) to `work_dir/<name>.mkv`. Matroska survives an unexpected stop.
  - keep sending the 5 fps thumbnails for analysis and the live preview.
- **Stop:** `stop_blank_seconds` × 5 consecutive blank frames. Or **Stop** pressed in the panel, or `max_record_minutes` reached, or the device unplugged.
- **Finalise:**
  1. The recording is cut at **last non-blank frame + 1 s**, with the video stream copied (no re-encode).
  2. The audio is loudness-normalised (`loudnorm`).
  3. The result is written to `originals/<name>.mp4.part`, then renamed atomically to `.mp4`, so the processor never sees a half-written file.
  4. The `.mkv` is deleted.
- Recordings with less than `min_keep_seconds` of picture are discarded.

### Crash recovery

If the service stops mid-recording (restart, crash or power cut), the `.mkv` stays in the working folder. At the next start it's normalised and saved as `<name>_recovered.mp4` in the originals folder, where it gets processed like any other tape. Leftover `.part` files are removed.

## Processing pipeline

For each new `PREFIX_YYYY-MM-DD_HH-MM-SS[_recovered].mp4` in the originals folder that isn't listed in `library/.processed.json` or in the failure list, oldest first:

| # | Step | How |
|---|---|---|
| 1 | **Edge detection** | ffmpeg `cropdetect` on 60 s from the middle of the tape. Each side is clamped to 16 px, so a dark scene can't make it cut into the picture. |
| 2 | **Chapters** | `scdet` scene-change scores on a 180×120 copy. Cuts scoring ≥ `chapter_sensitivity` and at least 30 s apart become chapters; none are placed in the last 15 s. Shots longer than 10 minutes get an extra chapter every 5 minutes. |
| 3 | **Transcription** | Audio is decoded at 16 kHz mono after rumble and hiss filtering, and passed to **faster-whisper** (int8, CPU) with voice-activity detection. Segments that look like hallucinations or background mumble are dropped: `no_speech_prob ≥ 0.6`, `avg_logprob ≤ −1`, or `compression_ratio ≥ 2.4`. |
| 4 | **Contact sheet** | One frame 2 s after each chapter start, padded to at least 8 and capped at 16, with timestamps, tiled 4 across. |
| 5 | **Stabilize – analyse** | `vidstabdetect` (shakiness 6, accuracy 15) on the cropped and scaled picture, writing `motion.trf`. |
| 6 | **Enhance + encode** | The video filters (below) and the audio chain `highpass=80 Hz` → `afftdn` (hiss) → `loudnorm`. Encoded as x264 CRF 20 + AAC 192 kb/s, with chapters and a `mov_text` subtitle track. |
| 7 | **Upscale** *(optional)* | Real-ESRGAN in 20 s chunks. See [Upscaling](upscaling.md). |
| 8 | **Save** | `transcript.txt` and `info.txt` are written, everything is moved into `library/<name>/`, the tape is recorded in `.processed.json`, and a notification is sent. |

Video filters in step 6:
1. `crop` to the detected edges
2. `scale` to the output size (for example 640×480) with lanczos, plus `setsar=1` for square pixels
3. `vidstabtransform` (smoothing 10/20/35, optimal zoom, bicubic)
4. `unsharp`

### Why the picture is re-scaled

Capture sticks sample 720 pixels across, but the 4:3 picture area of analogue video is about 704 of them. Players then show the 720×480 frame with square pixels, so everything looks **12 % too wide**. Cropping the edges and scaling to 640×480 with square pixels gives the correct shape on every player.

### Why there's no deinterlacing

Many capture sticks, the MS210x included, already deliver progressive frames. TapeCap was tested with ffmpeg's `idet`, which found 0 interlaced frames. If your device delivers interlaced video (comb-like lines on movement), please open an issue.

### Resume and checkpoints

Each tape has a work folder: `work_dir/process/<name>/`.
- The results of steps 1–3 are cached in `progress.json` along with a snapshot of the processing settings.
- The stabilization analysis and each finished upscale chunk are kept on disk.

After a restart the processor skips whatever is already done. If the processing settings changed in the meantime, the cache is thrown away and the tape starts again.

### Failure handling

If a step fails, the tape goes into `~/.local/state/tapecap/failed.json` with the error message, a notification is sent, and the processor moves on to the next tape. Failed tapes aren't retried automatically. Press **Retry** in the Library. **Cancel this tape** in the panel works the same way, with the error *"Cancelled from the control panel"*.

## Files and folders

| Path | Contents |
|---|---|
| `~/.config/tapecap/config.json` | Settings |
| `~/.local/state/tapecap/processor.json` | Live processing status, read by the panel |
| `~/.local/state/tapecap/failed.json` | Tapes whose processing failed or was cancelled |
| `~/.local/state/tapecap/notify.log` | Every notification sent, plus Hermes's JSON reply |
| `<work_dir>/<name>.mkv` | The recording in progress |
| `<work_dir>/last_tape_thumb.jpg` | Thumbnail attached to the "tape finished" notification |
| `<work_dir>/process/<name>/` | Temporary processing files, deleted when the tape is done |
| `<originals_dir>/<name>.mp4` | Trimmed capture |
| `<library_dir>/.processed.json` | Finished tapes: original name → folder, time, duration, upscaled yes/no |
| `<library_dir>/<name>/` | Finished tape |

Logs go to the systemd journal: `journalctl -u tapecap -f`.
