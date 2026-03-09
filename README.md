# OpenClaw Deploy Bot

A Telegram bot that deploys [OpenClaw](https://openclaw.ai) AI agents on your server in minutes. No DevOps knowledge required.

## What it does

You buy a Linux server, give the bot your IP and password, and it sets everything up: Docker, Node.js, OpenClaw, config files, entrypoint. If something fails mid-deploy, it sends the error to Claude API and fixes it automatically.

After setup, you manage everything from a Telegram menu:

- **Servers** — add/remove Linux servers
- **Containers** — create OpenClaw containers, rename, delete
- **Employees** — add team members' SSH keys to containers
- **Pairing** — confirm OpenClaw Telegram pairing from the bot
- **Instructions** — generate Mac/Windows connection guides for your team
- **Admins** — manage who can access the bot

## How to deploy

The easiest way is with [Claude Code](https://claude.ai/code):

1. Open this folder in Claude Code
2. Paste the prompt from [PROMPT.md](PROMPT.md)
3. Answer 5 questions (server IP, bot token, Telegram ID, API key, Google Sheets)
4. Claude Code SSHes into your server and sets everything up

Full manual instructions: [CLAUDE.md](CLAUDE.md)

## Requirements

- A Linux server (any VPS, $5/mo is enough)
- Python 3.10+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Anthropic API Key (for LLM-assisted deployment)
- OpenAI API Key (for the agent)

## Quick start (manual)

```bash
git clone https://github.com/vasilbo1/openclaw-deploy-bot.git
cd openclaw-deploy-bot

pip install -r requirements.txt

# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Create .env
cp .env.example .env
# Edit .env with your tokens

# Generate SSH key for the bot
mkdir -p ssh_keys
ssh-keygen -t ed25519 -f ssh_keys/id_ed25519 -N ""

# Run
python3 bot.py
```

## Google Sheets sync (optional)

The bot can auto-sync all data to Google Sheets. Set these environment variables:

```
GOOGLE_CREDENTIALS_PATH=/path/to/google-credentials.json
GOOGLE_SPREADSHEET_ID=your_sheet_id
```

If not configured, the bot works without it.

## Security

- The bot runs on **your machine** — nothing goes through third parties
- API keys are encrypted with Fernet before storing in SQLite
- Server passwords are used once (to copy the SSH key) and never stored
- All code is open — read every line before running

## Architecture

```
bot.py              — Telegram bot (menus, conversation handler, 27 states)
database.py         — async SQLite (servers, containers, employees, API keys, admins)
ssh_manager.py      — SSH/Docker operations via paramiko
sheets_sync.py      — SQLite → Google Sheets sync
crypto.py           — Fernet encryption for API keys
instructions.py     — Mac/Windows connection guide templates
```

### How container creation works

1. Creates a Docker container from `ubuntu:latest`
2. Installs Node.js 22, OpenClaw, ffmpeg, Python
3. Writes OpenClaw config and auth profiles
4. If a step fails — sends the error to Claude API, gets a fix, retries (up to 3x)
5. Creates entrypoint and starts the OpenClaw gateway

## License

MIT
