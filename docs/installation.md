# Installation

## Requirements

| | Minimum | Recommended |
|---|---|---|
| Computer | Raspberry Pi 4 (4 GB) or any 64-bit x86 PC | Raspberry Pi 5 (8 GB+), or a PC with a 4+ core CPU |
| OS | Debian 12, Ubuntu 22.04+, Raspberry Pi OS (Bookworm or newer, 64-bit) | Same |
| Capture device | USB composite ("AV to USB", "USB 2.0 video grabber") stick that works with V4L2 | MacroSilicon MS210x-based sticks (tested) |
| Storage | Enough for your tapes: about **100 MB per minute** of tape (original + finished copy) | A USB hard drive. 1 TB holds about 150 hours of tape. |
| GPU (optional) | Any Vulkan-capable card, for upscaling | Dedicated NVIDIA/AMD card with 4 GB+ |

Python 3.10+ and ffmpeg 5+ are needed. The installer takes care of both.

## Install

```bash
git clone https://github.com/MaximusBalzac/tapecap.git
cd tapecap
./install.sh
```

The installer:
1. installs the system packages: `ffmpeg`, `v4l-utils`, `alsa-utils`, `python3-venv`, `vulkan-tools`, `unzip` and `curl`
2. creates a Python virtual environment in `./venv` with `numpy` and `faster-whisper`
3. **on x86-64 PCs only**, downloads Real-ESRGAN ncnn-vulkan into `./tools/realesrgan/` (about 45 MB). Skip it with `./install.sh --no-upscaler`.
4. writes `/etc/systemd/system/tapecap.service` for the current user, then enables and starts it
5. prints the control panel address

The service runs as **your user**, not root, with the `video`, `audio` and `render` groups added. The folder you cloned into is where the service runs from, so don't delete or move it afterwards. If you do move it, run `./install.sh` again.

The first transcription downloads the speech model (`small.en`, about 480 MB) into `~/.cache/huggingface`.

> The file `tapecap.service` in the repository is an example (the one used on the author's Raspberry Pi). You don't need it: `install.sh` writes the correct unit for your user and folder.

## First run

1. Open `http://<computer-name>.local:8787/`. If `.local` names don't work on your network, use `http://<ip-address>:8787/`.
2. Go to **Settings → Save locations** and point the three folders at your big drive, for example:
   - Library: `/mnt/usb/library`
   - Originals: `/mnt/usb/originals`
   - Working: `/mnt/usb/work`

   The default is `~/TapeCapture/…` in your home folder.
3. Plug in the capture stick. The **Status** page should show its name and a live **blue** picture.
4. Play a tape. Within about a second the status changes to **Recording**.

### Using an external USB drive

Mount it permanently with `/etc/fstab` so it's always at the same path:

```
UUID=XXXX-XXXX  /mnt/usb  ntfs3  defaults,nofail,uid=1000,gid=1000  0  0
```

(`sudo blkid` shows the UUID. Use `ext4` or `exfat` instead of `ntfs3` to match your drive's format.)

TapeCap reads `/etc/fstab`. If a save folder is on a drive that isn't mounted, it shows **Waiting for drive** and waits rather than writing to the SD card underneath the empty mount point.

## Updating

```bash
cd tapecap
git pull
sudo systemctl restart tapecap
```

Only restart while the status is **Waiting for a tape**. Restarting during a recording cuts it short. The part recorded so far is recovered, but you'd have to replay the rest of the tape.

If an update adds Python packages, run `./install.sh` again. It's safe to re-run.

## Uninstall

```bash
sudo systemctl disable --now tapecap
sudo rm /etc/systemd/system/tapecap.service
sudo systemctl daemon-reload
rm -rf ~/.config/tapecap ~/.local/state/tapecap   # settings and status files
```

Your recordings stay wherever you saved them. Delete the `tapecap` folder to remove the program itself.

## Running it by hand (without systemd)

```bash
cd tapecap
venv/bin/python -m tapecap
```

Stop it with Ctrl-C. Don't run this while the service is also running: only one program can use the capture device at a time.

## Several machines

A common setup is a Raspberry Pi doing the capturing, and a PC with a graphics card doing the heavy upscaling. Two ways to do it:

- **Simple:** install TapeCap on both. Capture on the Pi, then copy the finished originals (`VHS_*.mp4`) into the PC's *Originals* folder. The PC processes and upscales anything new that appears there.
- **Shared storage:** have the PC mount the Pi's drive over the network (Samba/NFS) and point its *Originals* folder at the Pi's originals. On the Pi, set **Upscaling → off**. On the PC, set a separate Library folder and a local Working folder.

  Only one machine should process a given Library folder, because the list of processed tapes lives in `library/.processed.json`.

A PC without a capture stick works fine as a processing-only machine. Its status just shows **No capture device**.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TAPECAP_CONFIG` | `~/.config/tapecap/config.json` | Settings file location |
| `TAPECAP_STATE` | `~/.local/state/tapecap` | Runtime status, failure list, notification log |

Set them in the service with `sudo systemctl edit tapecap`:
```
[Service]
Environment=TAPECAP_CONFIG=/etc/tapecap.json
```
