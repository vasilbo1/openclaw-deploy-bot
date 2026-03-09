# AI Server Admin Bot — Deployment Guide

## What is this

A Telegram bot for managing servers and Docker containers running OpenClaw AI agents.

**Features:**
- Server management (add/delete)
- Docker container creation with OpenClaw (automated Node.js 22 + OpenClaw installation, config setup, LLM-assisted error recovery on failures)
- Employee management (adding SSH keys into containers)
- OpenClaw Telegram pairing confirmation from the bot
- View connected users (paired users) with Telegram names
- Container renaming
- Mac/Windows connection instructions
- Bot admin management
- Auto-sync of all data to Google Sheets

## Stack

- Python 3.10+
- python-telegram-bot 20.7
- paramiko (SSH)
- aiosqlite (SQLite)
- cryptography (Fernet encryption)
- anthropic (LLM-assisted deployment)
- gspread (Google Sheets sync)
- aiohttp

## Files

```
tgbot/
├── bot.py              # Main bot (ConversationHandler, 27 states, all menus)
├── database.py         # Async SQLite: servers, containers, employees, API keys, admins
├── ssh_manager.py      # SSH/Docker operations via paramiko, OpenClaw container creation
├── sheets_sync.py      # SQLite → Google Sheets sync on every change
├── crypto.py           # Fernet encryption/decryption of API keys
├── instructions.py     # Mac/Windows connection instruction templates
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── tgbot.service.example # Systemd unit file
├── .gitignore          # Git exclusions
└── CLAUDE.md           # This file
```

## Deployment

### Step 1: Gather required data

Before starting deployment, ask the user for:

1. **Server IP** and **login** for SSH (usually root)
2. **Telegram Bot Token** — created via @BotFather
3. **Administrator's Telegram ID** — can be found via @userinfobot
4. **Anthropic API Key** — for LLM-assisted container deployment (https://console.anthropic.com/)
5. **Google Sheets** (optional):
   - Google Service Account JSON credentials (created in Google Cloud Console → APIs & Services → Credentials → Create Service Account → Keys → Add Key → JSON)
   - Google Sheet ID to which this Service Account has been granted Editor access

### Step 2: Connect to server and install

```bash
ssh root@<SERVER_IP>

# Install system dependencies
apt update && apt install -y python3 python3-pip

# Create directory
mkdir -p /root/tgbot
cd /root/tgbot
```

Copy all `.py` files and `requirements.txt` to the server at `/root/tgbot/`.

```bash
# Install Python dependencies
pip install -r requirements.txt --break-system-packages
```

### Step 3: Configure .env

Create `/root/tgbot/.env` based on `.env.example`:

```bash
# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```env
BOT_TOKEN=<telegram_bot_token>
ADMIN_IDS=<telegram_user_id>
ENCRYPTION_KEY=<generated_key>
ANTHROPIC_API_KEY=<anthropic_api_key>
```

### Step 4: Bot SSH key

The bot uses an SSH key to connect to servers. Generate it:

```bash
mkdir -p /root/tgbot/ssh_keys
ssh-keygen -t ed25519 -f /root/tgbot/ssh_keys/id_ed25519 -N ""
```

Add the public key to all servers the bot will manage:

```bash
cat /root/tgbot/ssh_keys/id_ed25519.pub >> /root/.ssh/authorized_keys
# For remote servers:
ssh-copy-id -i /root/tgbot/ssh_keys/id_ed25519.pub root@<OTHER_SERVER_IP>
```

### Step 5: Google Sheets (optional)

If Google Sheets sync is needed:

1. Place the Google Service Account JSON file on the server (e.g. `/root/tgbot/google-credentials.json`)
2. Update `CREDENTIALS_PATH` in `sheets_sync.py` with the path to your JSON
3. Update `SPREADSHEET_ID` in `sheets_sync.py` with your sheet ID
4. Share the Google Sheet with the service account email (from the JSON, `client_email` field) with Editor permissions

If Google Sheets is not needed — sync simply won't run and won't affect the bot (errors are logged but don't break anything).

### Step 6: Systemd service

```bash
cp /root/tgbot/tgbot.service.example /etc/systemd/system/tgbot.service
systemctl daemon-reload
systemctl enable tgbot
systemctl start tgbot
```

Verify:
```bash
systemctl status tgbot
journalctl -u tgbot -n 50
```

### Step 7: First launch

After starting:
1. Send `/start` to the bot in Telegram
2. Add a server (IP, login)
3. Create a container (the bot will ask for API keys: Anthropic, OpenAI, Telegram Bot Token for the agent)

## Architecture

### OpenClaw container creation

When creating a container, the bot:
1. Creates a Docker container based on `ubuntu:latest` with a startup wrapper (waits for the `/ready` file)
2. Installs Node.js 22, OpenClaw, ffmpeg, Python
3. Writes OpenClaw config (`openclaw.json`, `auth-profiles.json`) via base64
4. If a step fails — sends the error to the Claude API, gets a fix command, executes it and retries (up to 3 times)
5. Creates `/entrypoint.sh` and sets the `/ready` flag — the container starts the gateway

### Encryption

API keys (Anthropic, OpenAI, Telegram token) are encrypted with Fernet before being written to SQLite. The encryption key is stored in `.env`.

### Google Sheets sync

On every database change (add/delete/modify servers, containers, employees, admins), data is automatically pushed to Google Sheets. Sync runs as a fire-and-forget asyncio task and does not block the bot.

Sheets: Servers, Containers (with Telegram IDs of paired users), Employees, Admins.
