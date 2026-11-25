# TapeCap – automatic VHS / camcorder tape digitizer

Insert a tape, press **Play**, walk away. TapeCap:

1. **Finds the capture device** at startup (USB composite stick: video + its own audio input), and keeps looking if it is unplugged.
2. **Starts recording** when a picture appears (the stick shows solid blue/black when nothing plays).
3. **Stops** when the screen has been blank for 15 s, **trims the blank end**, levels the volume and saves the original.
4. **Processes** it in the background at low priority:
   - crops the black edges and fixes the aspect ratio (4:3)
   - stabilizes shaky footage
   - reduces hiss and rumble and evens out the loudness
   - speech-to-text subtitles and transcript (faster-whisper)
   - chapters at camera stop/start points, plus a contact sheet
   - **AI upscaling** (Real-ESRGAN) when the computer has a supported graphics card
5. Optionally sends a phone message through Hermes Agent.

## Control panel
Open `http://<computer-name>.local:8787/` from any browser on the network. It has three tabs:
- **Status**: live picture, recording state and a Stop button, processing progress, and the activity log.
- **Library**: every tape's contact sheet. You can play it in the browser (with subtitles), download it, read the transcript, or re-process it.
- **Settings**: capture device, save folders and every option above. Changes apply immediately, or after the current recording.

## Install
```
./install.sh
```
Installs ffmpeg and the Python environment, downloads Real-ESRGAN on x86-64 PCs, and creates and starts `tapecap.service`.
Settings live in `~/.config/tapecap/config.json`. Logs: `journalctl -u tapecap -f`.

## Upscaling GPUs
Any **Vulkan** graphics card works with Real-ESRGAN ncnn-vulkan:
- NVIDIA GTX 600 or newer (Kepler cards such as the Quadro K2000 need the 470 driver)
- AMD HD 7000 / RX or newer

With upscaling on **Auto**, only dedicated cards are used. Built-in graphics (like the Raspberry Pi's) are too slow for whole tapes. To use two cards, set the cards field to `0,1`.

## Folders
| Folder | Contents |
|---|---|
| library | `<name>/<name>.mp4`, `.srt`, `transcript.txt`, `contact_sheet.jpg`, `info.txt` (and `<name>_SD.mp4` if upscaled) |
| originals | trimmed raw captures, never modified |
| work | recording in progress and temporary processing files; interrupted jobs resume from here |
