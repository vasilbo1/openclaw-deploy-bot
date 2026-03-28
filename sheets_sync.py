"""Sync tgbot SQLite database to Google Sheets."""
import asyncio
import logging
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

CREDENTIALS_PATH = "/root/tochka-sheets/google-credentials.json"
SPREADSHEET_ID = "1MssLAXW8qUlITgYGdgj6voVXfHsLoL3R67iRbCLBP9I"
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
    """Blocking sync — runs in executor.
    paired_data: {container_id: [{"telegram_id": ..., "telegram_username": ...}]}
    """
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    # --- Серверы ---
    headers = ["ID", "Название", "IP", "Логин", "Контейнеров"]
    ws = _get_or_create_sheet(sh, "Серверы", headers)
    rows = []
    for s in servers:
        cont_count = sum(1 for c in containers if c["server_id"] == s["id"])
        rows.append([s["id"], s["name"], s["ip"], s["login"], cont_count])
    # Clear old data (keep header), write new
    ws.batch_clear(["A2:Z1000"])
    if rows:
        ws.update(rows, f'A2:E{1 + len(rows)}')

    # --- Контейнеры ---
    headers = ["ID", "Сервер", "IP", "Название", "Порт", "Тип", "Модель",
               "Telegram-бот", "Anthropic API", "OpenAI API",
               "Telegram User", "Paired Users (Telegram ID)"]
    ws = _get_or_create_sheet(sh, "Контейнеры", headers)

    # Preserve existing API keys from the sheet (columns I, J = indices 8, 9)
    existing_rows = ws.get_all_values()
    existing_api_keys = {}  # {container_name: (anthropic_key, openai_key)}
    for row in existing_rows[1:]:  # skip header
        if len(row) >= 10:
            name = row[3]  # column D = Название
            existing_api_keys[name] = (row[8], row[9])  # columns I, J

    rows = []
    for c in containers:
        server_name = next((s["name"] for s in servers if s["id"] == c["server_id"]), "?")
        bot_uname = c.get("bot_username") or ""
        ant_label = c.get("anthropic_label") or ""
        oai_label = c.get("openai_label") or ""
        model = c.get("default_model") or ""
        paired_users = paired_data.get(c["id"], [])
        usernames_str = ", ".join(u["telegram_username"] for u in paired_users if u["telegram_username"])
        ids_str = ", ".join(u["telegram_id"] for u in paired_users)
        # Keep existing full API keys if present, only use DB label as fallback
        existing = existing_api_keys.get(c["name"], ("", ""))
        ant_value = existing[0] if existing[0] else ant_label
        oai_value = existing[1] if existing[1] else oai_label
        rows.append([c["id"], server_name, c["ip"], c["name"], c["port"], c["type"],
                     model, bot_uname, ant_value, oai_value, usernames_str, ids_str])
    ws.batch_clear(["A2:Z1000"])
    if rows:
        ws.update(rows, f'A2:L{1 + len(rows)}')

    # --- Сотрудники ---
    headers = ["ID", "Имя", "Контейнер", "Сервер"]
    ws = _get_or_create_sheet(sh, "Сотрудники", headers)
    rows = []
    for e in employees:
        cont_name = e.get("container_name") or "—"
        # Find server for this container
        server_name = ""
        for c in containers:
            if c["name"] == cont_name:
                server_name = next((s["name"] for s in servers if s["id"] == c["server_id"]), "")
                break
        rows.append([e["id"], e["name"], cont_name, server_name])
    ws.batch_clear(["A2:Z1000"])
    if rows:
        ws.update(rows, f'A2:D{1 + len(rows)}')

    # --- Админы ---
    headers = ["ID", "Telegram ID", "Имя", "Добавил"]
    ws = _get_or_create_sheet(sh, "Админы", headers)
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
    import database as db

    # Gather all data
    servers_raw = await db.get_servers()
    containers_raw = await db.get_containers()
    employees_raw = await db.get_employees()
    admins_raw = await db.get_admins()

    # Convert Row objects to plain dicts
    servers = [dict(s) for s in servers_raw]
    containers_list = [dict(c) for c in containers_raw]

    # Add bot_username to containers
    for c in containers_list:
        keys = await db.get_api_keys(c["id"])
        c["bot_username"] = keys["bot_username"] if keys and keys["bot_username"] else ""
        c["anthropic_label"] = keys["anthropic_label"] if keys and keys["anthropic_label"] else ""
        c["openai_label"] = keys["openai_label"] if keys and keys["openai_label"] else ""

    employees = [dict(e) for e in employees_raw]
    admins = [dict(a) for a in admins_raw]

    # Get paired users from DB (no SSH needed)
    paired_data = {}
    all_paired = await db.get_paired_users_db()
    for pu in all_paired:
        cid = pu["container_id"]
        if cid not in paired_data:
            paired_data[cid] = []
        paired_data[cid].append({
            "telegram_id": pu["telegram_id"],
            "telegram_username": pu["telegram_username"] or "",
        })

    # Run blocking gspread calls in executor
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _sync_blocking, servers, containers_list, employees, admins, paired_data)
    except Exception as e:
        logger.error(f"Sheets sync error: {e}")


def schedule_sync():
    """Fire-and-forget sync — call after any DB mutation."""
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
