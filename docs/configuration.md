# Configuration

Settings are stored in `~/.config/tapecap/config.json`. You can change them in the control panel's **Settings** page (recommended), through the [API](api.md), or by editing the file and restarting the service. The file only needs the settings you change; anything missing uses the default.

```json
{
  "library_dir": "/mnt/usb/library",
  "originals_dir": "/mnt/usb/originals",
  "work_dir": "/mnt/usb/work",
  "stabilize": "strong",
  "notify": "hermes",
  "notify_target": "telegram:123456789"
}
```

---

## Capture device

| Setting | Default | Description |
|---|---|---|
| `video_device` | `auto` | `auto` uses the first **USB** video capture device found. Built-in cameras, codecs and the Raspberry Pi's ISP are skipped. Or give a path, preferably the stable `/dev/v4l/by-id/…` one rather than `/dev/videoN`. If the chosen device is unplugged, TapeCap waits for it instead of switching to another one. |
| `audio_device` | `auto` | `auto` uses the ALSA capture input that sits on the **same USB device** as the video, so the stick's own audio, falling back to the first USB audio input. `none` records video only. Or give an ALSA name such as `hw:CARD=MS210x,DEV=0`; `arecord -L` lists them. |
| `video_format` | `auto` | `auto` picks in this order: 720×480 @ 30 (NTSC), 720×576 @ 25 (PAL), 640×480 @ 30, preferring MJPEG. Or a specific format from the dropdown, written as `mjpeg:720x480@30`. |

> **PAL tapes** (Europe, Australia…): if your stick offers 720×576, `auto` will only choose it when it doesn't offer 720×480 @ 30. Pick `…720x576@25` by hand for PAL sources.

## Save locations

| Setting | Default | Description |
|---|---|---|
| `library_dir` | `~/TapeCapture/library` | Finished, enhanced tapes, one folder per tape |
| `originals_dir` | `~/TapeCapture/originals` | Trimmed raw captures, never modified after saving |
| `work_dir` | `~/TapeCapture/work` | The recording in progress, plus temporary processing files. Can need tens of GB during upscaling. Keep it on the big drive. |
| `name_prefix` | `VHS` | File names are `PREFIX_YYYY-MM-DD_HH-MM-SS`. Letters and numbers only. |

All three folders must be full paths. They're created and tested for write access when you save.

## Start & stop

| Setting | Default | Range | Description |
|---|---|---|---|
| `start_seconds` | `1.0` | 0.2–30 | Picture must be present this long before recording starts. Avoids false starts from a flicker. |
| `stop_blank_seconds` | `15` | 3–600 | Blank screen this long means the tape has finished. Raise it if your tapes have long blank gaps that you want kept in one file. |
| `min_keep_seconds` | `20` | 0–3600 | Recordings with less real picture than this are thrown away (for example a moment of picture while rewinding). |
| `max_record_minutes` | `0` | 0–1000 | Safety stop. `0` means no limit. Set it to about 10 minutes more than your longest tape (for example `250` for T-240 tapes) if your VCR shows snow instead of blue at the end. |
| `record_quality` | `20` | 14–30 | x264 CRF of the capture. Lower means better quality and bigger files; each step of 6 roughly doubles or halves the size. 18–22 is visually lossless for tape. |
| `blank_tolerance` | `24` | 4–80 | *Advanced.* How far (0–255) a pixel may differ from the frame's typical colour and still count as "the same colour". |
| `blank_fraction` | `0.92` | 0.5–0.999 | *Advanced.* The share of pixels that must be "the same colour" for a frame to count as blank. |

## Sound

| Setting | Default | Description |
|---|---|---|
| `normalize_audio` | `true` | Evens out loudness to `loudness_target` (EBU R128 loudnorm, peaks limited to −2 dBTP). Applied to the originals and the library copies. |
| `loudness_target` | `-14` | In LUFS. −14 is YouTube/Spotify level, −16 is a little quieter, −12 louder. Range −30 to −8. |
| `rumble_filter` | `true` | Removes sound below 80 Hz: wind, handling noise, motor hum. Voices aren't affected. |
| `hiss_reduction` | `medium` | Tape hiss reduction (FFT noise reduction): `off`, `light`, `medium` or `strong`. Too strong can make voices sound "underwater". Applied to the library copy only. |

## Picture

