"""Background processing of captured tapes (runs as a low-priority child process).

For every new capture in the originals folder it builds <library>/<name>/ :
  <name>.mp4         black edges cropped, true aspect ratio, stabilized, hiss/rumble
                     reduced + loudness-normalised audio, chapters, subtitles
                     (AI-upscaled when a supported GPU is present)
  <name>_SD.mp4      the standard-resolution version, if upscaled and kept
  <name>.srt, transcript.txt, contact_sheet.jpg, info.txt
Originals are never modified. Interrupted jobs resume from the last finished step.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

import numpy as np

from . import config, devices
from .notify import notify
from .upscale import upscale
from .util import fmt_minutes, log, probe, read_json, ts, write_json

STATUS = os.path.join(config.STATE_DIR, "processor.json")
FAILED = os.path.join(config.STATE_DIR, "failed.json")
CANCEL = os.path.join(config.STATE_DIR, "cancel")
POLL = 10
MAX_CROP = 16
STAB_SMOOTHING = {"light": 10, "normal": 20, "strong": 35}
HISS = {"off": None, "light": "afftdn=nr=8:nf=-30", "medium": "afftdn=nf=-25", "strong": "afftdn=nr=20:nf=-25"}
LONG_GAP, FILL_EVERY, MIN_CHAPTER = 600, 300, 30
# settings that change the output; if they differ from an interrupted run, start over
OUTPUT_KEYS = ("crop_edges", "aspect", "output_height", "stabilize", "sharpen", "rumble_filter",
               "hiss_reduction", "normalize_audio", "loudness_target", "transcribe", "whisper_model",
               "language", "chapters", "chapter_sensitivity", "upscale", "upscale_factor", "upscale_model")

running = True
current = None


class Cancelled(Exception):
    pass


def on_signal(*_):
    global running
    running = False
    if current and current.poll() is None:
        current.terminate()


# ------------------------------------------------------------ status/IO ----
class Status:
    def __init__(self):
        self.d = {"state": "idle", "tape": None, "step": None, "step_pct": 0, "pct": 0,
                  "started": None, "queue": [], "upscale": None, "last": None, "pid": os.getpid()}
        self._t = 0

    def set(self, force=True, **kw):
        self.d.update(kw)
        now = time.time()
        if force or now - self._t > 2:
            self._t = now
            write_json(STATUS, self.d)


status = Status()
STEPS = []          # (name, weight) for the current tape


def step(name, pct=0):
    done = 0
    total = sum(w for _, w in STEPS) or 1
    for n, w in STEPS:
        if n == name:
            done += w * pct / 100
            break
        done += w
    status.set(force=pct == 0, step=name, step_pct=round(pct, 1), pct=round(100 * done / total, 1))
    if os.path.exists(CANCEL):
        raise Cancelled()


def run(cmd, dur=None, step_name=None, capture=False):
    """Run a command; interruptible; optional progress from ffmpeg -progress."""
    global current
    if not running:
        raise InterruptedError
    if dur and cmd[0] == "ffmpeg":
        cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    current = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, errors="replace")
    err = []
    t = threading.Thread(target=lambda: err.extend(current.stderr), daemon=True)
    t.start()
    try:
        for line in current.stdout:
            if dur and line.startswith("out_time_us=") and step_name:
                try:
                    step(step_name, min(99.9, int(line.split("=")[1]) / 1e6 / dur * 100))
                except ValueError:
                    pass
            elif os.path.exists(CANCEL):
                current.terminate()
    except Cancelled:
        current.terminate()
        current.wait()
        raise
    current.wait()
    t.join(5)
    rc = current.returncode
    current = None
    if not running:
        raise InterruptedError
    if os.path.exists(CANCEL):
        raise Cancelled()
    if rc != 0:
        raise RuntimeError(f"{os.path.basename(cmd[0])} failed (rc={rc}): {''.join(err)[-400:]}")
    return "".join(err) if capture else None


def ff(*args):
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args]


# ---------------------------------------------------------------- steps ----
def detect_crop(src, info):
    W, H = info["width"], info["height"]
    start = max(0, info["duration"] / 2 - 30)
    err = run(ff("-ss", f"{start:.0f}", "-t", "60", "-i", src,
                 "-vf", "cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"), capture=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
    if not m:
        return [W, H, 0, 0]
    w, h, x, y = map(int, m[-1])
    left, top = min(x, MAX_CROP), min(y, MAX_CROP)
    right, bottom = min(W - (x + w), MAX_CROP), min(H - (y + h), MAX_CROP)
    w, h = W - left - right, H - top - bottom
    return [w - w % 2, h - h % 2, left, top]


def detect_chapters(src, dur, cfg):
    times = []
    if cfg["chapters"]:
        err = run(ff("-i", src, "-vf", f"scale=180:120,scdet=threshold={cfg['chapter_sensitivity']}",
                     "-an", "-f", "null", "-"), dur, "Finding chapters", capture=True)
        times = sorted(float(t) for t in re.findall(r"lavfi\.scd\.time: ([0-9.]+)", err))
    chapters = [0.0]
    for t in times:
        if t - chapters[-1] >= MIN_CHAPTER and dur - t >= 15:
            chapters.append(t)
    if not cfg["chapters"]:
        return chapters
    filled = []                         # long tripod shots: a chapter every 5 min
    for a, b in zip(chapters, chapters[1:] + [dur]):
        filled.append(a)
        if b - a > LONG_GAP:
            t = a + FILL_EVERY
            while b - t >= FILL_EVERY / 2:
                filled.append(t)
                t += FILL_EVERY
    return filled


def audio_chain(cfg, final=True):
    parts = []
    if cfg["rumble_filter"]:
        parts.append("highpass=f=80")
    if HISS.get(cfg["hiss_reduction"]):
        parts.append(HISS[cfg["hiss_reduction"]])
    if final and cfg["normalize_audio"]:
        parts.append(f"loudnorm=I={cfg['loudness_target']}:TP=-2:LRA=11")
    return ",".join(parts)


_whisper = None


def transcribe(src, dur, cfg):
    global _whisper
    if not cfg["transcribe"] or not devices.whisper_available():
        return []
    ac = audio_chain(cfg, final=False)
    p = subprocess.run(ff("-v", "error", "-i", src, "-vn", *(["-af", ac] if ac else []),
                          "-ac", "1", "-ar", "16000", "-f", "f32le", "-"), capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return []
    audio = np.frombuffer(p.stdout, np.float32)
    if _whisper is None or _whisper[0] != cfg["whisper_model"]:
        from faster_whisper import WhisperModel
        _whisper = (cfg["whisper_model"], WhisperModel(cfg["whisper_model"], device="cpu",
                                                       compute_type="int8", cpu_threads=cfg["process_threads"]))
    # English-only models must be told "en"; multilingual ones auto-detect when language is blank
    lang = "en" if cfg["whisper_model"].endswith(".en") else (cfg["language"] or None)
    segs, _ = _whisper[1].transcribe(audio, language=lang, vad_filter=True, condition_on_previous_text=False)
    out = []
    for s in segs:
        if not running:
            raise InterruptedError
        step("Transcribing speech", min(99.9, s.end / max(dur, 1) * 100))
        text = s.text.strip()
        if text and s.no_speech_prob < 0.6 and s.avg_logprob > -1.0 and s.compression_ratio < 2.4:
            out.append([s.start, s.end, text])
    return out


def write_srt(segs, path):
    with open(path, "w") as f:
        for i, (a, b, t) in enumerate(segs, 1):
            f.write(f"{i}\n{ts(a, True)} --> {ts(b, True)}\n{t}\n\n")


def write_ffmeta(path, title, chapters, dur):
    def esc(s):
        return re.sub(r"([=;#\\\n])", r"\\\1", s)
    with open(path, "w") as f:
        f.write(f";FFMETADATA1\ntitle={esc(title)}\n")
        bounds = chapters + [dur]
        for i in range(len(chapters)):
            f.write(f"\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(bounds[i] * 1000)}\n"
                    f"END={int(bounds[i + 1] * 1000)}\ntitle=Scene {i + 1} ({ts(bounds[i])})\n")


def contact_sheet(src, chapters, dur, out, work, crop):
    cw, ch, cx, cy = crop
    points = list(chapters)
    if len(points) < 8:
        points = sorted(set(round(p) for p in points + [dur * i / 9 for i in range(1, 9)]))
    points = sorted(points)[:16]
    for old in [f for f in os.listdir(work) if f.startswith("thumb_")]:
        os.remove(os.path.join(work, old))
    for i, t in enumerate(points):
        t = min(t + 2, max(0, dur - 1))
        run(ff("-v", "error", "-ss", f"{t:.1f}", "-i", src, "-frames:v", "1",
               "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale=320:240,setsar=1,"
                      f"drawtext=text='{ts(t).replace(':', chr(92) + ':')}':"
                      "x=6:y=h-th-6:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6",
               os.path.join(work, f"thumb_{i:02d}.png")))
    rows = -(-len(points) // 4)
    run(ff("-v", "error", "-framerate", "1", "-i", os.path.join(work, "thumb_%02d.png"),
           "-vf", f"tile=4x{rows}:padding=4:margin=4", "-frames:v", "1", "-q:v", "3", out))


def enhance(src, info, crop, meta, srt, out, work, cfg):
    w, h, x, y = crop
    oh = cfg["output_height"]
    ow = round(oh * (16 / 9 if cfg["aspect"] == "16:9" else 4 / 3) / 2) * 2
    vf = f"crop={w}:{h}:{x}:{y}" if cfg["crop_edges"] else "null"
    vf += f",scale={ow}:{oh}:flags=lanczos,setsar=1"
    dur = info["duration"]
    if cfg["stabilize"] != "off":
        trf = os.path.join(work, "motion.trf")
        if not os.path.exists(trf + ".done"):
            run(ff("-v", "error", "-i", src, "-vf", f"{vf},vidstabdetect=shakiness=6:accuracy=15:result={trf}",
                   "-an", "-f", "null", "-"), dur, "Measuring camera shake")
            open(trf + ".done", "w").close()
        vf += (f",vidstabtransform=input={trf}:smoothing={STAB_SMOOTHING[cfg['stabilize']]}:"
               "optzoom=1:zoomspeed=0.2:interpol=bicubic")
    if cfg["sharpen"]:
        vf += ",unsharp=5:5:0.6:3:3:0.0"
    has_subs = srt and os.path.exists(srt) and os.path.getsize(srt) > 0
    cmd = ff("-v", "error", "-i", src, "-i", meta) + (["-i", srt] if has_subs else [])
    cmd += ["-map", "0:v:0", "-map", "0:a?"] + (["-map", "2:s"] if has_subs else [])
    cmd += ["-map_metadata", "1", "-map_chapters", "1", "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    ac = audio_chain(cfg)
    if info["has_audio"]:
        cmd += (["-af", ac] if ac else []) + ["-ar", "48000", "-c:a", "aac", "-b:a", "192k"]
    if has_subs:
        cmd += ["-c:s", "mov_text", "-metadata:s:s:0", f"language={'eng' if cfg['language'] == 'en' else 'und'}"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", out + ".tmp"]
    run(cmd, dur, "Stabilizing + cleaning sound")
    os.replace(out + ".tmp", out)


# ---------------------------------------------------------------- driver ---
def state_path(cfg):
    return os.path.join(cfg["library_dir"], ".processed.json")


def mark_done(cfg, name, entry):
    st = read_json(state_path(cfg), {})        # re-read: the panel may have edited it
    st[name] = entry
    write_json(state_path(cfg), st)


def process(name, cfg):
    global STEPS
    src = os.path.join(cfg["originals_dir"], name)
    stem = name[:-4]
    work = os.path.join(cfg["work_dir"], "process", stem)
    snapshot = {k: cfg[k] for k in OUTPUT_KEYS}
    cache = read_json(os.path.join(work, "progress.json"))
    if not cache or cache.get("settings") != snapshot:
        shutil.rmtree(work, ignore_errors=True)
        cache = {"settings": snapshot}
    os.makedirs(work, exist_ok=True)

    def save_cache():
        write_json(os.path.join(work, "progress.json"), cache)

    t0 = time.time()
    info = probe(src)
    dur = info["duration"]
    gpu_ids, why = devices.upscale_plan(cfg)
    STEPS = [("Checking picture edges", 1), ("Finding chapters", 4), ("Transcribing speech", 25 if cfg["transcribe"] else 0),
             ("Making contact sheet", 1), ("Measuring camera shake", 15 if cfg["stabilize"] != "off" else 0),
             ("Stabilizing + cleaning sound", 30), ("Upscaling (AI)", 200 if gpu_ids else 0), ("Saving", 1)]
    status.set(state="working", tape=name, started=time.strftime("%Y-%m-%d %H:%M:%S"),
               upscale=("GPU " + ",".join(map(str, gpu_ids))) if gpu_ids else why)
    log(f"Processing {name} ({fmt_minutes(dur)}); upscale: {gpu_ids or why}")

    step("Checking picture edges")
    if "crop" not in cache:
        cache["crop"] = detect_crop(src, info) if cfg["crop_edges"] else [info["width"], info["height"], 0, 0]
        save_cache()
    step("Finding chapters")
    if "chapters" not in cache:
        cache["chapters"] = detect_chapters(src, dur, cfg)
        save_cache()
    step("Transcribing speech")
    if "segments" not in cache:
        cache["segments"] = transcribe(src, dur, cfg)
        save_cache()
    crop, chapters, segs = cache["crop"], cache["chapters"], cache["segments"]
    log(f"  crop {crop}, {len(chapters)} chapters, {len(segs)} speech segments")

    srt = os.path.join(work, stem + ".srt")
    write_srt(segs, srt)
    meta = os.path.join(work, "meta.txt")
    write_ffmeta(meta, stem, chapters, dur)
    step("Making contact sheet")
    sheet = os.path.join(work, "contact_sheet.jpg")
    if cfg["contact_sheet"] and not os.path.exists(sheet):
        contact_sheet(src, chapters, dur, sheet, work, crop)

    std = os.path.join(work, stem + "_SD.mp4")
    if not os.path.exists(std):
        enhance(src, info, crop, meta, srt, std, work, cfg)
    final = std
    upscaled = False
    if gpu_ids:
        step("Upscaling (AI)")
        hd = os.path.join(work, stem + "_HD.mp4")
        if not os.path.exists(hd):
            upscale(std, hd + ".tmp", probe(std), cfg, devices.find_upscaler(cfg), gpu_ids, work,
                    run, lambda p: step("Upscaling (AI)", p))
            os.replace(hd + ".tmp", hd)
        final, upscaled = hd, True

    step("Saving")
    with open(os.path.join(work, "transcript.txt"), "w") as f:
        f.write(f"{stem}\n\n")
        f.writelines(f"[{ts(a)}] {t}\n" for a, _, t in segs)
        if not segs:
            f.write("(no speech detected)\n" if cfg["transcribe"] else "(transcription turned off)\n")
    out_info = probe(final)
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})", stem)
    with open(os.path.join(work, "info.txt"), "w") as f:
        f.write(f"Name:      {stem}\nLength:    {ts(dur)}\n"
                f"Digitized: {m.group(1) + ' ' + m.group(2) + ':' + m.group(3) if m else '?'} "
                f"(capture date, not the date it was filmed)\n"
                f"Source:    {src}\nPicture:   {out_info['width']}x{out_info['height']}"
                f"{' (AI upscaled ' + str(cfg['upscale_factor']) + 'x)' if upscaled else ''}\n"
                f"Speech:    {len(segs)} segments\n\nChapters:\n")
        f.writelines(f"  {i:2d}. {ts(c)}\n" for i, c in enumerate(chapters, 1))

    dest = os.path.join(cfg["library_dir"], stem)
    os.makedirs(dest, exist_ok=True)
    shutil.move(final, os.path.join(dest, stem + ".mp4"))
    if upscaled and cfg["keep_standard_version"]:
        shutil.move(std, os.path.join(dest, stem + "_SD.mp4"))
    for f in (stem + ".srt", "transcript.txt", "contact_sheet.jpg", "info.txt"):
        if os.path.exists(os.path.join(work, f)):
            shutil.move(os.path.join(work, f), os.path.join(dest, f))
    shutil.rmtree(work, ignore_errors=True)

    mins = (time.time() - t0) / 60
    mark_done(cfg, name, {"folder": dest, "title": stem, "done": time.strftime("%Y-%m-%d %H:%M"),
                          "minutes": round(mins, 1), "upscaled": upscaled})
    log(f"Done in {mins:.1f} min -> {dest}")
    status.set(last={"tape": name, "done": time.strftime("%Y-%m-%d %H:%M"), "ok": True})
    notify(cfg, f"✅ Tape processed: {stem}\n{fmt_minutes(dur)} · {len(chapters)} chapters · "
                f"{'transcript + subtitles' if segs else 'no speech found'}"
                f"{' · AI upscaled' if upscaled else ''}\n\n📁 {dest}",
           os.path.join(dest, "contact_sheet.jpg"), wait=True)


def pending(cfg):
    done = read_json(state_path(cfg), {})
    failed = read_json(FAILED, {})
    pat = re.compile(rf"{re.escape(cfg['name_prefix'])}_\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}(_recovered)?\.mp4")
    try:
        names = sorted(os.listdir(cfg["originals_dir"]))
    except OSError:
        return []
    return [n for n in names if pat.fullmatch(n) and n not in done and n not in failed]


def main():
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        os.nice(15)
        subprocess.run(["ionice", "-c", "3", "-p", str(os.getpid())], capture_output=True)
    except OSError:
        pass
    os.makedirs(config.STATE_DIR, exist_ok=True)
    log("Processor started")
    while running:
        cfg = config.load()
        if os.path.exists(CANCEL):
            os.remove(CANCEL)                   # stale cancel request
        try:
            os.makedirs(cfg["library_dir"], exist_ok=True)
            queue = pending(cfg)
        except OSError:
            queue = []
        status.set(state="idle" if not queue else "working", tape=None, step=None, pct=0,
                   step_pct=0, queue=queue)
        for name in queue[:1]:
            status.set(queue=queue[1:])
            try:
                process(name, cfg)
            except InterruptedError:
                break
            except Cancelled:
                log(f"Cancelled {name}")
                f = read_json(FAILED, {})
                f[name] = {"error": "Cancelled from the control panel", "time": time.strftime("%Y-%m-%d %H:%M")}
                write_json(FAILED, f)
                status.set(last={"tape": name, "done": time.strftime("%Y-%m-%d %H:%M"), "ok": False,
                                 "error": "cancelled"})
            except Exception as e:
                log(f"FAILED {name}: {e}")
                f = read_json(FAILED, {})
                f[name] = {"error": str(e)[:500], "time": time.strftime("%Y-%m-%d %H:%M")}
                write_json(FAILED, f)
                status.set(last={"tape": name, "done": time.strftime("%Y-%m-%d %H:%M"), "ok": False,
                                 "error": str(e)[:200]})
                notify(cfg, f"⚠️ Tape processing failed for {name}: {str(e)[:300]}")
        if queue:
            continue                            # look for the next tape straight away
        for _ in range(POLL):
            if not running:
                break
            time.sleep(1)
    status.set(state="stopped", tape=None)
    log("Processor stopping")


if __name__ == "__main__":
    sys.exit(main())
