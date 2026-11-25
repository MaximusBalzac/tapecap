"""Detect capture devices (V4L2 video + ALSA audio), GPUs and the upscaler."""
import glob
import os
import re
import shutil
import subprocess

from . import config

FOURCC_FFMPEG = {"MJPG": "mjpeg", "YUYV": "yuyv422", "UYVY": "uyvy422", "NV12": "nv12"}
# preferred capture sizes for tape sources (NTSC, PAL, fallback)
PREFERRED_SIZES = [(720, 480, 30), (720, 576, 25), (640, 480, 30), (720, 480, 25)]


def _read(p, default=""):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return default


def _usb_device_of(sys_device_link):
    """sysfs interface dir (…/1-1/1-1:1.0) -> the USB device it belongs to (…/1-1)."""
    p = os.path.realpath(sys_device_link)
    if "/usb" not in p:
        return None
    if re.search(r"/[\d.-]+:\d+\.\d+$", p):
        p = os.path.dirname(p)
    return p


def _formats(dev):
    """[{fourcc, input_format, width, height, fps:[..]}] from v4l2-ctl."""
    if not shutil.which("v4l2-ctl"):
        return [{"fourcc": "MJPG", "input_format": "mjpeg", "width": 720, "height": 480, "fps": [30]}]
    try:
        out = subprocess.run(["v4l2-ctl", "-d", dev, "--list-formats-ext"],
                             capture_output=True, text=True, timeout=10).stdout
    except (subprocess.TimeoutExpired, OSError):
        return []
    fmts, cur, size = [], None, None
    for line in out.splitlines():
        m = re.search(r"\[\d+\]: '(\w+)'", line)
        if m:
            cur = m.group(1)
            continue
        m = re.search(r"Size: Discrete (\d+)x(\d+)", line)
        if m and cur:
            size = {"fourcc": cur, "input_format": FOURCC_FFMPEG.get(cur, cur.lower()),
                    "width": int(m.group(1)), "height": int(m.group(2)), "fps": []}
            fmts.append(size)
            continue
        m = re.search(r"\(([\d.]+) fps\)", line)
        if m and size is not None:
            size["fps"].append(round(float(m.group(1))))
    return [f for f in fmts if f["input_format"] in FOURCC_FFMPEG.values()]


def format_id(f, fps):
    return f"{f['input_format']}:{f['width']}x{f['height']}@{fps}"


def best_format(fmts):
    for w, h, fps in PREFERRED_SIZES:
        for pref in ("mjpeg", "yuyv422", "uyvy422", "nv12"):
            for f in fmts:
                if f["input_format"] == pref and (f["width"], f["height"]) == (w, h) and fps in f["fps"]:
                    return {"input_format": pref, "width": w, "height": h, "fps": fps}
    if fmts:
        f = max(fmts, key=lambda f: (f["input_format"] == "mjpeg", f["width"] * f["height"]))
        fps = 30 if 30 in f["fps"] else (max(f["fps"]) if f["fps"] else 30)
        return {"input_format": f["input_format"], "width": f["width"], "height": f["height"], "fps": fps}
    return {"input_format": "mjpeg", "width": 720, "height": 480, "fps": 30}


def list_video():
    by_id = {}
    for link in glob.glob("/dev/v4l/by-id/*"):
        by_id[os.path.realpath(link)] = link
    devs = []
    for p in sorted(glob.glob("/sys/class/video4linux/video*"),
                    key=lambda s: int(re.sub(r"\D", "", os.path.basename(s)) or 0)):
        usb = _usb_device_of(os.path.join(p, "device"))
        if not usb:                       # only USB capture devices (skips Pi codec/ISP nodes)
            continue
        dev = "/dev/" + os.path.basename(p)
        fmts = _formats(dev)
        if not fmts:                      # metadata node, not a capture node
            continue
        devs.append({"path": by_id.get(dev, dev), "dev": dev, "name": _read(os.path.join(p, "name"), dev),
                     "usb": usb, "formats": fmts, "best": best_format(fmts),
                     "format_ids": [format_id(f, fps) for f in fmts for fps in f["fps"]]})
    return devs


def list_audio():
    cards = []
    for line in _read("/proc/asound/cards").splitlines():
        m = re.match(r"\s*(\d+) \[(\S+)\s*\]: (.*)", line)
        if not m:
            continue
        n, cid, desc = m.groups()
        pcms = sorted(glob.glob(f"/proc/asound/card{n}/pcm*c"))
        if not pcms:                      # no capture (e.g. HDMI outputs)
            continue
        for pcm in pcms:
            d = re.search(r"pcm(\d+)c", pcm).group(1)
            cards.append({"path": f"hw:CARD={cid},DEV={d}", "name": desc.split(" - ")[-1].strip(),
                          "usb": _usb_device_of(f"/sys/class/sound/card{n}/device")})
    return cards


