# How to deploy

Open this folder in [Claude Code](https://claude.ai/code) and paste the prompt below.

Claude Code will ask you a few questions (server IP, password, API keys), then connect to your server and set everything up.

---

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
- Copy all bot files to the server at /root/tgbot/
- Install dependencies (apt + pip)
- Generate ENCRYPTION_KEY and the bot's SSH key
- Create .env with my data
- Configure the systemd service and start the bot
- If I provided Google Sheets data, configure sheets_sync.py
- Verify the bot is running (systemctl status + journalctl)
```
