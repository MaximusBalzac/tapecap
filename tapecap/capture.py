"""Capture engine: watch the capture device, record while a tape plays,
stop after the picture has been blank for a while, trim the blank tail and
save the result to the originals folder.

The device sends the stick's solid BLUE "no signal" screen (or black) when
nothing plays. A frame counts as blank when nearly every pixel is the same
colour; real video – even dark scenes or snow – never is.
"""
import collections
import datetime
import os
import shutil
import subprocess
import threading
import time

import numpy as np

from . import config, devices
from .notify import notify
from .util import drive_ready, fmt_minutes, log, png_bytes

MON_W, MON_H, MON_FPS = 320, 240, 5      # analysis / preview thumbnails
MON_BYTES = MON_W * MON_H * 3
MON_FILTER = f"fps={MON_FPS},scale={MON_W}:{MON_H},format=rgb24"


class Capture(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="capture")
        self.state = "starting"
        self.detail = ""
        self.video = self.audio = self.fmt = None
        self.rec_file = None
        self.rec_started = None
        self.blank_seconds = 0.0
        self.content_seconds = 0.0
        self._preview = None
        self.preview_time = 0.0
        self.events = collections.deque(maxlen=60)
        self._stop_rec = threading.Event()
        self._restart = threading.Event()
        self._quit = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ control --
    def stop_recording(self):
        self._stop_rec.set()

    def apply_settings(self):
        """Re-read the configuration (immediately when idle, after the tape when recording)."""
        self._restart.set()
        return "after this recording" if self.state == "recording" else "now"

    def shutdown(self):
        self._quit.set()

    def event(self, msg):
        log(msg)
        self.events.appendleft({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "msg": msg})

    def _set(self, state, detail=""):
        if (state, detail) != (self.state, self.detail):
            self.state, self.detail = state, detail
            if detail:
                self.event(detail)

    def status(self):
        rec = None
        if self.state in ("recording", "saving") and self.rec_started:
            rec = {"file": self.rec_file, "started": self.rec_started.strftime("%Y-%m-%d %H:%M:%S"),
                   "elapsed": (datetime.datetime.now() - self.rec_started).total_seconds(),
                   "blank_seconds": self.blank_seconds,
                   "size": os.path.getsize(self.rec_file) if self.rec_file and os.path.exists(self.rec_file) else 0}
        return {"state": self.state, "detail": self.detail,
                "video": self.video and {"path": self.video["path"], "name": self.video["name"]},
                "audio": self.audio, "format": self.fmt, "recording": rec,
                "preview_age": time.time() - self.preview_time if self.preview_time else None,
                "events": list(self.events)}

    def preview_png(self):
        with self._lock:
            f = self._preview
        return png_bytes(f) if f is not None else None

    # ---------------------------------------------------------- ffmpeg I/O --
    def _video_args(self):
        f = self.fmt
        return ["-f", "v4l2", "-input_format", f["input_format"],
                "-video_size", f"{f['width']}x{f['height']}", "-framerate", str(f["fps"]),
                "-thread_queue_size", "512", "-i", self.video["path"]]

    def _start_monitor(self):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *self._video_args(),
               "-vf", MON_FILTER, "-f", "rawvideo", "pipe:1"]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)

    def _start_recorder(self, path, cfg):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *self._video_args()]
        if self.audio:
            cmd += ["-f", "alsa", "-thread_queue_size", "2048", "-i", self.audio]
        cmd += ["-filter_complex", f"[0:v]split=2[rec][mon];[mon]{MON_FILTER}[monout]",
                "-map", "[rec]"]
        if self.audio:
            cmd += ["-map", "1:a", "-af", "aresample=async=1000", "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg["record_quality"]),
                "-pix_fmt", "yuv420p", path,
                "-map", "[monout]", "-f", "rawvideo", "pipe:1"]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)

    @staticmethod
    def _stop_proc(p, graceful=True):
        if p is None or p.poll() is not None:
            return
        try:
            if graceful and p.stdin:
                p.stdin.write(b"q")
                p.stdin.flush()
                p.stdin.close()
            else:
                p.terminate()
        except Exception:
            p.terminate()
        try:                                   # drain so ffmpeg never blocks on a full pipe
            while p.stdout.read(65536):
                pass
        except Exception:
            pass
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

    def _read_frame(self, p):
        buf = b""
        while len(buf) < MON_BYTES:
            chunk = p.stdout.read(MON_BYTES - len(buf))
            if not chunk:
                return None
            buf += chunk
        f = np.frombuffer(buf, np.uint8).reshape(MON_H, MON_W, 3)
        with self._lock:
            self._preview = f
            self.preview_time = time.time()
        return f

    @staticmethod
    def _is_blank(frame, cfg):
        px = frame[::2, ::2].reshape(-1, 3).astype(np.int16)
        med = np.median(px, axis=0)
        close = (np.abs(px - med).max(axis=1) < cfg["blank_tolerance"]).mean()
        return close >= cfg["blank_fraction"]

    # ------------------------------------------------------------- saving --
    @staticmethod
    def _audio_filter(cfg):
        return f"loudnorm=I={cfg['loudness_target']}:TP=-2:LRA=11" if cfg["normalize_audio"] else None

    def _save(self, cfg, raw, out, keep=None):
        """Trim (optional) + normalise the audio, writing out via a .part file."""
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", raw]
        if keep:
            cmd += ["-t", f"{keep:.2f}"]
        cmd += ["-map", "0:v:0", "-map", "0:a?", "-c:v", "copy"]
        af = self._audio_filter(cfg)
        cmd += (["-af", af, "-ar", "48000"] if af else []) + ["-c:a", "aac", "-b:a", "192k"]
        name = os.path.splitext(os.path.basename(out))[0]
        cmd += ["-movflags", "+faststart", "-metadata", f"title={name}", "-f", "mp4", out + ".part"]
        r = subprocess.run(cmd)
        if r.returncode == 0 and os.path.getsize(out + ".part") > 0:
            os.replace(out + ".part", out)
            return True
        if os.path.exists(out + ".part"):
            os.remove(out + ".part")
        return False

    def _finalize(self, cfg, raw, content_end, started_at):
        if content_end < cfg["min_keep_seconds"]:
            self.event(f"Only {content_end:.0f}s of picture – discarded (shorter than {cfg['min_keep_seconds']}s)")
            os.remove(raw)
            return
        name = f"{cfg['name_prefix']}_" + started_at.strftime("%Y-%m-%d_%H-%M-%S")
        out = os.path.join(cfg["originals_dir"], name + ".mp4")
        keep = content_end + 1.0               # a second of breathing room after the last picture
        self._set("saving", f"Trimming blank end and saving {name} ({fmt_minutes(keep)})")
        if self._save(cfg, raw, out, keep):
            os.remove(raw)
            self.event(f"Saved {out} ({fmt_minutes(keep)}, {os.path.getsize(out) / 1e6:.0f} MB)")
            thumb = os.path.join(cfg["work_dir"], "last_tape_thumb.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{keep / 2:.0f}", "-i", out,
                            "-frames:v", "1", "-vf", "scale=640:480", thumb])
            notify(cfg, f"📼 Tape finished recording ({fmt_minutes(keep)}) – ready for the next tape.\n"
                        f"Processing has started.", thumb)
        else:
            self.event(f"Saving failed – raw recording kept at {raw}")

    def _recover(self, cfg):
        """Save raw recordings left behind by a crash, power cut or service stop."""
        for f in sorted(os.listdir(cfg["originals_dir"])):
            if f.endswith(".mp4.part"):
                os.remove(os.path.join(cfg["originals_dir"], f))
        for f in sorted(os.listdir(cfg["work_dir"])):
            if not f.endswith(".mkv"):
                continue
            raw = os.path.join(cfg["work_dir"], f)
            out = os.path.join(cfg["originals_dir"], f[:-4] + "_recovered.mp4")
            self.event(f"Recovering unfinished recording {f}")
            if self._save(cfg, raw, out):
                os.remove(raw)
                self.event(f"Recovered -> {out}")
            else:
                shutil.move(raw, out[:-4] + ".mkv")
                self.event(f"Could not repair {f}; moved it to {out[:-4]}.mkv")

    # --------------------------------------------------------------- main --
    def run(self):
        recovered = False
        while not self._quit.is_set():
            cfg = config.load()
            for d in ("originals_dir", "work_dir"):
                ok, mp = drive_ready(cfg[d])
                if not ok:
                    self._set("waiting_drive", f"Waiting for the drive {mp} to be connected/mounted")
                    break
            else:
                ok = True
            if not ok:
                self._quit.wait(5)
                continue
            try:
                os.makedirs(cfg["originals_dir"], exist_ok=True)
                os.makedirs(cfg["work_dir"], exist_ok=True)
                if not recovered:
                    self._recover(cfg)
                    recovered = True
            except OSError as e:
                self._set("error", f"Cannot write to the save folder: {e}")
                self._quit.wait(10)
                continue

            video, msg = devices.resolve_video(cfg)
            if not video:
                self.video = None
                self._set("no_device", msg)
                self._quit.wait(5)
                continue
            self.video, self.audio, self.fmt = video, devices.resolve_audio(cfg, video), devices.resolve_format(cfg, video)
            self._restart.clear()
            try:
                self._cycle(cfg)
            except Exception as e:             # never let the service die
                self._set("error", f"Capture error: {e}")
                self._quit.wait(5)
        self._set("stopped", "Capture stopped")

    def _cycle(self, cfg):
        """One idle -> record -> save cycle."""
        fmt = self.fmt
        self._set("idle", f"Waiting for a tape to play ({self.video['name']}, "
                          f"{fmt['width']}x{fmt['height']}@{fmt['fps']}, "
                          f"{'audio ' + self.audio if self.audio else 'no audio'})")
        mon = self._start_monitor()
        need = max(1, int(cfg["start_seconds"] * MON_FPS))
        content = 0
        while True:
            if self._quit.is_set() or self._restart.is_set():
                self._stop_proc(mon, graceful=False)
                return
            f = self._read_frame(mon)
            if f is None:
                self._stop_proc(mon, graceful=False)
                self._set("no_device", "Capture device stopped responding – retrying")
                self._quit.wait(3)
                return
            content = 0 if self._is_blank(f, cfg) else content + 1
            if content >= need:
                break
        self._stop_proc(mon, graceful=False)

        # ------------------------------ recording
        started = datetime.datetime.now()
        raw = os.path.join(cfg["work_dir"], f"{cfg['name_prefix']}_" + started.strftime("%Y-%m-%d_%H-%M-%S") + ".mkv")
        self.rec_file, self.rec_started = raw, started
        self._stop_rec.clear()
        self._set("recording", f"Tape playing – recording {os.path.basename(raw)}")
        rec = self._start_recorder(raw, cfg)
        n = last_content = blank = 0
        stop_after = int(cfg["stop_blank_seconds"] * MON_FPS)
        max_frames = int(cfg["max_record_minutes"] * 60 * MON_FPS) or None
        reason = ""
        while True:
            if self._quit.is_set():
                # service stopping: close the file cleanly; it is recovered on next start
                self._stop_proc(rec, graceful=True)
                self.event("Service stopping during a recording – it will be recovered at next start")
                return
            if self._stop_rec.is_set():
                reason = "Stopped from the control panel"
                last_content = n
                break
            f = self._read_frame(rec)
            if f is None:
                reason = "Capture device stopped during recording"
                break
            n += 1
            if self._is_blank(f, cfg):
                blank += 1
                if blank == MON_FPS * 3:
                    self.event(f"Blank screen… (stops after {cfg['stop_blank_seconds']}s)")
                if blank >= stop_after:
                    reason = f"Blank for {cfg['stop_blank_seconds']}s – tape finished"
                    break
            else:
                if blank >= MON_FPS * 3:
                    self.event("Picture back – still recording")
                blank = 0
                last_content = n
            self.blank_seconds = blank / MON_FPS
            if max_frames and n >= max_frames:
                reason = f"Reached the {cfg['max_record_minutes']} min limit"
                last_content = n
                break
            if n % (MON_FPS * 300) == 0:
                log(f"Recording… {n / MON_FPS / 60:.0f} min")
        self.event(reason)
        self._stop_proc(rec, graceful=True)
        self.blank_seconds = 0
        if os.path.exists(raw) and os.path.getsize(raw) > 0:
            self._finalize(cfg, raw, last_content / MON_FPS, started)
        else:
            self.event("No recording file was produced")
        self.rec_file = self.rec_started = None
        time.sleep(1)
