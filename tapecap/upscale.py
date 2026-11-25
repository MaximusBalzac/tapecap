"""AI upscaling with Real-ESRGAN (ncnn-vulkan build, runs on any Vulkan GPU).

Works through the video in short chunks so it never needs more than a few GB
of temporary disk space, and finished chunks are kept so an interrupted job
resumes where it left off.
"""
import glob
import os
import shutil
import subprocess

NATIVE_SCALE = {"realesrgan-x4plus": 4, "realesrgan-x4plus-anime": 4}
CHUNK_SECONDS = 20


def upscale(src, out, info, cfg, binary, gpu_ids, work, run, progress):
    """run(cmd) executes a command (interruptible); progress(pct) reports 0-100."""
    fps, fps_str = info["fps"], info["fps_str"]
    factor = int(cfg["upscale_factor"])
    model = cfg["upscale_model"]
    native = NATIVE_SCALE.get(model, factor)
    tw, th = info["width"] * factor, info["height"] * factor
    total = max(1, round(info["duration"] * fps))
    per = int(round(fps * CHUNK_SECONDS))
    chunks = -(-total // per)
    seg_dir = os.path.join(work, "upscale")
    os.makedirs(seg_dir, exist_ok=True)
    segs = []
    for k in range(chunks):
        seg = os.path.join(seg_dir, f"seg_{k:05d}.mp4")
        segs.append(seg)
        if os.path.exists(seg):            # done in an earlier (interrupted) run
            continue
        d_in, d_out = os.path.join(seg_dir, "in"), os.path.join(seg_dir, "out")
        for d in (d_in, d_out):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        start = max(0.0, (k * per - 0.5) / fps)   # half a frame early -> lands exactly on frame k*per
        run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.4f}", "-i", src,
             "-frames:v", str(min(per, total - k * per)), "-an", "-sn", "-start_number", "1",
             os.path.join(d_in, "%06d.png")])
        if not glob.glob(os.path.join(d_in, "*.png")):
            break                           # past the real end of the video
        models = os.path.join(os.path.dirname(binary), "models")
        run([binary, "-i", d_in, "-o", d_out, "-n", model, "-s", str(native),
             *(["-m", models] if os.path.isdir(models) else []),
             "-g", ",".join(str(g) for g in gpu_ids), "-f", "png"])
        vf = [] if native == factor else ["-vf", f"scale={tw}:{th}:flags=lanczos"]
        run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-framerate", fps_str,
             "-i", os.path.join(d_out, "%06d.png"), *vf, "-c:v", "libx264", "-preset", "medium",
             "-crf", "18", "-pix_fmt", "yuv420p", "-r", fps_str, seg + ".tmp.mp4"])
        os.replace(seg + ".tmp.mp4", seg)
        shutil.rmtree(d_in, ignore_errors=True)
        shutil.rmtree(d_out, ignore_errors=True)
        progress(100.0 * (k + 1) / chunks)
    segs = [s for s in segs if os.path.exists(s)]
    lst = os.path.join(seg_dir, "list.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    # video from the upscaled chunks; audio, subtitles, chapters, title from the source
    run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-i", src, "-map", "0:v", "-map", "1:a?", "-map", "1:s?", "-map_metadata", "1",
         "-map_chapters", "1", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", out])
    shutil.rmtree(seg_dir, ignore_errors=True)
