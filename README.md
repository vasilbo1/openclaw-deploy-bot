# AI Server Admin Bot

A Telegram bot that manages servers, Docker containers, and [OpenClaw](https://openclaw.ai) AI agents. Create containers, update API keys, set up GitHub auto-deploy — all from Telegram.

## What you need

1. A Linux server ($5/mo on [Hetzner](https://www.hetzner.com/cloud/), [Hostinger](https://www.hostinger.com/vps-hosting), or any provider). After purchase you'll get an **IP address**, **login** and **password**.
2. [Claude Code](https://claude.ai/code) installed on your computer.
3. API keys: [Anthropic](https://console.anthropic.com/) and a Telegram bot token from [@BotFather](https://t.me/BotFather).

## How to deploy

**Step 1.** Download this repository:

```
git clone https://github.com/vasilbo1/openclaw-deploy-bot.git
```

Or click the green **Code** button on GitHub and select **Download ZIP**.

**Step 2.** Open the folder in Claude Code:

```
cd openclaw-deploy-bot
claude
```

**Step 3.** Paste this prompt:

```
Deploy this Telegram bot to my server. Read CLAUDE.md for full instructions.

Before starting, ask me for:
1. Server IP and login (SSH)
2. Server password
3. Telegram Bot Token (from @BotFather)
4. My Telegram ID (from @userinfobot)
5. Anthropic API Key
6. Do I need GitHub integration? If yes, I'll provide my GitHub token.
7. Do I need Google Sheets sync? If yes, I'll provide credentials.

After receiving the data:
- Connect to the server via SSH
- Copy all bot files to the server
- Install dependencies
- Generate ENCRYPTION_KEY and the bot's SSH key
- Create .env with my data
- Configure the systemd service and start the bot
- Verify the bot is running
```

**Step 4.** Answer Claude's questions — it will set everything up automatically.

**Step 5.** Open Telegram, find your bot, send `/start`. Done.

## What the bot can do

- **Servers** — add/remove servers, auto health check every 30 min
- **Containers** — create OpenClaw AI agents with one tap (auto-installs everything)
- **API Keys** — update Anthropic/OpenAI/Telegram tokens from chat
- **GitHub** — create repos, auto-setup deploy.yml + secrets, git init + push from server
- **Employees** — create SSH access + generate connection instructions
- **Pairing** — confirm OpenClaw Telegram pairing
- **Google Sheets** — auto-sync all data
- **Monitoring** — health checks + daily reports + OpenClaw update notifications

## GitHub auto-deploy

The bot can create a GitHub repository for any project on your server and configure automatic deployment:

1. Bot creates a private repo on GitHub
2. Sets up `deploy.yml` with correct branch detection (master/main)
3. Configures deployment secrets automatically
4. Runs `git init` + `git push` on the server
5. Every future push → server auto-updates (git pull + install deps + restart service)

To use this feature, add `GITHUB_TOKEN` to your `.env` (GitHub token with `repo` scope).

## Is it safe?

- You run the bot on **your own server**. Nothing goes through third parties.
- Server passwords are used once to copy an SSH key and are never stored.
- API keys are encrypted with Fernet before saving to the database.
- The code is fully open — read every line before running.

## License

MIT
