"""Sync tgbot SQLite database to Google Sheets."""
import asyncio
import logging
import os
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", os.path.join(os.path.dirname(__file__), "google-credentials.json"))
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_gc = None

def _get_client():
    global _gc
    if _gc is None:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


def _get_or_create_sheet(spreadsheet, title, headers):
    """Get existing worksheet or create new one with headers."""
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=100, cols=len(headers))
    # Always set headers in row 1
    ws.update([headers], 'A1')
    return ws


def _sync_blocking(servers, containers, employees, admins, paired_data):
    """Blocking sync - runs in executor."""
    if not SPREADSHEET_ID:
        logger.info("GOOGLE_SPREADSHEET_ID not set, skipping sync")
        return

    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    # --- Servers ---
    headers = ["ID", "Name", "IP", "Login", "Containers"]
    ws = _get_or_create_sheet(sh, "Servers", headers)
    rows = []
    for s in servers:
        cont_count = sum(1 for c in containers if c["server_id"] == s["id"])
        rows.append([s["id"], s["name"], s["ip"], s["login"], cont_count])
    ws.batch_clear(["A2:Z1000"])
    if rows:
        ws.update(rows, f'A2:E{1 + len(rows)}')

    # --- Containers ---
    headers = ["ID", "Server", "IP", "Name", "Port", "Type", "Telegram Bot", "Anthropic API", "OpenAI API", "Paired Users (Telegram ID)"]
    ws = _get_or_create_sheet(sh, "Containers", headers)
    rows = []
    for c in containers:
        server_name = next((s["name"] for s in servers if s["id"] == c["server_id"]), "?")
        bot_uname = c.get("bot_username") or ""
        ant_label = c.get("anthropic_label") or ""
        oai_label = c.get("openai_label") or ""
        paired_ids = paired_data.get(c["id"], [])
        paired_str = ", ".join(str(uid) for uid in paired_ids)
        rows.append([c["id"], server_name, c["ip"], c["name"], c["port"], c["type"], bot_uname, ant_label, oai_label, paired_str])
    ws.batch_clear(["A2:Z1000"])
    if rows:
        ws.update(rows, f'A2:J{1 + len(rows)}')

    # --- Employees ---
    headers = ["ID", "Name", "Container", "Server"]
    ws = _get_or_create_sheet(sh, "Employees", headers)
    rows = []
    for e in employees:
        cont_name = e.get("container_name") or "—"
        server_name = ""
        for c in containers:
            if c["name"] == cont_name:
                server_name = next((s["name"] for s in servers if s["id"] == c["server_id"]), "")
                break
        rows.append([e["id"], e["name"], cont_name, server_name])
    ws.batch_clear(["A2:Z1000"])
    if rows:
        ws.update(rows, f'A2:D{1 + len(rows)}')

    # --- Admins ---
    headers = ["ID", "Telegram ID", "Name", "Added By"]
    ws = _get_or_create_sheet(sh, "Admins", headers)
    rows = []
    for a in admins:
        rows.append([a["id"], a["telegram_id"], a["name"], a.get("added_by") or ""])
    ws.batch_clear(["A2:Z1000"])
    if rows:
        ws.update(rows, f'A2:D{1 + len(rows)}')

    # Delete default Sheet1 if it exists and is empty
    try:
        default = sh.worksheet("Sheet1")
        if default.get_all_values() == []:
            sh.del_worksheet(default)
    except Exception:
        pass

    logger.info("Google Sheets sync complete")


async def sync_to_sheets():
    """Async wrapper: gather data from DB and sync to Google Sheets."""
    import aiosqlite
    import database as db
    import ssh_manager as ssh

    servers_raw = await db.get_servers()
    containers_raw = await db.get_containers()
    employees_raw = await db.get_employees()
    admins_raw = await db.get_admins()

    servers = [dict(s) for s in servers_raw]
    containers_list = [dict(c) for c in containers_raw]

    for c in containers_list:
        keys = await db.get_api_keys(c["id"])
        c["bot_username"] = keys["bot_username"] if keys and keys["bot_username"] else ""
        c["anthropic_label"] = keys["anthropic_label"] if keys and keys["anthropic_label"] else ""
        c["openai_label"] = keys["openai_label"] if keys and keys["openai_label"] else ""

    employees = [dict(e) for e in employees_raw]
    admins = [dict(a) for a in admins_raw]

    paired_data = {}
    for c in containers_list:
        if c["type"] == "openclaw":
            try:
                user_ids = ssh.get_paired_users(c["ip"], c["login"], c["name"], c.get("openclaw_profile") or "")
                paired_data[c["id"]] = user_ids
            except Exception:
                paired_data[c["id"]] = []

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _sync_blocking, servers, containers_list, employees, admins, paired_data)
    except Exception as e:
        logger.error(f"Sheets sync error: {e}")


def schedule_sync():
    """Fire-and-forget sync - call after any DB mutation."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_safe_sync())
    except Exception as e:
        logger.error(f"Failed to schedule sync: {e}")


async def _safe_sync():
    """Wrapper that catches all errors so the bot never crashes from sync issues."""
    try:
        await sync_to_sheets()
    except Exception as e:
        logger.error(f"Sheets sync failed: {e}")
