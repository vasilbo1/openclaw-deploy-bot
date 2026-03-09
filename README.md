# OpenClaw Deploy Bot

A Telegram bot that deploys [OpenClaw](https://openclaw.ai) AI agents on your own server. No technical skills required.

## Why

Services like [ClawPlane](https://www.clawplane.com/) charge you to host OpenClaw agents on their infrastructure. This bot does the same thing for free on a server you own.

## What you need

1. A Linux server ($5/mo on [Hetzner](https://www.hetzner.com/cloud/), [Hostinger](https://www.hostinger.com/vps-hosting), or any other provider). After purchase you'll get an **IP address**, **login** and **password**.
2. [Claude Code](https://claude.ai/code) installed on your computer.
3. API keys: [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/api-keys), and a Telegram bot token from [@BotFather](https://t.me/BotFather).

## How to use

**Step 1.** Download this repository to your computer:

```
git clone https://github.com/vasilbo1/openclaw-deploy-bot.git
```

Or click the green **Code** button on GitHub and select **Download ZIP**, then unzip it.

**Step 2.** Open the folder in Claude Code:

```
cd openclaw-deploy-bot
claude
```

**Step 3.** Paste this prompt into Claude Code:

```
Deploy this Telegram bot to my server. Read CLAUDE.md for full instructions.

Before starting, ask me for:
1. Server IP and login (SSH)
2. Telegram Bot Token (from @BotFather)
3. My Telegram ID (can be found via @userinfobot)
4. Anthropic API Key
5. Do I need Google Sheets sync? If yes, I will provide the service account JSON key and Sheet ID.

After receiving the data:
- Connect to the server via SSH
- Copy all bot files to the server
- Install dependencies
- Generate ENCRYPTION_KEY and the bot's SSH key
- Create .env with my data
- Configure the systemd service and start the bot
- Verify the bot is running
```

**Step 4.** Answer Claude Code's questions. It will ask for your server IP, password, and API keys. Then it connects to your server and sets everything up automatically.

**Step 5.** Open Telegram, find your bot, send `/start`. Done.

From there you can create OpenClaw containers right from the Telegram menu. The bot will ask for API keys and deploy a fully configured agent for you.

## What the bot can do

- **Servers** — add your Linux servers (IP + login)
- **Containers** — create OpenClaw AI agent containers with one tap
- **Employees** — give team members SSH access to specific containers
- **Pairing** — confirm OpenClaw Telegram pairing codes
- **Instructions** — generate Mac/Windows connection guides for your team
- **Admins** — manage who can use the bot

## Is it safe?

- You run the bot on **your own computer or server**. Nothing goes through third parties.
- Server passwords are used once to copy an SSH key and are never stored.
- API keys are encrypted before saving to the database.
- The code is fully open. Read every line before running.

## Google Sheets sync (optional)

The bot can auto-sync all data (servers, containers, employees) to a Google Sheet. To enable, set these in your `.env`:

```
GOOGLE_CREDENTIALS_PATH=/path/to/google-credentials.json
GOOGLE_SPREADSHEET_ID=your_sheet_id
```

If not configured, the bot works fine without it.

## How container deployment works under the hood

When you tap "OpenClaw container" in the bot menu, it:

1. Creates a Docker container on your server
2. Installs Node.js 22, OpenClaw, ffmpeg
3. Writes the OpenClaw config with your API keys
4. If any step fails, sends the error to Claude API, gets a fix command, and retries automatically
5. Starts the OpenClaw gateway

Your agent is live and connected to Telegram.

## License

MIT
