# Troubleshooting & FAQ

Start with the **Status** page (state, detail line, live picture and Activity log), then the logs:

```bash
journalctl -u tapecap -n 100 --no-pager      # recent log
journalctl -u tapecap -f                     # follow live
systemctl status tapecap
```

## Recording

### The tape is playing but the state stays "Waiting for a tape"
The live picture shows what the stick receives. If it's **solid blue**, no video is reaching it:
- Is the yellow cable in the VCR's **VIDEO OUT** (not IN)?
- Is a TV/VCR combo set to **VCR**?
- Is the camcorder in **PLAY/VTR** mode, with AV out enabled?
- Is the tape really playing, rather than still rewinding?
- Is the stick switched to the right input (composite or S-Video)? Check with `v4l2-ctl -d /dev/video0 --get-input`.

If the live picture shows the tape but TapeCap still doesn't start, the picture is being judged as blank. That's very dark or very flat footage. Raise `blank_fraction` (for example to 0.97) or lower `blank_tolerance` (for example to 12), so only a truly solid screen counts as blank.

### It records, but never stops at the end of the tape
Your VCR shows **snow/static** instead of a blue screen when the tape runs out, and snow counts as picture.
- Turn on the VCR's "blue back" / "blue background" setting, or
- set **Maximum recording length** (for example 250 minutes), or
- press **Stop recording now** in the panel when you see snow.

### One tape turned into several files
The tape has blank gaps longer than `stop_blank_seconds` (15 s) between recordings. Nothing was lost. Raise the setting to keep long gaps in one file.

### The start of the tape is missing about a second
Recording starts once there has been a picture for `start_seconds` (1 s), plus about half a second to start the recorder. Lower `start_seconds` to 0.4 if your tapes start right away with something important. Most tapes have a few seconds of lead-in anyway.

### "No capture device"
- Run `v4l2-ctl --list-devices` and check that the stick is listed. Try another USB port or cable, preferably directly on the computer rather than through a hub.
- If you chose a device by hand and it isn't connected, the detail line says so. Set **Video device → Automatic**.
- Built-in webcams and non-USB devices are ignored by Automatic. Choose them by hand.

### "Device or resource busy" in the log
Another program has the capture device open: a second TapeCap, `ffmpeg`, VLC, OBS, or an old capture script. Only one program can use it at a time. `fuser -v /dev/video0` shows which.

### No sound in the recordings
- The Status page shows **Audio: none**: no USB audio input was found. Check `arecord -l`, and set **Audio input** by hand.
- The stick's audio is muted or turned down. Run `alsamixer -c <card>`, press F4 for Capture, and turn it up.
- The red/white cables are in the VCR's audio **IN** jacks.

### Sound is too quiet or too loud
Raise or lower **Loudness target** (−14 is standard; −12 is louder). It's applied to every new tape. Use **Re-process** for tapes already done.

### Picture or sound out of sync
Usually a USB bandwidth problem: the stick is on a hub, or shares a port with a busy disk. Connect the stick directly. Long tapes from the same session drifting in sync is a known weakness of very cheap sticks; report it with the log if you see it.

### Small blocky squares in the picture
On **Digital8/MiniDV** tapes these are dropouts on the tape itself. Cleaning the camcorder heads, or playing the tape again, sometimes helps. Analogue tapes show horizontal streaks instead.

### "Waiting for drive /mnt/usb"
A save folder is on a drive listed in `/etc/fstab` that isn't mounted. Plug it in, or run `sudo mount /mnt/usb`. TapeCap carries on automatically once the drive is mounted.

## Processing

### A tape shows "failed" in the Library
The error is shown under it, and in full in the log. Common causes:
- **Disk full**: free some space, then press **Retry**.
- **Corrupt original** (power cut while saving): play the original in VLC. Recovered files are named `…_recovered.mp4`.
- **Upscaler error**: check the GPU driver with `vulkaninfo --summary`. Set **AI upscaling → off** to get the tape done without it.

### Processing is very slow
Transcription is usually the slowest step on a Pi. Choose `base.en` (about 3× faster), or turn transcription off. Stabilization can also be set to `off`. Upscaling time depends entirely on the GPU; see [Upscaling](upscaling.md).

### Stabilized video looks floaty or zoomed in
Use **Stabilize: light**, or `off` for tripod footage. Then **Re-process** the tape.

### Voices sound "underwater" or metallic
Hiss reduction is too strong. Set it to `light` or `off` and re-process.

### Subtitles are wrong or show text when nobody is talking
Whisper sometimes mishears muffled or overlapping speech. TapeCap already removes low-confidence lines. Bigger models (`small.en` → `medium.en`) are more accurate but much slower. Subtitles can be switched off in the player, and the `.srt` file can be edited in any text editor.

### Upscaling doesn't run
**Settings → This computer** shows the reason:
- **Real-ESRGAN not installed**: run `./install.sh` (x86-64 only) or see [Upscaling](upscaling.md#installing-real-esrgan-by-hand).
- **No supported graphics card**: only built-in graphics or the `llvmpipe` software renderer was found. Install the GPU driver (`nvidia-driver-470` for Kepler cards, or the current one), reboot, then press **Re-scan devices**. Set **AI upscaling → on** to allow integrated GPUs.
- The service user needs access to the GPU. `install.sh` adds the `render` and `video` groups.

## Control panel

### The panel doesn't load
- Is the service running? Check `systemctl status tapecap`.
- Use the IP address instead of `.local`: `hostname -I` on the TapeCap computer.
- Is a firewall blocking it? Try `sudo ufw allow 8787/tcp`.
- Was another program already using port 8787? Look for "Address already in use" in the log, and change `web_port` in the config file.

### Videos won't play in the browser
The browser plays the finished MP4s directly (H.264/AAC). Very old browsers, or raw `.mkv` recovery files, may not play: use **Download** and VLC.

## FAQ

**Can I record two tapes at once?**
Not with one service. It handles one capture device. Run a second instance with its own `TAPECAP_CONFIG`, `TAPECAP_STATE`, device and port.

**Does it work with PAL tapes?**
Yes. Select a 720×576 @ 25 format in **Settings → Picture format** if your stick offers it. Processing handles any frame rate.

**Does it work with Betamax, Video8, Hi8, Digital8, VHS-C or S-VHS?**
Yes, with anything that plays into a composite or S-Video output.

**Does it work on Windows or macOS?**
No. It relies on Linux V4L2/ALSA and systemd. A Raspberry Pi is the cheapest way to run it.

**Is my video sent anywhere?**
No. Everything, transcription included, runs locally. The only network traffic is the panel on your LAN, the one-time speech model download, and notifications if you turn them on.

**How much disk space do I need?**
About 100 MB per minute of tape for the original plus the finished copy, which is about 6 GB per hour of tape. Upscaled copies need 3–4× more.

**Can I delete the originals?**
Yes, once you're happy with the library copies. But they're the untouched master copy: if you want to re-process later with better settings or a GPU, you'll need them. Keep them if you have the space.

**Why are the files named by date and time instead of a title?**
The date and time are when the tape was digitized. TapeCap can't know what's on a tape or when it was filmed. Automatic titles from the transcript proved unreliable in testing, so naming is left to you.
