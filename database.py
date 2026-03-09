import os
import aiosqlite
from datetime import datetime
from sheets_sync import schedule_sync

DB_PATH = os.path.join(os.path.dirname(__file__), 'data.db')

async def create_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL,
                login TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS containers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                port INTEGER,
                type TEXT DEFAULT 'empty',
                openclaw_profile TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                container_id INTEGER,
                ssh_key TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (container_id) REFERENCES containers(id)
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_id INTEGER NOT NULL,
                anthropic_key_encrypted TEXT,
                openai_key_encrypted TEXT,
                telegram_token_encrypted TEXT,
                FOREIGN KEY (container_id) REFERENCES containers(id)
            );
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                added_by TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        # Migration: add openclaw_profile if missing
        try:
            await db.execute("ALTER TABLE containers ADD COLUMN openclaw_profile TEXT DEFAULT ''")
            await db.commit()
        except Exception:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE api_keys ADD COLUMN bot_username TEXT DEFAULT ''")
            await db.commit()
        except Exception:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE api_keys ADD COLUMN anthropic_label TEXT DEFAULT ''")
            await db.execute("ALTER TABLE api_keys ADD COLUMN openai_label TEXT DEFAULT ''")
            await db.commit()
        except Exception:
            pass
        await db.commit()

async def seed_admins():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
    admin_ids = os.getenv('ADMIN_IDS', '')
    async with aiosqlite.connect(DB_PATH) as db:
        for tid in admin_ids.split(','):
            tid = tid.strip()
            if tid:
                await db.execute(
                    "INSERT OR IGNORE INTO admins (telegram_id, name, added_by) VALUES (?, ?, ?)",
                    (tid, 'Owner', 'system')
                )
        await db.commit()

async def is_admin(telegram_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM admins WHERE telegram_id=?", (str(telegram_id),))
        return await cur.fetchone() is not None

async def add_server(name, ip, login):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO servers (name, ip, login) VALUES (?,?,?)", (name, ip, login))
        await db.commit()
        schedule_sync()
        return cur.lastrowid

async def get_servers():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM servers WHERE status='active' ORDER BY id")
        return await cur.fetchall()

async def delete_server(server_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE servers SET status='deleted' WHERE id=?", (server_id,))
        await db.commit()
    schedule_sync()

async def add_container(server_id, name, port, ctype='empty', openclaw_profile=''):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO containers (server_id, name, port, type, openclaw_profile) VALUES (?,?,?,?,?)",
            (server_id, name, port, ctype, openclaw_profile))
        await db.commit()
        schedule_sync()
        return cur.lastrowid

async def get_containers(server_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if server_id:
            cur = await db.execute(
                "SELECT c.*, s.ip, s.login FROM containers c JOIN servers s ON c.server_id=s.id WHERE c.server_id=? AND c.status='active' ORDER BY c.id",
                (server_id,))
        else:
            cur = await db.execute(
                "SELECT c.*, s.ip, s.login, s.name as server_name FROM containers c JOIN servers s ON c.server_id=s.id WHERE c.status='active' ORDER BY c.id")
        return await cur.fetchall()

async def get_container(container_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT c.*, s.ip, s.login, s.name as server_name FROM containers c JOIN servers s ON c.server_id=s.id WHERE c.id=?",
            (container_id,))
        return await cur.fetchone()

async def delete_container(container_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE containers SET status='deleted' WHERE id=?", (container_id,))
        await db.commit()
    schedule_sync()

def make_key_label(key: str) -> str:
    """Generate short label from API key: first 6 + ... + last 4."""
    if not key or len(key) < 12:
        return key or ''
    return key[:6] + '...' + key[-4:]

async def add_api_keys(container_id, anthropic_enc, openai_enc, tg_enc, bot_username='', anthropic_label='', openai_label=''):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO api_keys (container_id, anthropic_key_encrypted, openai_key_encrypted, telegram_token_encrypted, bot_username, anthropic_label, openai_label) VALUES (?,?,?,?,?,?,?)",
            (container_id, anthropic_enc, openai_enc, tg_enc, bot_username, anthropic_label, openai_label))
        await db.commit()
    schedule_sync()

async def get_api_keys(container_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM api_keys WHERE container_id=?", (container_id,))
        return await cur.fetchone()

async def update_bot_username(container_id, bot_username):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE api_keys SET bot_username=? WHERE container_id=?",
                         (bot_username, container_id))
        await db.commit()
    schedule_sync()

async def add_employee(name, container_id, ssh_key):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO employees (name, container_id, ssh_key) VALUES (?,?,?)",
            (name, container_id, ssh_key))
        await db.commit()
        schedule_sync()
        return cur.lastrowid

async def get_employees():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT e.*, c.name as container_name FROM employees e LEFT JOIN containers c ON e.container_id=c.id ORDER BY e.id")
        return await cur.fetchall()

async def delete_employee(emp_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM employees WHERE id=?", (emp_id,))
        await db.commit()
    schedule_sync()

async def add_admin(telegram_id, name, added_by):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO admins (telegram_id, name, added_by) VALUES (?,?,?)",
            (str(telegram_id), name, str(added_by)))
        await db.commit()
    schedule_sync()

async def get_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM admins ORDER BY id")
        return await cur.fetchall()

async def remove_admin(admin_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE id=?", (admin_id,))
        await db.commit()
    schedule_sync()

async def rename_container(container_id, new_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE containers SET name=? WHERE id=?", (new_name, container_id))
        await db.commit()
    schedule_sync()
