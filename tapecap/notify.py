"""Optional phone notifications through Hermes Agent (`hermes send`)."""
import os
import shutil
import subprocess
import time

from . import config


def hermes_path(cfg):
    for p in (cfg.get("hermes_bin"), shutil.which("hermes"),
              os.path.expanduser("~/.local/bin/hermes")):
        if p and os.path.exists(p):
            return p
    return None


def notify(cfg, text, image=None, wait=False):
    """Fire-and-forget by default so capture never waits on the network."""
    if cfg.get("notify") != "hermes":
        return
    hermes = hermes_path(cfg)
    if not hermes:
        return
    body = text + (f"\nMEDIA:{image}" if image and os.path.exists(image) else "")
    try:
        os.makedirs(config.STATE_DIR, exist_ok=True)
        log = open(os.path.join(config.STATE_DIR, "notify.log"), "a")
        log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.splitlines()[0] + "\n")
        log.flush()
        p = subprocess.Popen([hermes, "send", "--json", "-t", cfg.get("notify_target") or "telegram", body],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        if wait:
            p.wait(timeout=120)
    except Exception as e:  # a failed notification must never break capture
        print("notify failed:", e, flush=True)
