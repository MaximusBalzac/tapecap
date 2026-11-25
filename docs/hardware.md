# Hardware guide

## Capture devices

TapeCap works with any **USB composite video capture device** that Linux supports through V4L2 (the standard video driver framework). Most of them are sold as "USB 2.0 video capture", "AV to USB" or "VHS to digital converter".

| Device type | Works? | Notes |
|---|---|---|
| **MacroSilicon MS210x** sticks ("AV TO USB2.0") | ✅ Tested | Cheap and common. MJPEG 720×480 @ 30. Shows solid **blue** when there's no signal. Has its own audio input. |
| Other UVC (USB Video Class) composite grabbers | ✅ Should work | Anything that shows up as `/dev/videoN` and lists formats with `v4l2-ctl --list-formats-ext` |
| EasyCAP UTV007 / STK1160 | ⚠️ Usually | Supported by the kernel, YUYV only. Pick the format by hand if `auto` chooses wrongly. |
| HDMI capture sticks | ✅ (for HDMI sources) | Works for camcorders with HDMI out. Blank detection relies on the source showing a solid colour. |
| PCI(e) capture cards (bttv, cx23885…) | ⚠️ | Not USB, so set `video_device` and `audio_device` by hand |
| FireWire / DV (Digital8, MiniDV over i.LINK) | ❌ | Not supported. Use the camcorder's analogue AV output instead. |

Check what Linux sees:
```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
arecord -l
```

### "Blank" screens

Recording starts and stops based on whether the picture is a **single solid colour**. Most capture sticks show solid blue or black without a signal, and most VCRs show blue at the end of a tape. Real video, even dark scenes or static/snow, is never a solid colour. If your setup shows something else when idle (a logo, or a "No signal" text box), lower `blank_fraction` slightly (for example 0.85) so a mostly-plain screen still counts as blank, or open an issue with a screenshot.

## Cabling

```
VCR / camcorder                     Capture stick
  VIDEO OUT (yellow)  ───────────►  yellow (CVBS)
  AUDIO OUT L (white) ───────────►  white
  AUDIO OUT R (red)   ───────────►  red
```

- Use the VCR's **OUT** jacks, not IN.
- If there's an S-Video output and your stick has an S-Video input, use it: the picture is noticeably sharper. Select the S-Video input with `v4l2-ctl -d /dev/video0 --set-input=1` if needed.
- **Camcorders:** set the switch to **PLAY/VTR** mode and use the supplied AV cable. Some need "AV out" turned on in the menu.
- Combination TV/VCR units: press the **TV/VCR** button so the output shows the tape.
- **Hi8 / Digital8 camcorders** (Sony) play both analogue Hi8 and Digital8 tapes through the same AV output.

### Picture quality tips

- Clean the VCR heads if the picture is noisy or keeps losing colour.
- Turn the VCR's **tracking** to auto, or adjust it by hand for worn tapes.
- A VCR with **TBC** (time-base correction) or a DVD recorder in pass-through mode fixes jittery, wobbling pictures. A good VCR matters more than any software step.
- Small square blocky glitches on **Digital8** tapes are dropouts on the tape itself. Analogue tape dropouts look like horizontal white streaks.

## The computer

| | Raspberry Pi 5 | Raspberry Pi 4 | x86 PC |
|---|---|---|---|
| Recording (1 tape) | ✅ ~1 core | ✅ ~1.5 cores | ✅ |
| Stabilize + sound | ~0.5× real time | ~1× real time | much faster than real time |
| Transcription (`small.en`) | ~1–1.5× real time | ~3× real time; use `base.en` | faster than real time |
| AI upscaling | ❌ too slow | ❌ | ✅ with a GPU |

**CPU use while idle** is about 5 % of one core, for watching 5 small frames per second.

Recording always comes first. Processing runs at the lowest CPU and disk priority (`nice 15`, idle I/O class), so it never causes dropped frames.

**Storage:** about 50 MB per minute for originals and about 45 MB per minute for library copies. Upscaled 2× copies are roughly 3–4× bigger. A 1 TB drive holds about 150 hours of tape (originals and library), not counting upscaled copies. Prefer a powered USB hard drive or an SSD over the SD card.

## GPUs for upscaling

TapeCap upscales with **Real-ESRGAN ncnn-vulkan**, which runs on any GPU with a working **Vulkan** driver: NVIDIA, AMD and Intel. CUDA isn't needed, and the GPU's memory size matters less than you'd think, because each frame is processed in tiles.

| Card | Works | Notes |
|---|---|---|
| NVIDIA GTX 600/700 series, Quadro K-series (Kepler) | ✅ slow | Needs the **470** legacy driver (`sudo apt install nvidia-driver-470` on Ubuntu 22.04). Newer drivers dropped Kepler. |
| NVIDIA GTX 900/10-series | ✅ | Current driver |
| NVIDIA RTX 20/30/40/50-series | ✅ fast | Current driver. Several times faster than older cards. |
| AMD Radeon HD 7000 / R7 / R9 / RX (GCN and newer) | ✅ | Mesa RADV driver, included in Ubuntu |
| Intel Arc | ✅ | Recent Mesa |
| Intel UHD / Iris (integrated) | ⚠️ very slow | Only with `upscale: on` |
| Raspberry Pi V3D | ⚠️ far too slow | Upscaling isn't really practical on a Pi |
| NVIDIA GTX 400/500 (Fermi) and older, AMD HD 6000 and older | ❌ | No Vulkan |

**2 GB of graphics memory is enough** for 640×480 tape footage. More memory and a newer card mainly mean more speed.

**Two or more cards:** TapeCap uses all dedicated GPUs automatically (`upscale_gpu: auto`), or the ones you list (`0,1`). Frames are shared between the cards, so two similar cards are roughly twice as fast. Memory isn't pooled; each card works on its own frames.

### Check that the GPU is usable

```bash
vulkaninfo --summary          # should list your card as PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
nvidia-smi                    # NVIDIA only: driver loaded?
```

The control panel's **Settings → This computer** card shows each GPU with ✅ (supported), ⚠️ (built-in, slow) or ❌ (not a GPU, for example the `llvmpipe` software renderer), and states whether this computer will upscale.

### Example: old workstation as an upscaling box

An AMD FX / ASRock 990FX board with two **Quadro K2000** (2 GB, Kepler) cards:
- Install **Ubuntu 22.04 LTS**, then `sudo apt install nvidia-driver-470`, and reboot.
- Run `./install.sh`. It downloads Real-ESRGAN, and both cards are listed with ✅.
- Put the cards in the two full-speed x16 slots. The K2000 takes its power from the slot, so no extra power cable is needed.
- Expect roughly **5–10 hours per hour of tape** with both cards on the fast model at 2×. That makes it an overnight batch machine. See [Upscaling](upscaling.md).
