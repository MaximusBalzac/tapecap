"""Settings: defaults + JSON file (~/.config/tapecap/config.json)."""
import copy
import json
import os
import threading

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.environ.get("TAPECAP_CONFIG",
                             os.path.expanduser("~/.config/tapecap/config.json"))
STATE_DIR = os.environ.get("TAPECAP_STATE", os.path.expanduser("~/.local/state/tapecap"))
_HOME = os.path.expanduser("~/TapeCapture")

DEFAULTS = {
    # --- capture device -------------------------------------------------
    "video_device": "auto",          # "auto" or a /dev path
    "audio_device": "auto",          # "auto", "none" or an ALSA name (hw:CARD=..,DEV=0)
    "video_format": "auto",          # "auto" or "mjpeg:720x480@30"
    # --- where files go -------------------------------------------------
    "originals_dir": os.path.join(_HOME, "originals"),   # trimmed raw captures
    "library_dir": os.path.join(_HOME, "library"),       # finished, enhanced tapes
    "work_dir": os.path.join(_HOME, "work"),             # in-progress recordings/temp
    "name_prefix": "VHS",
    # --- start / stop detection ----------------------------------------
    "start_seconds": 1.0,            # picture this long -> start recording
    "stop_blank_seconds": 15,        # blank this long -> tape finished
    "min_keep_seconds": 20,          # shorter recordings are discarded
    "max_record_minutes": 0,         # safety stop (0 = no limit)
    "blank_tolerance": 24,
    "blank_fraction": 0.92,
    "record_quality": 20,            # x264 CRF of the capture (lower = better/larger)
    # --- sound ----------------------------------------------------------
    "normalize_audio": True,
    "loudness_target": -14,          # LUFS
    "rumble_filter": True,           # cut < 80 Hz (wind, handling, hum)
    "hiss_reduction": "medium",      # off | light | medium | strong
    # --- picture --------------------------------------------------------
    "crop_edges": True,
    "aspect": "4:3",                 # 4:3 | 16:9
    "output_height": 480,
    "stabilize": "normal",           # off | light | normal | strong
    "sharpen": True,
    # --- extras ---------------------------------------------------------
    "transcribe": True,
    "whisper_model": "small.en",     # tiny.en | base.en | small.en | medium.en
    "language": "en",
    "chapters": True,
    "chapter_sensitivity": 15,       # scene-cut threshold (lower = more chapters)
    "contact_sheet": True,
    # --- upscaling (Real-ESRGAN ncnn-vulkan, needs a Vulkan GPU) -------
    "upscale": "auto",               # off | auto (only with a dedicated GPU) | on
    "upscale_factor": 2,             # 2 | 3 | 4
    "upscale_model": "realesr-animevideov3",
    "upscale_gpu": "auto",           # "auto" or comma list of GPU numbers, e.g. "0,1"
    "upscale_binary": "",            # path to realesrgan-ncnn-vulkan ("" = search)
    "keep_standard_version": True,   # keep the non-upscaled copy too
    # --- notifications --------------------------------------------------
    "notify": "off",                 # off | hermes
    "notify_target": "telegram",
    "hermes_bin": "",
    # --- system ---------------------------------------------------------
    "process_threads": 3,
    "web_port": 8787,
    "web_bind": "0.0.0.0",
}

CHOICES = {
    "hiss_reduction": ["off", "light", "medium", "strong"],
    "stabilize": ["off", "light", "normal", "strong"],
    "aspect": ["4:3", "16:9"],
    "whisper_model": ["tiny.en", "base.en", "small.en", "medium.en", "tiny", "base", "small", "medium"],
    "upscale": ["off", "auto", "on"],
    "upscale_factor": [2, 3, 4],
    "upscale_model": ["realesr-animevideov3", "realesrgan-x4plus", "realesrgan-x4plus-anime"],
    "notify": ["off", "hermes"],
}

_lock = threading.Lock()


def load():
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save(cfg):
    with _lock:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({k: cfg[k] for k in DEFAULTS if k in cfg}, f, indent=2)
        os.replace(tmp, CONFIG_PATH)


def validate(new):
    """Return (clean_cfg, errors) for a dict coming from the control panel."""
    cfg = load()
    errors = {}
    for k, v in new.items():
        if k not in DEFAULTS:
            continue
        d = DEFAULTS[k]
        try:
            if isinstance(d, bool):
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
            elif isinstance(d, int) and not isinstance(d, bool):
                v = int(float(v))
            elif isinstance(d, float):
                v = float(v)
            else:
                v = str(v).strip()
        except (TypeError, ValueError):
            errors[k] = "not a valid number"
            continue
        if k in CHOICES and v not in CHOICES[k]:
            errors[k] = f"must be one of {CHOICES[k]}"
            continue
        cfg[k] = v
    for k in ("originals_dir", "library_dir", "work_dir"):
        p = os.path.expanduser(cfg[k])
        if not os.path.isabs(p):
            errors[k] = "must be a full path, e.g. /mnt/usb/library"
        cfg[k] = p
    rng = {"start_seconds": (0.2, 30), "stop_blank_seconds": (3, 600), "min_keep_seconds": (0, 3600),
           "max_record_minutes": (0, 1000), "blank_tolerance": (4, 80), "blank_fraction": (0.5, 0.999),
           "record_quality": (14, 30), "loudness_target": (-30, -8), "output_height": (240, 1080),
           "chapter_sensitivity": (3, 60), "process_threads": (1, 64), "web_port": (1024, 65535)}
    for k, (lo, hi) in rng.items():
        if not lo <= cfg[k] <= hi:
            errors[k] = f"must be between {lo} and {hi}"
    if cfg["output_height"] % 2:
        cfg["output_height"] += 1
    if not cfg["name_prefix"] or any(c in cfg["name_prefix"] for c in "/\\ :*?\"<>|"):
        errors["name_prefix"] = "letters/numbers only"
    return cfg, errors
