# API reference

The control panel is a single HTML page that talks to a small JSON API. You can use the same API from scripts, home-automation systems or AI agents.

- Base URL: `http://<host>:8787`
- All responses are JSON unless noted.
- There is **no authentication**. See [Security](#security).

## Status

### `GET /api/status`

```json
{
  "state": "recording",
  "detail": "Tape playing – recording VHS_2026-11-24_21-04-10.mkv",
  "video": {"path": "/dev/v4l/by-id/usb-MACROSILICON_AV_TO_USB2.0_20150130-video-index0", "name": "AV TO USB2.0"},
  "audio": "hw:CARD=MS210x,DEV=0",
  "format": {"input_format": "mjpeg", "width": 720, "height": 480, "fps": 30},
  "recording": {"file": "/mnt/usb/recording/VHS_2026-11-24_21-04-10.mkv", "started": "2026-11-24 21:04:10",
                "elapsed": 812.4, "blank_seconds": 0, "size": 402653184},
  "preview_age": 0.12,
  "events": [{"time": "2026-11-24 21:04:10", "msg": "Tape playing – recording …"}],
  "processor": {"state": "working", "tape": "VHS_2026-11-24_10-08-12.mp4", "step": "Transcribing speech",
                "step_pct": 41.5, "pct": 23.0, "started": "2026-11-24 21:10:00", "queue": [],
                "upscale": "no supported graphics card (dedicated Vulkan GPU) found", "last": {…}},
  "disk": {"free": 870540046336, "total": 1000168484864},
  "library_dir": "/mnt/usb/library",
  "host": "dryspot"
}
```

| `state` | Meaning |
|---|---|
| `starting` | Service just started |
| `waiting_drive` | A save folder is on an fstab drive that isn't mounted |
| `no_device` | No capture device, or the chosen one is unplugged |
| `idle` | Watching the input, nothing playing |
| `recording` | A tape is being recorded (`recording` has the details) |
| `saving` | Trimming and normalising the finished recording |
| `error` | See `detail`. TapeCap retries automatically. |
| `stopped` | Service shutting down |

`recording` is `null` unless the state is `recording` or `saving`. `processor.state` is `idle`, `working` or `stopped`.

### `GET /api/preview.png`
The latest analysis frame (320×240 PNG): what the capture stick sees right now. Returns 404 if no frame has arrived yet. `preview_age` in the status tells you how fresh it is.

## Control

### `POST /api/stop`
Stops the current recording and saves it. Body: `{}`. Returns `{"ok": true}`.

### `POST /api/cancel`
Cancels the tape currently being processed. It's added to the failure list and can be retried. Returns `{"ok": true}`.

### `POST /api/reprocess`
```json
{"name": "VHS_2026-11-23_00-04-16.mp4"}
```
Removes the tape from the done and failed lists and clears its work folder, so the processor picks it up again with the current settings. Returns 404 if the original doesn't exist.

### `POST /api/rescan`
Re-detects devices and GPUs (returns the same as `/api/devices`) and makes the capture engine re-read its settings. That happens immediately when idle, or after the current recording.

## Settings

### `GET /api/config`
```json
{"config": {…current values…}, "defaults": {…}, "choices": {"stabilize": ["off","light","normal","strong"], …}}
```

### `POST /api/config`
Send only the keys you want to change:
```bash
curl -X POST http://dryspot.local:8787/api/config \
     -H 'Content-Type: application/json' \
     -d '{"stabilize": "strong", "hiss_reduction": "light"}'
```
- Success: `{"ok": true, "applied": "now" | "after this recording", "note": ""}`
- Error (HTTP 400, nothing saved): `{"ok": false, "errors": {"stop_blank_seconds": "must be between 3 and 600"}}`

Folder settings are created and write-tested before saving. See [Configuration](configuration.md) for every key.

## Devices

### `GET /api/devices` (`?fresh` to bypass the 30 s cache)
```json
{
  "video": [{"path": "/dev/v4l/by-id/…-video-index0", "dev": "/dev/video0", "name": "AV TO USB2.0",
             "format_ids": ["mjpeg:720x480@30", "mjpeg:640x480@30", …], "best": {…}}],
  "audio": [{"path": "hw:CARD=MS210x,DEV=0", "name": "MS210x", "usb": "/sys/devices/…/1-1"}],
  "gpus": [{"index": 0, "name": "V3D 7.1.10.2", "type": "integrated_gpu", "use": "slow"}],
  "upscaler": null,
  "upscale_plan": {"gpus": null, "reason": "Real-ESRGAN (realesrgan-ncnn-vulkan) is not installed"},
  "whisper": true,
  "hermes": "/home/user/.local/bin/hermes",
  "drives": [{"path": "/mnt/usb", "fs": "ntfs3", "free": 870540046336, "total": 1000168484864}]
}
```

## Library and files

### `GET /api/library`
A list, newest first:
```json
[{"name": "VHS_2026-11-23_00-04-16", "status": "done", "folder": "VHS_2026-11-23_00-04-16",
  "files": ["VHS_2026-11-23_00-04-16.mp4", "VHS_2026-11-23_00-04-16.srt", "contact_sheet.jpg", "info.txt", "transcript.txt"],
  "length": "52:31", "picture": "640x480", "size": 741000000, "original": "VHS_2026-11-23_00-04-16.mp4"}]
```
`status` is one of `done`, `processing`, `queued` or `failed` (with `error`).

### File downloads

| URL | Serves |
|---|---|
| `GET /files/lib/<folder>/<file>` | A file from the library. Supports HTTP Range requests, so videos can be streamed and seeked. |
| `GET /files/lib/<folder>/<name>.vtt` | The `.srt` converted to WebVTT on the fly (for browser subtitles) |
| `GET /files/orig/<file>` | A file from the originals folder |
| `GET /download/<folder>/<file>` | Same as `/files/lib/…`, sent as an attachment |

Add `?download` to any `/files/…` URL to get a "save as" download. Paths are confined to the library and originals folders.

## Examples

```bash
# Is it recording?
curl -s http://dryspot.local:8787/api/status | jq -r .state

# Save the live picture
curl -s -o now.png http://dryspot.local:8787/api/preview.png

# Wait until the current tape is finished
until [ "$(curl -s http://dryspot.local:8787/api/status | jq -r .state)" = idle ]; do sleep 10; done

# Re-process every finished tape with new settings
curl -s http://dryspot.local:8787/api/library | jq -r '.[] | select(.original) | .original' |
  while read f; do curl -s -X POST -H 'Content-Type: application/json' \
       -d "{\"name\":\"$f\"}" http://dryspot.local:8787/api/reprocess; done
```

## Security

The panel has **no login**. Anyone who can reach port 8787 can see the live picture, watch and download your tapes, and change settings. It's meant for a home network only.

- **Don't forward port 8787 on your router.**
- To restrict it to the computer itself, set `web_bind` to `127.0.0.1`. You can then put it behind a reverse proxy with authentication (Caddy, nginx), or use a VPN such as Tailscale or WireGuard for remote access.
- The API only reads and writes inside the configured folders. File paths are checked so they can't escape the library and originals folders.