def resolve_video(cfg, devs=None):
    """Returns (device_dict | None, message)."""
    devs = list_video() if devs is None else devs
    want = cfg.get("video_device", "auto")
    if want and want != "auto":
        real = os.path.realpath(want)
        for d in devs:
            if want in (d["path"], d["dev"]) or real == d["dev"]:
                return d, ""
        if os.path.exists(want):          # not USB / unknown, but present: trust the user
            fmts = _formats(want)
            return {"path": want, "dev": real, "name": os.path.basename(want), "usb": None,
                    "formats": fmts, "best": best_format(fmts), "format_ids": []}, ""
        return None, f"Selected capture device {want} is not connected"
    if not devs:
        return None, "No USB capture device found – plug in the capture stick"
    return devs[0], ""


def resolve_audio(cfg, video, cards=None):
    want = cfg.get("audio_device", "auto")
    if want == "none":
        return None
    cards = list_audio() if cards is None else cards
    if want and want != "auto":
        return want
    if video and video.get("usb"):
        for c in cards:                   # same USB stick as the video
            if c["usb"] == video["usb"]:
                return c["path"]
    usb_cards = [c for c in cards if c["usb"]]
    return usb_cards[0]["path"] if usb_cards else None


def resolve_format(cfg, video):
    want = cfg.get("video_format", "auto")
    m = re.match(r"(\w+):(\d+)x(\d+)@(\d+)$", want or "")
    if m and (not video.get("format_ids") or want in video["format_ids"]):
        return {"input_format": m.group(1), "width": int(m.group(2)),
                "height": int(m.group(3)), "fps": int(m.group(4))}
    return video["best"]


# ------------------------------------------------------------------ GPUs ---
def list_gpus():
    """Vulkan devices in enumeration order (the numbering Real-ESRGAN's -g uses)."""
    if not shutil.which("vulkaninfo"):
        return []
    try:
        out = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True,
                             timeout=20).stdout
    except (subprocess.TimeoutExpired, OSError):
        return []
    gpus = []
    for m in re.finditer(r"GPU(\d+):(.*?)(?=\nGPU\d+:|\Z)", out, re.S):
        idx, body = int(m.group(1)), m.group(2)
        name = re.search(r"deviceName\s*=\s*(.+)", body)
        typ = re.search(r"deviceType\s*=\s*PHYSICAL_DEVICE_TYPE_(\w+)", body)
        name = name.group(1).strip() if name else f"GPU {idx}"
        typ = typ.group(1) if typ else "OTHER"
        if typ == "DISCRETE_GPU":
            use = "good"
        elif typ == "INTEGRATED_GPU":
            use = "slow"                  # works, but far too slow for whole tapes
        else:
            use = "no"                    # software renderer (llvmpipe)
        gpus.append({"index": idx, "name": name, "type": typ.lower(), "use": use})
    return gpus


def find_upscaler(cfg):
    for p in (cfg.get("upscale_binary"), shutil.which("realesrgan-ncnn-vulkan"),
              os.path.join(config.APP_DIR, "tools", "realesrgan", "realesrgan-ncnn-vulkan")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def upscale_plan(cfg, gpus=None):
    """Decide whether this machine will upscale. Returns (gpu_ids | None, reason)."""
    mode = cfg.get("upscale", "auto")
    if mode == "off":
        return None, "upscaling is turned off"
    binary = find_upscaler(cfg)
    if not binary:
        return None, "Real-ESRGAN (realesrgan-ncnn-vulkan) is not installed"
    gpus = list_gpus() if gpus is None else gpus
    if cfg.get("upscale_gpu", "auto") not in ("", "auto"):
        ids = [int(x) for x in re.findall(r"\d+", cfg["upscale_gpu"])]
        known = {g["index"] for g in gpus}
        ids = [i for i in ids if i in known] if known else ids
        return (ids, "") if ids else (None, "selected GPU not found")
    good = [g["index"] for g in gpus if g["use"] == "good"]
    if good:
        return good, ""
    if mode == "on":
        slow = [g["index"] for g in gpus if g["use"] == "slow"]
        if slow:
            return slow, ""
    return None, "no supported graphics card (dedicated Vulkan GPU) found"


def whisper_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False
