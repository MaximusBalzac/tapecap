# Notifications

TapeCap can send a phone message:
- 📼 **when a tape finishes recording**, with a thumbnail: *"Tape finished recording (24 min) – ready for the next tape."*
- ✅ **when a tape has been processed**, with the contact sheet: length, number of chapters, whether speech was found, upscaled or not, and the folder.
- ⚠️ **if processing fails**, with the error.

Messages are sent through **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** (`hermes send`), which can deliver to Telegram and other platforms it's connected to.

## Setup

1. Install Hermes Agent and connect it to Telegram (see the Hermes docs). Check it works:
   ```bash
   hermes send -t telegram:<chat-id> "test from TapeCap"
   ```
   Use an **explicit chat ID** (`telegram:123456789`). A bare `telegram` target only works if Hermes has a Telegram "home channel" set.
2. In TapeCap's **Settings → Notifications**, set:
   - **Phone messages** to `hermes`
   - **Send to** to `telegram:<chat-id>`
3. Save. The next finished tape sends a message.

To find your chat ID, send your bot a message, then check Hermes's channel directory, or use a bot such as @userinfobot.

## Troubleshooting

Every message, and Hermes's JSON reply, is logged in `~/.local/state/tapecap/notify.log`:

```
2026-11-24 21:30:02 📼 Tape finished recording (24.1 min) – ready for the next tape.
{"success": true, "platform": "telegram", "chat_id": "123456789", "message_id": "512"}
```

- No log lines at all: notifications are off, or the `hermes` command wasn't found. Set **hermes_bin** in the config file to the full path.
- `"error": "No home channel set"`: use an explicit `telegram:<chat-id>` target.
- Notifications never block or break recording. If sending fails, it's logged and capture carries on.

## Letting Hermes operate TapeCap

Hermes (or any agent) can use the [API](api.md) to answer questions such as *"is it recording?"*, show the live picture, or change settings on request. A Hermes skill that does this looks like:

```markdown
---
name: tapecap
description: Check and operate the TapeCap tape digitizer (status, live picture, settings).
---
- Status: curl -s http://localhost:8787/api/status   (report .state and .detail)
- Live picture: curl -s -o /tmp/now.png http://localhost:8787/api/preview.png, then describe it
- Change a setting: POST JSON to /api/config (only the keys to change)
- Never restart tapecap while .state is "recording".
```

## Other notification systems

`tapecap/notify.py` is a single short function. To use something else (ntfy, Pushover, e-mail, Home Assistant), replace the `subprocess.Popen([...hermes...])` call with your own. It receives the message text and an optional image path.
