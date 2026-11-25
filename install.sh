#!/usr/bin/env bash
# TapeCap installer for Debian / Ubuntu / Raspberry Pi OS.
#   ./install.sh              install + start the service for the current user
#   ./install.sh --no-upscaler  skip downloading Real-ESRGAN (x86-64 only anyway)
set -euo pipefail
APP="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
WANT_UPSCALER=1
[ "${1:-}" = "--no-upscaler" ] && WANT_UPSCALER=0

echo "== Installing system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg v4l-utils alsa-utils python3-venv vulkan-tools unzip curl >/dev/null

echo "== Python environment"
[ -d "$APP/venv" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q numpy faster-whisper

if [ "$WANT_UPSCALER" = 1 ] && [ "$(uname -m)" = "x86_64" ] && [ ! -x "$APP/tools/realesrgan/realesrgan-ncnn-vulkan" ]; then
  echo "== Downloading Real-ESRGAN (AI upscaler, used only if a supported GPU is present)"
  mkdir -p "$APP/tools/realesrgan"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/r.zip" \
    https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip
  unzip -q -o "$tmp/r.zip" -d "$APP/tools/realesrgan"
  chmod +x "$APP/tools/realesrgan/realesrgan-ncnn-vulkan"
  rm -rf "$tmp"
fi

echo "== systemd service"
sudo tee /etc/systemd/system/tapecap.service >/dev/null <<EOF
[Unit]
Description=TapeCap – automatic VHS/camcorder tape capture
After=network-online.target local-fs.target sound.target
Wants=network-online.target

[Service]
User=$USER_NAME
SupplementaryGroups=video audio render
WorkingDirectory=$APP
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP/venv/bin/python -m tapecap
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now tapecap
sleep 3
PORT=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~$USER_NAME/.config/tapecap/config.json'))).get('web_port',8787))" 2>/dev/null || echo 8787)
echo
echo "TapeCap is running. Open the control panel:  http://$(hostname).local:$PORT/"
echo "Logs: journalctl -u tapecap -f"
