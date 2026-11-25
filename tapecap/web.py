"""Control panel: a small web server (stdlib only) + JSON API."""
import json
import mimetypes
import os
import re
import shutil
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, devices
from .notify import hermes_path
from .processor import CANCEL, FAILED, STATUS, state_path
from .util import disk_free, read_json, write_json

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_dev_cache = {"t": 0, "data": None}


def device_report(fresh=False):
    import time
    if fresh or not _dev_cache["data"] or time.time() - _dev_cache["t"] > 30:
        cfg = config.load()
        gpus = devices.list_gpus()
        plan, why = devices.upscale_plan(cfg, gpus)
        _dev_cache["data"] = {
            "video": [{k: d[k] for k in ("path", "dev", "name", "format_ids", "best")} for d in devices.list_video()],
            "audio": devices.list_audio(),
            "gpus": gpus,
            "upscaler": devices.find_upscaler(cfg),
            "upscale_plan": {"gpus": plan, "reason": why},
            "whisper": devices.whisper_available(),
            "hermes": hermes_path(cfg),
            "drives": drives(),
        }
        _dev_cache["t"] = time.time()
    return _dev_cache["data"]


def drives():
    out = []
    try:
        with open("/proc/mounts") as f:
            for line in f:
                dev, mp, fs = line.split()[:3]
                mp = mp.replace("\\040", " ")
                if (mp.startswith(("/mnt/", "/media/", "/srv/")) or mp == os.path.expanduser("~")) \
                        and fs not in ("tmpfs", "autofs"):
                    u = disk_free(mp)
                    out.append({"path": mp, "fs": fs, **(u or {})})
    except OSError:
        pass
    home = os.path.expanduser("~")
    if not any(d["path"] == home for d in out):
        out.append({"path": home, "fs": "home", **(disk_free(home) or {})})
    return out


def library(cfg):
    done = read_json(state_path(cfg), {})
    failed = read_json(FAILED, {})
    proc = read_json(STATUS, {})
    items = {}
    try:
        for d in sorted(os.listdir(cfg["library_dir"])):
            p = os.path.join(cfg["library_dir"], d)
            if not os.path.isdir(p) or d.startswith("."):
                continue
            files = sorted(os.listdir(p))
            info = ""
            try:
                with open(os.path.join(p, "info.txt")) as f:
                    info = f.read()
            except OSError:
                pass
            length = re.search(r"Length:\s+(\S+)", info)
            pic = re.search(r"Picture:\s+(.+)", info)
            items[d] = {"name": d, "status": "done", "folder": d, "files": files,
                        "length": length.group(1) if length else "",
                        "picture": pic.group(1).strip() if pic else "",
                        "size": sum(os.path.getsize(os.path.join(p, f)) for f in files)}
    except OSError:
        pass
    try:
        originals = sorted(f for f in os.listdir(cfg["originals_dir"]) if f.endswith(".mp4"))
    except OSError:
        originals = []
    for f in originals:
        stem = f[:-4]
        it = items.setdefault(stem, {"name": stem, "folder": None, "files": [], "length": "", "picture": "", "size": 0})
        it["original"] = f
        if f == proc.get("tape") and proc.get("state") == "working":
            it["status"] = "processing"
        elif f in failed:
            it["status"], it["error"] = "failed", failed[f].get("error", "")
        elif f not in done:
            it["status"] = "queued"
    for it in items.values():
        it.setdefault("status", "done")
    return sorted(items.values(), key=lambda i: i["name"], reverse=True)


class Handler(BaseHTTPRequestHandler):
    capture = None
    server_version = "TapeCap"

    def log_message(self, *a):
        pass

    # -------------------------------------------------------------- helpers
    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _file(self, path):
        if not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".srt"):
            ctype = "text/plain; charset=utf-8"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if "download" in self.path:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    @staticmethod
    def _inside(root, rel):
        p = os.path.realpath(os.path.join(root, rel))
        return p if p.startswith(os.path.realpath(root) + os.sep) else None

    # --------------------------------------------------------------- routes
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(u.path)
        cfg = config.load()
        if path in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"))
        if path == "/api/status":
            st = self.capture.status()
            st["processor"] = read_json(STATUS, {})
            st["disk"] = disk_free(cfg["library_dir"])
            st["library_dir"] = cfg["library_dir"]
            st["host"] = socket.gethostname()
            return self._json(st)
        if path == "/api/preview.png":
            png = self.capture.preview_png()
            if not png:
                return self._json({"error": "no picture yet"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            return self.wfile.write(png)
        if path == "/api/config":
            return self._json({"config": cfg, "defaults": config.DEFAULTS, "choices": config.CHOICES})
        if path == "/api/devices":
            return self._json(device_report(fresh="fresh" in u.query))
        if path == "/api/library":
            return self._json(library(cfg))
        if path.startswith("/files/lib/") and path.endswith(".vtt"):
            p = self._inside(cfg["library_dir"], path[len("/files/lib/"):-4] + ".srt")
            if not p or not os.path.exists(p):
                return self._json({"error": "not found"}, 404)
            with open(p, encoding="utf-8", errors="replace") as f:
                vtt = "WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", f.read())
            body = vtt.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/vtt; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        m = re.match(r"^/files/(lib|orig)/(.+)$", path)
        if m:
            root = cfg["library_dir"] if m.group(1) == "lib" else cfg["originals_dir"]
            p = self._inside(root, m.group(2))
            return self._file(p) if p else self._json({"error": "forbidden"}, 403)
        if path.startswith("/download/"):
            p = self._inside(cfg["library_dir"], path[len("/download/"):])
            return self._file(p) if p else self._json({"error": "forbidden"}, 403)
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        data = self._body()
        cfg = config.load()
        if path == "/api/config":
            new, errors = config.validate(data)
            if not errors:
                for k in ("originals_dir", "library_dir", "work_dir"):
                    try:
                        os.makedirs(new[k], exist_ok=True)
                        probe_file = os.path.join(new[k], ".tapecap_write_test")
                        open(probe_file, "w").close()
                        os.remove(probe_file)
                    except OSError as e:
                        errors[k] = f"cannot write there ({e.strerror})"
            if errors:
                return self._json({"ok": False, "errors": errors}, 400)
            restart_web = new["web_port"] != cfg["web_port"] or new["web_bind"] != cfg["web_bind"]
            config.save(new)
            _dev_cache["t"] = 0
            when = self.capture.apply_settings()
            return self._json({"ok": True, "applied": when,
                               "note": "Restart the service for the new web port to take effect" if restart_web else ""})
        if path == "/api/stop":
            self.capture.stop_recording()
            return self._json({"ok": True})
        if path == "/api/rescan":
            rep = device_report(fresh=True)
            self.capture.apply_settings()
            return self._json(rep)
        if path == "/api/reprocess":
            name = os.path.basename(data.get("name", ""))
            if not name.endswith(".mp4") or not os.path.exists(os.path.join(cfg["originals_dir"], name)):
                return self._json({"ok": False, "error": "original not found"}, 404)
            st = read_json(state_path(cfg), {})
            st.pop(name, None)
            write_json(state_path(cfg), st)
            f = read_json(FAILED, {})
            f.pop(name, None)
            write_json(FAILED, f)
            shutil.rmtree(os.path.join(cfg["work_dir"], "process", name[:-4]), ignore_errors=True)
            return self._json({"ok": True})
        if path == "/api/cancel":
            open(CANCEL, "w").close()
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


def serve(capture, cfg):
    Handler.capture = capture
    srv = ThreadingHTTPServer((cfg["web_bind"], cfg["web_port"]), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="web").start()
    return srv
