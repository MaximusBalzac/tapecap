"""TapeCap service: capture engine + processing worker + control panel."""
import os
import signal
import subprocess
import sys
import threading
import time

from . import config
from .capture import Capture
from .util import log
from .web import serve


def supervise_processor(stop):
    """Run the processing worker as a separate low-priority process; restart it if it dies."""
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    while not stop.is_set():
        p = subprocess.Popen([sys.executable, "-m", "tapecap.processor"], cwd=config.APP_DIR, env=env)
        while p.poll() is None and not stop.is_set():
            stop.wait(1)
        if stop.is_set():
            p.terminate()
            try:
                p.wait(60)
            except subprocess.TimeoutExpired:
                p.kill()
            return
        log(f"Processor exited (rc={p.returncode}) – restarting in 10 s")
        stop.wait(10)


def main():
    cfg = config.load()
    if not os.path.exists(config.CONFIG_PATH):
        config.save(cfg)                 # write the defaults so they are easy to find
    os.makedirs(config.STATE_DIR, exist_ok=True)
    stop = threading.Event()

    def on_signal(*_):
        stop.set()
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    cap = Capture()
    cap.start()
    srv = serve(cap, cfg)
    log(f"Control panel: http://{os.uname().nodename}.local:{cfg['web_port']}/")
    pt = threading.Thread(target=supervise_processor, args=(stop,), daemon=True)
    pt.start()

    while not stop.is_set():
        stop.wait(1)
    log("Stopping…")
    cap.shutdown()
    cap.join(45)
    pt.join(65)
    srv.shutdown()
    log("Stopped")


if __name__ == "__main__":
    sys.exit(main())
