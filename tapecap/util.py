import json
import os
import shutil
import struct
import subprocess
import time
import zlib


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def ts(sec, srt=False):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if srt:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    return f"{int(h)}:{int(m):02d}:{int(s):02d}" if h else f"{int(m)}:{int(s):02d}"


def fmt_minutes(seconds):
    m = seconds / 60
    return f"{m:.0f} min" if m >= 10 else f"{m:.1f} min"


def png_bytes(arr):
    """Encode an HxWx3 uint8 array as PNG (stdlib only)."""
    h, w, _ = arr.shape
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                          "-show_format", path], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"cannot read {path}: {out.stderr.strip()[-200:]}")
    d = json.loads(out.stdout)
    info = {"duration": float(d.get("format", {}).get("duration", 0) or 0),
            "has_audio": False, "has_video": False, "width": 0, "height": 0,
            "fps_str": "30/1", "fps": 30.0}
    for s in d.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"], info["height"] = int(s["width"]), int(s["height"])
            # r_frame_rate is the real constant rate (30/1); avg_frame_rate can be
            # a rounding artefact like 22500/751 on trimmed/filtered files
            for fr in (s.get("r_frame_rate"), s.get("avg_frame_rate")):
                num, _, den = (fr or "").partition("/")
                try:
                    fps = float(num) / float(den or 1)
                except (ValueError, ZeroDivisionError):
                    continue
                if 5 <= fps <= 120:
                    info["fps_str"], info["fps"] = fr, fps
                    break
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


def fstab_mountpoint(path):
    """The fstab mount point that `path` lives on (None if it is on the root fs)."""
    best = None
    try:
        with open("/etc/fstab") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2 or parts[0].startswith("#") or parts[1] in ("/", "none", "swap"):
                    continue
                mp = parts[1].rstrip("/")
                if (path == mp or path.startswith(mp + "/")) and (best is None or len(mp) > len(best)):
                    best = mp
    except OSError:
        pass
    return best


def drive_ready(path):
    """False if the folder is on an fstab drive that is not mounted right now."""
    mp = fstab_mountpoint(os.path.abspath(path))
    return (mp is None or os.path.ismount(mp)), mp


def disk_free(path):
    while path and not os.path.exists(path):
        path = os.path.dirname(path)
    try:
        u = shutil.disk_usage(path or "/")
        return {"free": u.free, "total": u.total}
    except OSError:
        return None


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
