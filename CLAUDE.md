# Dev Rules

- **Default branch is `master`**, not `main`. All PRs must target `master`. Deploy workflows must trigger on `master`.
- When creating `deploy.yml` for any repo (including via the bot's GitHub feature), always check the actual default branch name — do not assume `main`.

# AI Server Admin Bot

Telegram bot for managing servers, Docker containers, and employees running [OpenClaw](https://openclaw.ai) AI agents.

## Features

- **Server management** — add/delete servers, SSH connectivity check
- **Docker container management** — automated OpenClaw container creation (Node.js 22 + OpenClaw + ffmpeg + Python, LLM-assisted error recovery), rename, delete
- **🔑 API Keys** — view and update Anthropic, OpenAI, and Telegram bot tokens for any container. Shows masked labels (`sk-ant...L9uAAAA`), updates config files inside containers, auto-restarts gateway. User messages with keys are auto-deleted for security
- **GitHub integration** — create private repos, auto-setup deploy.yml + secrets, auto git init + push from server. Delete repos with confirmation
- **Employee management** — create Linux user + SSH key + docker group + auto-login into container
- **Pairing** — confirm OpenClaw Telegram pairing from the bot, save @username
- **Paired Users** — view/edit paired users per container
- **Container health monitoring** — background check every 30 min (DOWN alert with last log lines), daily report at 08:00 UTC
- **OpenClaw update checker** — checks for new versions every 6 hours
- **Google Sheets sync** — auto-syncs all data (servers, containers, employees, admins, paired users) on every change
- **Connection instructions** — generates Mac/Windows SSH/SCP/Claude Code instructions per employee
- **Admin management** — add/remove bot administrators

## Quick Start with Claude Code

The fastest way to deploy is to give this project to Claude Code and let it set everything up.

### Prerequisites

1. A Linux server (Ubuntu 22.04+) with root SSH access
2. A Telegram bot token from [@BotFather](https://t.me/BotFather)
3. Your Telegram user ID (get it from [@userinfobot](https://t.me/userinfobot))
4. An [Anthropic API key](https://console.anthropic.com/) (for LLM-assisted container deployment)
5. (Optional) A GitHub personal access token with `repo` scope (for GitHub integration)
6. (Optional) Google Service Account JSON + Google Sheet ID for data sync

### Deploy via Claude Code

Open this repository in Claude Code and say:

```
Deploy this bot to my server <IP>. Here are the credentials:
- Telegram bot token: <token>
- My Telegram ID: <id>
- Anthropic API key: <key>
```

Claude Code will:
1. SSH into your server and install dependencies
2. Copy all project files
3. Generate encryption key and create `.env`
4. Generate SSH key pair for the bot
5. Set up systemd service with auto-restart
6. Start the bot and verify it's running

After deployment, send `/start` to your bot in Telegram.

## Manual Deployment

### 1. Install on server

```bash
ssh root@<SERVER_IP>
apt update && apt install -y python3 python3-pip git

git clone <this-repo-url> /root/tgbot
cd /root/tgbot
pip install -r requirements.txt --break-system-packages
```

### 2. Configure environment

```bash
# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Create .env from template
cp .env.example .env
nano .env  # Fill in BOT_TOKEN, ADMIN_IDS, ENCRYPTION_KEY, ANTHROPIC_API_KEY
```

### 3. Generate bot SSH key

The bot connects to servers via SSH to manage Docker containers:

```bash
mkdir -p /root/tgbot/ssh_keys
ssh-keygen -t ed25519 -f /root/tgbot/ssh_keys/id_ed25519 -N ""

# Authorize on the local server
cat /root/tgbot/ssh_keys/id_ed25519.pub >> /root/.ssh/authorized_keys

# For remote servers:
ssh-copy-id -i /root/tgbot/ssh_keys/id_ed25519.pub root@<OTHER_SERVER_IP>
```

### 4. GitHub integration (optional)

To enable GitHub features (create repos, auto-deploy setup):

1. Create a GitHub Personal Access Token with `repo` scope
2. Add `GITHUB_TOKEN=<token>` to `.env`
3. Generate a deploy key: `ssh-keygen -t ed25519 -f /root/tgbot/ssh_keys/deploy_id_ed25519 -N ""`

### 5. Google Sheets sync (optional)

1. Create a Google Service Account in [Google Cloud Console](https://console.cloud.google.com/)
2. Place the JSON file on the server (e.g. `/root/tgbot/google-credentials.json`)
3. Update `CREDENTIALS_PATH` and `SPREADSHEET_ID` in `sheets_sync.py`
4. Share your Google Sheet with the service account email (Editor access)

If not configured, sync silently skips — no errors.

### 6. Start as a service

```bash
cp tgbot.service.example /etc/systemd/system/tgbot.service
systemctl daemon-reload
systemctl enable tgbot
systemctl start tgbot

# Verify
systemctl status tgbot
journalctl -u tgbot -n 50
```

### 7. First launch

1. Send `/start` to the bot in Telegram
2. Add a server (IP, login)
3. Create a container (bot will ask for: Anthropic key, OpenAI key, Telegram bot token)

## Files

```
tgbot/
├── bot.py                  # Main bot — ConversationHandler (35 states)
├── database.py             # Async SQLite: servers, containers, employees, API keys, admins, paired users
├── ssh_manager.py          # SSH/Docker via paramiko: container creation, API key updates, health checks
├── github.py               # GitHub API: create/delete repos, manage secrets, auto-deploy setup
├── sheets_sync.py          # Auto-sync SQLite → Google Sheets on every DB change
├── crypto.py               # Fernet encryption/decryption of API keys
├── instructions.py         # Mac/Windows connection instruction templates
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── tgbot.service.example   # Systemd unit file template
└── CLAUDE.md               # This file (also serves as Claude Code context)
```

## Architecture

### Container creation flow

1. Creates Docker container from `ubuntu:latest` with a startup wrapper
2. Installs Node.js 22, OpenClaw, ffmpeg, Python inside the container
3. Writes `openclaw.json` and `auth-profiles.json` via base64 encoding
4. On failure — sends error to Claude API, gets fix command, retries (up to 3 attempts)
5. Creates `/entrypoint.sh`, sets ready flag — container starts the gateway

### GitHub integration flow

1. Creates a private repo via GitHub API
2. Generates `deploy.yml` (detects actual branch name — master or main)
3. Sets `DEPLOY_HOST` and `DEPLOY_KEY` secrets via GitHub API
4. SSHs into server, runs `git init`, `git add -A`, `git commit`, `git push`
5. Replaces HTTPS remote with SSH URL for future operations
6. Result: auto-deploy on every push (git pull + pip/npm install + systemctl restart)

**Important:** deploy.yml uses `--break-system-packages` for pip on Ubuntu 22.04+ (PEP 668).

### API Keys management

Updates individual keys on running containers without recreating them:

- **Anthropic**: `auth-profiles.json` > `profiles.anthropic:default.key`
- **OpenAI**: `auth-profiles.json` + `openclaw.json` (`env.OPENAI_API_KEY` + `skills.entries.openai-whisper-api.apiKey`)
- **Telegram token**: `openclaw.json` > `channels.telegram.botToken`

### Encryption

All API keys are encrypted with Fernet before storing in SQLite. The encryption key lives in `.env` and is never committed.

### Monitoring

Two background asyncio tasks (`post_init`):

- **Health monitor** (30 min) — checks `docker ps` across all servers, alerts on DOWN containers
- **Update checker** (6 hours) — checks `openclaw --version` for new releases

## Stack

- Python 3.10+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 20.7
- [paramiko](https://github.com/paramiko/paramiko) — SSH
- [aiosqlite](https://github.com/omnilib/aiosqlite) — async SQLite
- [cryptography](https://github.com/pyca/cryptography) — Fernet encryption
- [anthropic](https://github.com/anthropics/anthropic-sdk-python) — LLM-assisted deployment
- [gspread](https://github.com/burnash/gspread) — Google Sheets
- [aiohttp](https://github.com/aio-libs/aiohttp) — HTTP client
- [pynacl](https://github.com/pyca/pynacl) — GitHub secret encryption

## License

MIT