| Setting | Default | Description |
|---|---|---|
| `crop_edges` | `true` | Detects black borders and crops them, at most 16 px per side, so real picture is never cut. |
| `aspect` | `4:3` | Output shape. Nearly all tapes are 4:3. `16:9` is for widescreen camcorder recordings. |
| `output_height` | `480` | Output height in pixels; the width follows from the aspect (480 → 640×480). 480 keeps all the detail a tape really has. Use upscaling rather than this to go bigger. |
| `stabilize` | `normal` | Camera-shake removal: `off`, `light` (smoothing 10), `normal` (20) or `strong` (35). Stronger is steadier but zooms in a little more, and pans can look "floaty". |
| `sharpen` | `true` | A light unsharp mask after stabilization. |

## Upscaling

See **[Upscaling](upscaling.md)** for a full explanation.

| Setting | Default | Description |
|---|---|---|
| `upscale` | `auto` | `off`: never. `auto`: only when a **dedicated** (discrete) Vulkan GPU is found. `on`: also use built-in/integrated graphics, which is very slow. |
| `upscale_factor` | `2` | `2`, `3` or `4`. 640×480 becomes 1280×960, 1920×1440 or 2560×1920. |
| `upscale_model` | `realesr-animevideov3` | `realesr-animevideov3`: fast, made for video. `realesrgan-x4plus`: slower and more detailed, for real-world footage. `realesrgan-x4plus-anime`: for cartoons. The x4 models always run at 4× and are then resized to your factor. |
| `upscale_gpu` | `auto` | `auto` uses all dedicated GPUs. Or give card numbers from *Settings → This computer*, for example `0` or `0,1`. |
| `upscale_binary` | *(empty)* | Path to `realesrgan-ncnn-vulkan`. When empty, TapeCap searches `PATH` and `./tools/realesrgan/`. |
| `keep_standard_version` | `true` | Also keep the non-upscaled copy (`<name>_SD.mp4`) next to the upscaled one. |

## Transcripts & chapters

| Setting | Default | Description |
|---|---|---|
| `transcribe` | `true` | Speech-to-text with faster-whisper, run offline on the CPU. Creates subtitles and `transcript.txt`. |
| `whisper_model` | `small.en` | `tiny.en`, `base.en`, `small.en` or `medium.en` (English), or `tiny`, `base`, `small` or `medium` (multilingual). On a Pi 5, `small.en` runs at about 1–1.5× real time and `base.en` about 3× faster but less accurately. Avoid `medium` on a Pi. |
| `language` | `en` | Language code for multilingual models (`de`, `es`, `fr`…). Leave it empty to auto-detect. Ignored by `.en` models. |
| `chapters` | `true` | Adds chapters at scene cuts (camera stop/start), at least 30 s apart. Long continuous shots also get a chapter every 5 minutes. |
| `chapter_sensitivity` | `15` | Scene-change score needed for a chapter (3–60). Lower gives more chapters. |
| `contact_sheet` | `true` | Thumbnail grid (`contact_sheet.jpg`), one image per chapter, 8–16 images. |

## Notifications

| Setting | Default | Description |
|---|---|---|
| `notify` | `off` | `hermes` sends messages through [Hermes Agent](notifications.md). |
| `notify_target` | `telegram` | Hermes target, for example `telegram:123456789` (a chat ID). |
| `hermes_bin` | *(empty)* | Path to the `hermes` command. Empty means search `PATH` and `~/.local/bin`. |

## System

| Setting | Default | Description |
|---|---|---|
| `process_threads` | `3` | CPU threads for transcription. On a 4-core Pi, keep one core free for recording. |
| `web_port` | `8787` | Control panel port. Needs a service restart. |
| `web_bind` | `0.0.0.0` | Address the panel listens on. Use `127.0.0.1` to allow only the computer itself (for example behind a reverse proxy). Needs a restart. |

---

## Which settings need what

| Change | Takes effect |
|---|---|
| Capture device, format, start/stop, record quality, save folders | Immediately when idle; after the current recording otherwise |
| Sound / picture / upscaling / transcripts / chapters | From the next tape processed. Use **Re-process** in the Library to apply them to tapes already done. |
| `web_port`, `web_bind` | After `sudo systemctl restart tapecap` |

If processing is interrupted and the processing-related settings have changed since it started, TapeCap starts that tape over rather than mixing old and new settings.
