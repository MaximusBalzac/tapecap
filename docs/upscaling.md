# AI upscaling

VHS and Hi8 hold roughly 330–400 lines of real detail. On a modern TV a 640×480 file is stretched by the TV's simple scaler and looks soft. AI upscaling uses a neural network (**Real-ESRGAN**) trained to rebuild sharp edges and textures, so it produces a cleaner, higher-resolution picture before the TV ever sees it.

It **can't recover detail that was never on the tape**. Expect cleaner edges, less blur and less noise. Faces and fine textures can look a bit smooth or "painted", especially with the fast model. Try it on a few minutes of your own footage before committing to a whole collection.

## When it runs

Upscaling is the last processing step, after stabilization and sound clean-up, so the stabilized picture is what gets upscaled. It only runs when all of these are true:

1. `upscale` is `auto` or `on` (Settings → Upscaling)
2. the **Real-ESRGAN** program is installed (`install.sh` downloads it on x86-64 PCs)
3. a usable GPU is found:
   - `auto`: only **dedicated** (discrete) Vulkan GPUs
   - `on`: integrated graphics too
   - or the exact cards listed in `upscale_gpu`

The **Processing** card on the Status page says *"Upscaling: GPU 0,1"* or the reason it's skipped (for example *"no supported graphics card"*).

## Models

| Model | Speed | Look | Best for |
|---|---|---|---|
| `realesr-animevideov3` (default) | ⚡ fast | Clean and smooth, can look a bit painted | Most home video, big collections |
| `realesrgan-x4plus` | 🐢 ~10–20× slower | More natural texture and detail | A few favourite tapes on a fast GPU |
| `realesrgan-x4plus-anime` | 🐢 | Flat colours, hard edges | Cartoons recorded off TV |

The x4 models always work at 4× and are then resized down to your factor (2× or 3×).

## Factor

| Factor | 4:3 output | Notes |
|---|---|---|
| 2× | 1280×960 | Recommended. Fills a 1080p TV, and files are about 3–4× bigger. |
| 3× | 1920×1440 | |
| 4× | 2560×1920 | Mostly just bigger files, rarely visibly better than 2× |

## Speed

These are rough figures for **one hour of tape** (108,000 frames at 30 fps) at 2× with `realesr-animevideov3`. Real speed depends on the card, the driver and the CPU feeding it.

| GPU | Approx. time per hour of tape |
|---|---|
| Quadro K2000 / GT 740 class (Kepler, 2 GB) | 10–20 h (two cards: 5–10 h) |
| GTX 1050 / 1060 | 3–6 h |
| RTX 3050 / 3060 | 1–3 h |
| RTX 4070 or faster | under 1 h |
| `realesrgan-x4plus` on any card | ~10–20× the above |

Time a short test before committing: copy a 1-minute clip into the Originals folder, named for example `VHS_2000-01-01_00-00-00.mp4`, and watch the progress bar.

## How it works

TapeCap upscales in **20-second chunks**:
1. ffmpeg extracts one chunk of frames as PNG images.
2. `realesrgan-ncnn-vulkan` upscales the folder on the GPU(s) (`-g 0,1` splits the work).
3. ffmpeg encodes the chunk (H.264, CRF 18), and the PNGs are deleted.

When every chunk is done, they're joined and the audio, subtitles, chapters and title are copied over from the stabilized version.

This keeps temporary disk use down to a few GB, however long the tape is. Finished chunks are kept, so if the computer is restarted mid-tape, upscaling **resumes from the last finished chunk**.

## Installing Real-ESRGAN by hand

`install.sh` does this on x86-64. For other setups, or a newer version:

```bash
mkdir -p tools/realesrgan && cd tools/realesrgan
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip
unzip realesrgan-ncnn-vulkan-20220424-ubuntu.zip
chmod +x realesrgan-ncnn-vulkan
./realesrgan-ncnn-vulkan -i input.png -o output.png   # quick test
```

Or put it anywhere and set **Settings → Upscaling → Real-ESRGAN program** to its path. The `models/` folder must sit next to the program.

There's no official ARM build, so upscaling isn't available on a Raspberry Pi, and the Pi's GPU would be far too slow anyway.

## Upscaling tapes that are already processed

Tapes processed before upscaling was available, or on a machine without a GPU, can be upscaled later:
- **Same machine:** press **Re-process** in the Library. The whole pipeline runs again, including upscaling.
- **Another machine with a GPU:** copy the originals into that machine's Originals folder. It processes and upscales them.
