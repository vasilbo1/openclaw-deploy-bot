import logging
import os
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)
import database as db
import ssh_manager as ssh
import instructions
import github as gh
from crypto import encrypt, decrypt

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def resolve_bot_username(token: str) -> str:
    """Resolve bot username from Telegram token via getMe API."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return "@" + data["result"].get("username", "")
    except Exception:
        pass
    return ""

# States
(MAIN,
 SRV_NAME, SRV_IP, SRV_LOGIN, SRV_PASS,
 SRV_DEL,
 CONT_SERVER, CONT_NAME, CONT_PROFILE, CONT_ANTHROPIC, CONT_OPENAI, CONT_TG,
 CONT_DEL_SRV, CONT_DEL,
 EMP_NAME, EMP_CONT, EMP_KEY,
 EMP_DEL,
 ADMIN_NAME, ADMIN_ID,
 ADMIN_DEL,
 INST_CONT_MAC, INST_CONT_WIN,
 PAIR_CONT, PAIR_CODE,
 CONT_RENAME_SEL, CONT_RENAME_NAME,
 PAIR_USERNAME,
 PAIR_EDIT_CONT, PAIR_EDIT_USER, PAIR_EDIT_NAME,
 KEYS_CONT, KEYS_ANTHROPIC, KEYS_OPENAI, KEYS_TG_TOKEN,
 GITHUB_REPO_NAME, GITHUB_REPO_DESC, GITHUB_REPO_SERVER, GITHUB_REPO_PATH, GITHUB_REPO_SERVICE,
 GITHUB_DEL_REPO, GITHUB_DEL_CONFIRM,
) = range(42)


SHEETS_URL = "https://docs.google.com/spreadsheets/d/1MssLAXW8qUlITgYGdgj6voVXfHsLoL3R67iRbCLBP9I"

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 Servers", callback_data="menu_servers"),
         InlineKeyboardButton("📦 Containers", callback_data="menu_containers")],
        [InlineKeyboardButton("👥 Employees", callback_data="menu_employees"),
         InlineKeyboardButton("📋 Instructions", callback_data="menu_instructions")],
        [InlineKeyboardButton("⚙️ Administrators", callback_data="menu_admins"),
         InlineKeyboardButton("🗄 Database", url=SHEETS_URL)],
        [InlineKeyboardButton("🐙 GitHub", callback_data="menu_github")],
    ])


async def check_access(update: Update) -> bool:
    uid = update.effective_user.id
    if not await db.is_admin(uid):
        if update.callback_query:
            await update.callback_query.answer("⛔️ Access denied", show_alert=True)
        else:
            await update.message.reply_text("⛔️ Access denied")
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update):
        return ConversationHandler.END
    await update.message.reply_text("🤖 *AI Server Admin*", parse_mode='Markdown', reply_markup=main_keyboard())
    return MAIN


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled", reply_markup=main_keyboard())
    return MAIN


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await check_access(update):
        return MAIN
    data = q.data

    # ── SERVERS ──────────────────────────────────────────────────────────
    if data == "menu_servers":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Server list", callback_data="srv_list")],
            [InlineKeyboardButton("➕ Add server", callback_data="srv_add")],
            [InlineKeyboardButton("🗑 Delete server", callback_data="srv_del")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ])
        await q.edit_message_text("🖥 *Servers*", parse_mode='Markdown', reply_markup=kb)
        return MAIN

    if data == "srv_list":
        servers = await db.get_servers()
        if not servers:
            text = "No servers"
        else:
            text = "\n".join(f"• *{s['name']}* — `{s['ip']}` ({s['login']})" for s in servers)
        await q.edit_message_text(f"🖥 *Servers:*\n{text}", parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_servers")]]))
        return MAIN

    if data == "srv_add":
        await q.edit_message_text("Enter server *name*:", parse_mode='Markdown')
        return SRV_NAME

    if data == "srv_del":
        servers = await db.get_servers()
        if not servers:
            await q.edit_message_text("No servers", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_servers")]]))
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(s['name'], callback_data=f"srv_del_{s['id']}")] for s in servers] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_servers")]])
        await q.edit_message_text("Select server to delete:", reply_markup=kb)
        return SRV_DEL

    if data.startswith("srv_del_"):
        srv_id = int(data.split("_")[-1])
        await db.delete_server(srv_id)
        await q.edit_message_text("✅ Server deleted", reply_markup=main_keyboard())
        return MAIN

    # ── CONTAINERS ───────────────────────────────────────────────────────
    if data == "menu_containers":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Container list", callback_data="cont_list")],
            [InlineKeyboardButton("➕ Empty container", callback_data="cont_add_empty")],
            [InlineKeyboardButton("🦞 OpenClaw container", callback_data="cont_add_openclaw")],
            [InlineKeyboardButton("🔑 Confirm Pairing", callback_data="cont_pair")],
            [InlineKeyboardButton("👤 Paired Users", callback_data="paired_users")],
            [InlineKeyboardButton("🔑 API Keys", callback_data="cont_keys")],
            [InlineKeyboardButton("✏️ Rename", callback_data="cont_rename")],
            [InlineKeyboardButton("🗑 Delete container", callback_data="cont_del")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ])
        await q.edit_message_text("📦 *Containers*", parse_mode='Markdown', reply_markup=kb)
        return MAIN

    if data == "cont_list":
        servers = await db.get_servers()
        if not servers:
            await q.edit_message_text("No servers", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(s['name'], callback_data=f"cont_list_{s['id']}")] for s in servers] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_containers")]])
        await q.edit_message_text("Select server:", reply_markup=kb)
        return MAIN

    if data.startswith("cont_list_"):
        srv_id = int(data.split("_")[-1])
        conts = await db.get_containers(srv_id)
        if not conts:
            await q.edit_message_text("No containers", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        buttons = []
        for c in conts:
            label = f"{c['name']} | :{c['port']} | {c['type']}"
            if c['type'] == 'openclaw':
                paired = await db.get_paired_users_db(c['id'])
                label += f" | 👥 {len(paired)}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"cont_info_{c['id']}")])
        buttons.append([InlineKeyboardButton("« Back", callback_data="menu_containers")])
        await q.edit_message_text("📦 *Containers:*", parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup(buttons))
        return MAIN

    if data.startswith("cont_info_"):
        cont_id = int(data.split("_")[-1])
        c = await db.get_container(cont_id)
        if not c:
            await q.edit_message_text("Container not found", reply_markup=main_keyboard())
            return MAIN
        keys = await db.get_api_keys(c['id'])
        bot_uname = keys['bot_username'] if keys and keys['bot_username'] else ''
        lines = [
            f"📦 *{c['name']}*",
            f"Server: `{c['server_name']}` ({c['ip']})",
            f"Port: {c['port']}",
            f"Type: {c['type']}",
        ]
        if bot_uname:
            lines.append(f"Telegram bot: {bot_uname.replace(chr(95), chr(92)+chr(95))}")
        if c['type'] == 'openclaw':
            lines.append("")
            lines.append("*Connected users:*")
            paired = await db.get_paired_users_db(c['id'])
            if not paired:
                lines.append("No connected users")
            else:
                for u in paired:
                    uname = f" ({u['telegram_username']})" if u['telegram_username'] else ""
                    lines.append(f"• `{u['telegram_id']}`{uname}")
        buttons = [
            [InlineKeyboardButton("« Back to list", callback_data=f"cont_list_{c['server_id']}")],
        ]
        await q.edit_message_text("\n".join(lines), parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup(buttons))
        return MAIN

    if data in ("cont_add_empty", "cont_add_openclaw"):
        context.user_data['cont_type'] = 'empty' if data == "cont_add_empty" else 'openclaw'
        servers = await db.get_servers()
        if not servers:
            await q.edit_message_text("Add a server first", reply_markup=main_keyboard())
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(s['name'], callback_data=f"cont_srv_{s['id']}")] for s in servers] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_containers")]])
        await q.edit_message_text("Select server:", reply_markup=kb)
        return CONT_SERVER

    if data.startswith("cont_srv_"):
        srv_id = int(data.split("_")[-1])
        context.user_data['srv_id'] = srv_id
        servers = await db.get_servers()
        srv = next((s for s in servers if s['id'] == srv_id), None)
        if srv:
            context.user_data['srv_ip'] = srv['ip']
            context.user_data['srv_login'] = srv['login']
        await q.edit_message_text("Enter container *name*:", parse_mode='Markdown')
        return CONT_NAME

    if data == "cont_del":
        servers = await db.get_servers()
        if not servers:
            await q.edit_message_text("No servers", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(s['name'], callback_data=f"cont_del_srv_{s['id']}")] for s in servers] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_containers")]])
        await q.edit_message_text("Select server:", reply_markup=kb)
        return CONT_DEL_SRV

    if data.startswith("cont_del_srv_"):
        srv_id = int(data.split("_")[-1])
        conts = await db.get_containers(srv_id)
        if not conts:
            await q.edit_message_text("No containers", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(c['name'], callback_data=f"cont_del_{c['id']}")] for c in conts] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_containers")]])
        await q.edit_message_text("Select container to delete:", reply_markup=kb)
        return CONT_DEL

    if data.startswith("cont_del_") and not data.startswith("cont_del_srv_"):
        cont_id = int(data.split("_")[-1])
        cont = await db.get_container(cont_id)
        if cont:
            try:
                ssh.execute(cont['ip'], cont['login'], f"docker rm -f {cont['name']}")
            except Exception:
                pass
        await db.delete_container(cont_id)
        await q.edit_message_text("✅ Container deleted", reply_markup=main_keyboard())
        return MAIN

    # ── RENAME ───────────────────────────────────────────────────────────
    if data == "cont_rename":
        conts = await db.get_containers()
        if not conts:
            await q.edit_message_text("No containers",
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{c['name']} ({c['server_name']})", callback_data=f"rename_cont_{c['id']}")] for c in conts] +
            [[InlineKeyboardButton("« Back", callback_data="menu_containers")]]
        )
        await q.edit_message_text("Select container to rename:", reply_markup=kb)
        return CONT_RENAME_SEL

    if data.startswith("rename_cont_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['rename_cont_id'] = cont_id
        cont = await db.get_container(cont_id)
        await q.edit_message_text(
            f"Current name: *{cont['name']}*\nEnter *new name*:",
            parse_mode='Markdown'
        )
        return CONT_RENAME_NAME

    # ── PAIRED USERS MANAGEMENT ──────────────────────────────────────────
    if data == "paired_users":
        conts = await db.get_containers()
        openclaw_conts = [c for c in conts if c['type'] == 'openclaw']
        if not openclaw_conts:
            await q.edit_message_text("No OpenClaw containers",
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{c['name']} ({c['server_name']})", callback_data=f"pu_cont_{c['id']}")] for c in openclaw_conts] +
            [[InlineKeyboardButton("« Back", callback_data="menu_containers")]]
        )
        await q.edit_message_text("👤 *Paired Users* — select container:", parse_mode='Markdown', reply_markup=kb)
        return PAIR_EDIT_CONT

    if data.startswith("pu_cont_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['pu_cont_id'] = cont_id
        cont = await db.get_container(cont_id)
        paired = await db.get_paired_users_db(cont_id)
        if not paired:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="paired_users")]])
            await q.edit_message_text(f"👤 *{cont['name']}* — no paired users", parse_mode='Markdown', reply_markup=kb)
            return PAIR_EDIT_CONT
        buttons = [
            [InlineKeyboardButton(
                f"{u['telegram_username'] or u['telegram_id']} — ID {u['telegram_id']}",
                callback_data=f"pu_edit_{u['id']}"
            )] for u in paired
        ]
        buttons.append([InlineKeyboardButton("« Back", callback_data="paired_users")])
        await q.edit_message_text(
            f"👤 *{cont['name']}* — select user to edit username:",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))
        return PAIR_EDIT_USER

    if data.startswith("pu_edit_"):
        pu_id = int(data.split("_")[-1])
        context.user_data['pu_edit_id'] = pu_id
        # fetch the paired user record
        async def _get_pu(pid):
            import aiosqlite
            async with aiosqlite.connect(db.DB_PATH) as _db:
                _db.row_factory = aiosqlite.Row
                cur = await _db.execute("SELECT * FROM paired_users WHERE id=?", (pid,))
                return await cur.fetchone()
        pu = await _get_pu(pu_id)
        context.user_data['pu_cont_id'] = pu['container_id']
        context.user_data['pu_telegram_id'] = pu['telegram_id']
        await q.edit_message_text(
            f"Enter new Telegram username for ID `{pu['telegram_id']}`\n"
            f"Current: `{pu['telegram_username'] or '—'}`\n\n"
            f"Format: @username or just username",
            parse_mode='Markdown'
        )
        return PAIR_EDIT_NAME

    # ── API KEYS ──────────────────────────────────────────────────────────
    if data == "cont_keys":
        conts = await db.get_containers()
        openclaw_conts = [c for c in conts if c['type'] == 'openclaw']
        if not openclaw_conts:
            await q.edit_message_text("No OpenClaw containers",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{c['name']} ({c['server_name']})", callback_data=f"keys_cont_{c['id']}")] for c in openclaw_conts] +
            [[InlineKeyboardButton("« Back", callback_data="menu_containers")]]
        )
        await q.edit_message_text("🔑 *API Keys* — select container:", parse_mode='Markdown', reply_markup=kb)
        return KEYS_CONT

    if data.startswith("keys_cont_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['keys_cont_id'] = cont_id
        cont = await db.get_container(cont_id)
        if not cont:
            await q.edit_message_text("Container not found", reply_markup=main_keyboard())
            return MAIN
        keys = await db.get_api_keys(cont_id)

        ant_label = keys['anthropic_label'] if keys and keys['anthropic_label'] else '—'
        oai_label = keys['openai_label'] if keys and keys['openai_label'] else '—'
        bot_uname = keys['bot_username'] if keys and keys['bot_username'] else '—'

        text = (
            f"🔑 *API Keys — {cont['name']}*\n\n"
            f"*Anthropic:* `{ant_label}`\n"
            f"*OpenAI:* `{oai_label}`\n"
            f"*Telegram bot:* `{bot_uname}`\n"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Anthropic", callback_data=f"keys_upd_ant_{cont_id}"),
             InlineKeyboardButton("🔄 OpenAI", callback_data=f"keys_upd_oai_{cont_id}")],
            [InlineKeyboardButton("🔄 Telegram Token", callback_data=f"keys_upd_tg_{cont_id}")],
            [InlineKeyboardButton("« Back", callback_data="cont_keys")],
        ])
        await q.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)
        return MAIN

    if data.startswith("keys_upd_ant_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['keys_cont_id'] = cont_id
        cont = await db.get_container(cont_id)
        await q.edit_message_text(
            f"Enter new *Anthropic API key* for *{cont['name']}*:\n"
            f"_(your message will be auto-deleted)_",
            parse_mode='Markdown')
        return KEYS_ANTHROPIC

    if data.startswith("keys_upd_oai_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['keys_cont_id'] = cont_id
        cont = await db.get_container(cont_id)
        await q.edit_message_text(
            f"Enter new *OpenAI API key* for *{cont['name']}*:\n"
            f"_(your message will be auto-deleted)_",
            parse_mode='Markdown')
        return KEYS_OPENAI

    if data.startswith("keys_upd_tg_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['keys_cont_id'] = cont_id
        cont = await db.get_container(cont_id)
        await q.edit_message_text(
            f"Enter new *Telegram bot token* for *{cont['name']}*:\n"
            f"_(your message will be auto-deleted)_",
            parse_mode='Markdown')
        return KEYS_TG_TOKEN

    # ── PAIRING ──────────────────────────────────────────────────────────
    if data == "cont_pair":
        conts = await db.get_containers()
        openclaw_conts = [c for c in conts if c['type'] == 'openclaw']
        if not openclaw_conts:
            await q.edit_message_text("No OpenClaw containers",
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_containers")]]))
            return MAIN
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{c['name']} ({c['server_name']})", callback_data=f"pair_cont_{c['id']}")] for c in openclaw_conts] +
            [[InlineKeyboardButton("« Back", callback_data="menu_containers")]]
        )
        await q.edit_message_text("Select container for pairing confirmation:", reply_markup=kb)
        return PAIR_CONT

    if data.startswith("pair_cont_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['pair_cont_id'] = cont_id
        cont = await db.get_container(cont_id)
        profile = cont['openclaw_profile'] if cont['openclaw_profile'] else "default"
        await q.edit_message_text(
            f"Container: *{cont['name']}* (profile: `{profile}`)\n\n"
            f"Enter *pairing code* from the agent's Telegram bot:",
            parse_mode='Markdown'
        )
        return PAIR_CODE

    # ── EMPLOYEES ────────────────────────────────────────────────────────
    if data == "menu_employees":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Employee list", callback_data="emp_list")],
            [InlineKeyboardButton("➕ Add employee", callback_data="emp_add")],
            [InlineKeyboardButton("🗑 Delete employee", callback_data="emp_del")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ])
        await q.edit_message_text("👥 *Employees*", parse_mode='Markdown', reply_markup=kb)
        return MAIN

    if data == "emp_list":
        emps = await db.get_employees()
        if not emps:
            text = "No employees"
        else:
            text = "\n".join(f"• *{e['name']}* → {e['container_name'] or '—'}" for e in emps)
        await q.edit_message_text(f"👥 *Employees:*\n{text}", parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_employees")]]))
        return MAIN

    if data == "emp_add":
        await q.edit_message_text("Enter employee *name*:", parse_mode='Markdown')
        return EMP_NAME

    if data.startswith("emp_cont_"):
        cont_id = int(data.split("_")[-1])
        context.user_data['emp_cont_id'] = cont_id
        await q.edit_message_text("Send employee's public *SSH key*:", parse_mode='Markdown')
        return EMP_KEY

    if data == "emp_del":
        emps = await db.get_employees()
        if not emps:
            await q.edit_message_text("No employees", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_employees")]]))
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(e['name'], callback_data=f"emp_del_{e['id']}")] for e in emps] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_employees")]])
        await q.edit_message_text("Select employee to delete:", reply_markup=kb)
        return EMP_DEL

    if data.startswith("emp_del_"):
        emp_id = int(data.split("_")[-1])
        await db.delete_employee(emp_id)
        await q.edit_message_text("✅ Employee deleted", reply_markup=main_keyboard())
        return MAIN

    # ── INSTRUCTIONS ─────────────────────────────────────────────────────
    if data == "menu_instructions":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Mac Instructions", callback_data="inst_mac")],
            [InlineKeyboardButton("💻 Windows Instructions", callback_data="inst_win")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ])
        await q.edit_message_text("📋 *Instructions*", parse_mode='Markdown', reply_markup=kb)
        return MAIN

    if data in ("inst_mac", "inst_win"):
        context.user_data['inst_type'] = data
        conts = await db.get_containers()
        if not conts:
            await q.edit_message_text("No containers", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_instructions")]]))
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{c['name']} ({c['server_name']})", callback_data=f"inst_cont_{c['id']}")] for c in conts] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_instructions")]])
        await q.edit_message_text("Select container:", reply_markup=kb)
        return MAIN

    if data.startswith("inst_cont_"):
        cont_id = int(data.split("_")[-1])
        cont = await db.get_container(cont_id)
        inst_type = context.user_data.get('inst_type', 'inst_mac')
        if inst_type == 'inst_mac':
            text = instructions.get_mac_instruction(cont['ip'], cont['name'])
        else:
            text = instructions.get_windows_instruction(cont['ip'], cont['name'])
        await q.edit_message_text(text, parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_instructions")]]))
        return MAIN

    # ── ADMINISTRATORS ───────────────────────────────────────────────────
    if data == "menu_admins":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Administrator list", callback_data="adm_list")],
            [InlineKeyboardButton("➕ Add administrator", callback_data="adm_add")],
            [InlineKeyboardButton("🗑 Delete administrator", callback_data="adm_del")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ])
        await q.edit_message_text("⚙️ *Administrators*", parse_mode='Markdown', reply_markup=kb)
        return MAIN

    if data == "adm_list":
        admins = await db.get_admins()
        text = "\n".join(f"• *{a['name']}* | ID: `{a['telegram_id']}`" for a in admins) or "No administrators"
        await q.edit_message_text(f"⚙️ *Administrators:*\n{text}", parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_admins")]]))
        return MAIN

    if data == "adm_add":
        await q.edit_message_text("Enter *name* of new administrator:", parse_mode='Markdown')
        return ADMIN_NAME

    if data == "adm_del":
        admins = await db.get_admins()
        caller_id = str(update.effective_user.id)
        others = [a for a in admins if a['telegram_id'] != caller_id]
        if not others:
            await q.edit_message_text("No other administrators to delete",
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_admins")]]))
            return MAIN
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(a['name'], callback_data=f"adm_del_{a['id']}")] for a in others] +
                                   [[InlineKeyboardButton("« Back", callback_data="menu_admins")]])
        await q.edit_message_text("Select administrator to delete:", reply_markup=kb)
        return ADMIN_DEL

    if data.startswith("adm_del_"):
        adm_id = int(data.split("_")[-1])
        await db.remove_admin(adm_id)
        await q.edit_message_text("✅ Administrator deleted", reply_markup=main_keyboard())
        return MAIN


    # GitHub menu
    if data == "menu_github":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("+ Create repo", callback_data="gh_create")],
            [InlineKeyboardButton("Link existing repo", callback_data="gh_link")],
            [InlineKeyboardButton("🗑 Delete repo", callback_data="gh_delete")],
            [InlineKeyboardButton("Back", callback_data="back_main")],
        ])
        await q.edit_message_text("GitHub", reply_markup=kb)
        return MAIN

    if data == "gh_create":
        context.user_data["gh_mode"] = "create"
        await q.edit_message_text("Create GitHub repo\n\nEnter repo name:")
        return GITHUB_REPO_NAME

    if data == "gh_link":
        context.user_data["gh_mode"] = "link"
        repos = gh.list_repos()
        if not repos:
            await q.edit_message_text("Could not fetch repos.", reply_markup=main_keyboard())
            return MAIN
        # Show in pages of 10
        rows = [[InlineKeyboardButton(r.split("/")[1], callback_data=f"gh_selrepo_{r}")] for r in repos[:20]]
        rows.append([InlineKeyboardButton("Back", callback_data="menu_github")])
        kb = InlineKeyboardMarkup(rows)
        await q.edit_message_text("Select repository:", reply_markup=kb)
        return GITHUB_REPO_SERVER

    if data.startswith("gh_selrepo_"):
        full_name = data[len("gh_selrepo_"):]
        context.user_data["gh_repo_name"] = full_name
        context.user_data["gh_repo_desc"] = ""
        servers = await db.get_servers()
        if not servers:
            await q.edit_message_text("No servers in DB.", reply_markup=main_keyboard())
            return MAIN
        repo_short = full_name.split("/")[-1]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(s["name"], callback_data=f"gh_srv_{s['id']}_{s['ip']}")] for s in servers]
                                   + [[InlineKeyboardButton("Back", callback_data="gh_link")]])
        await q.edit_message_text(f"Repo: {full_name}\n\nSelect server:", reply_markup=kb)
        return GITHUB_REPO_SERVER

    if data.startswith("gh_srv_"):

        parts = data.split("_", 3)
        # gh_srv_{id}_{ip}
        srv_id = parts[2]
        srv_ip = parts[3] if len(parts) > 3 else ""
        context.user_data["gh_deploy_host"] = srv_ip
        repo_name = context.user_data.get("gh_repo_name", "project")
        default_path = "/root/" + repo_name
        default_service = repo_name + ".service"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Default ({default_path})", callback_data="gh_path_default")],
        ])
        await q.edit_message_text(f"Server: {srv_ip}\n\nDeploy path — enter custom or use default:", reply_markup=kb)
        return GITHUB_REPO_PATH

    if data == "gh_path_default":
        repo_name = context.user_data.get("gh_repo_name", "project")
        default_path = "/root/" + repo_name
        context.user_data['gh_deploy_path'] = default_path
        default_service = repo_name + ".service"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Default ({default_service})", callback_data="gh_service_default")],
        ])
        await q.edit_message_text(f"Path: {default_path}\n\nService name — enter custom, /skip, or use default:", reply_markup=kb)
        return GITHUB_REPO_SERVICE

    if data == "gh_service_default":
        repo_name = context.user_data.get("gh_repo_name", "project")
        context.user_data['gh_service'] = repo_name + ".service"
        await q.edit_message_text(f"Service: {repo_name}.service\n\nCreating repository...")
        return await _github_create(q, context)

    if data == "gh_delete":
        repos = gh.list_repos()
        if not repos:
            await q.edit_message_text("No repos found.", reply_markup=main_keyboard())
            return MAIN
        rows = [[InlineKeyboardButton(r.split("/")[1], callback_data=f"gh_delrepo_{r}")] for r in repos[:20]]
        rows.append([InlineKeyboardButton("Back", callback_data="menu_github")])
        kb = InlineKeyboardMarkup(rows)
        await q.edit_message_text("Select repo to delete:", reply_markup=kb)
        return GITHUB_DEL_REPO

    if data.startswith("gh_delrepo_"):
        full_name = data[len("gh_delrepo_"):]
        context.user_data["gh_del_repo"] = full_name
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, delete", callback_data="gh_del_yes"),
             InlineKeyboardButton("Cancel", callback_data="menu_github")],
        ])
        await q.edit_message_text(f"Are you sure you want to delete {full_name}?\n\nThis action cannot be undone!", reply_markup=kb)
        return GITHUB_DEL_CONFIRM

    if data == "gh_del_yes":
        full_name = context.user_data.get("gh_del_repo", "")
        _, status = gh.delete_repo(full_name)
        if status == 204:
            await q.edit_message_text(f"Repo {full_name} deleted.")
        else:
            await q.edit_message_text(f"Failed to delete {full_name} (status {status}).")
        return MAIN

    if data == "back_main":
        await q.edit_message_text("🤖 *AI Server Admin*", parse_mode='Markdown', reply_markup=main_keyboard())
        return MAIN

    return MAIN


# ── Message handlers ─────────────────────────────────────────────────────

async def srv_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv_name'] = update.message.text
    await update.message.reply_text("Enter server *IP*:", parse_mode='Markdown')
    return SRV_IP

async def srv_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv_ip_new'] = update.message.text
    await update.message.reply_text("Enter *login* (usually root):", parse_mode='Markdown')
    return SRV_LOGIN

async def srv_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv_login_new'] = update.message.text
    await update.message.reply_text("Enter *password* (needed once to copy the SSH key):", parse_mode='Markdown')
    return SRV_PASS

async def srv_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass
    name = context.user_data['srv_name']
    ip = context.user_data['srv_ip_new']
    login = context.user_data['srv_login_new']
    await context.bot.send_message(chat_id, "⏳ Connecting and copying SSH key...")
    try:
        ssh.copy_bot_key(ip, login, password)
        await db.add_server(name, ip, login)
        await context.bot.send_message(chat_id, f"✅ Server *{name}* added", parse_mode='Markdown', reply_markup=main_keyboard())
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Error: {e}", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def cont_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import re
    raw_name = update.message.text.strip().replace(' ', '-')
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]+$', raw_name):
        await update.message.reply_text(
            "❌ Invalid container name. Use only letters, digits, `-`, `_`, `.`\nNo spaces or special characters.",
            reply_markup=main_keyboard())
        return MAIN
    context.user_data['cont_name'] = raw_name
    if context.user_data.get('cont_type') == 'openclaw':
        context.user_data['cont_profile'] = ''
        await update.message.reply_text("Enter *Anthropic API key*:", parse_mode='Markdown')
        return CONT_ANTHROPIC
    else:
        await update.message.reply_text("⏳ Creating container...")
        ip = context.user_data['srv_ip']
        login = context.user_data['srv_login']
        name = context.user_data['cont_name']
        srv_id = context.user_data['srv_id']
        try:
            port = ssh.create_empty_container(ip, login, name)
            await db.add_container(srv_id, name, port, 'empty')
            await update.message.reply_text(f"✅ Container *{name}* created (port {port})", parse_mode='Markdown', reply_markup=main_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN


async def cont_anthropic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['anthropic_key'] = update.message.text
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass
    await context.bot.send_message(chat_id, "Enter *OpenAI API key*:", parse_mode='Markdown')
    return CONT_OPENAI

async def cont_openai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['openai_key'] = update.message.text
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass
    await context.bot.send_message(chat_id, "Enter *Telegram bot token*:", parse_mode='Markdown')
    return CONT_TG

async def cont_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tg_token'] = update.message.text
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass

    ip = context.user_data['srv_ip']
    login = context.user_data['srv_login']
    name = context.user_data['cont_name']
    srv_id = context.user_data['srv_id']
    profile = context.user_data.get('cont_profile', '')
    ak = context.user_data['anthropic_key']
    ok = context.user_data['openai_key']
    tt = context.user_data['tg_token']

    msg = await context.bot.send_message(chat_id, "⏳ Starting container deployment...")
    log = []

    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(
        None,
        lambda: ssh.create_openclaw_container(ip, login, name, ak, ok, tt, profile, log)
    )

    last_len = 0
    while not future.done():
        await asyncio.sleep(4)
        if len(log) > last_len:
            last_len = len(log)
            try:
                await msg.edit_text("⏳ Deploying...\n\n" + "\n".join(log))
            except Exception:
                pass

    try:
        port = await future
        cont_id = await db.add_container(srv_id, name, port, 'openclaw', profile)
        bot_uname = await resolve_bot_username(tt)
        await db.add_api_keys(cont_id, encrypt(ak), encrypt(ok), encrypt(tt), bot_uname, db.make_key_label(ak), db.make_key_label(ok))
        result = f"✅ OpenClaw container *{name}* created (port {port})\n\n" + "\n".join(log)
        await msg.edit_text(result[:4000], parse_mode='Markdown', reply_markup=main_keyboard())
    except Exception as e:
        log_text = "\n".join(log[-8:]) if log else ""
        await msg.edit_text(f"❌ Error: {e}\n\n{log_text}"[:4000], reply_markup=main_keyboard())

    context.user_data.clear()
    return MAIN

# ── API KEYS HANDLERS ────────────────────────────────────────────────────

async def keys_anthropic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_key = update.message.text.strip()
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass

    cont_id = context.user_data.get('keys_cont_id')
    if not cont_id:
        await context.bot.send_message(chat_id, "❌ Context lost, please start again", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN

    cont = await db.get_container(cont_id)
    msg = await context.bot.send_message(chat_id, f"⏳ Updating Anthropic key for *{cont['name']}*...", parse_mode='Markdown')

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: ssh.update_anthropic_key(
            cont['ip'], cont['login'], cont['name'], cont['openclaw_profile'] or '', new_key))
        label = db.make_key_label(new_key)
        await db.update_api_key(cont_id, 'anthropic', encrypt(new_key), label)
        await loop.run_in_executor(None, lambda: ssh.restart_gateway(
            cont['ip'], cont['login'], cont['name'], cont['openclaw_profile'] or '', force_restart=True))
        await msg.edit_text(f"✅ Anthropic key updated for *{cont['name']}*\n`{label}`\nGateway restarted",
                            parse_mode='Markdown', reply_markup=main_keyboard())
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def keys_openai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_key = update.message.text.strip()
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass

    cont_id = context.user_data.get('keys_cont_id')
    if not cont_id:
        await context.bot.send_message(chat_id, "❌ Context lost, please start again", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN

    cont = await db.get_container(cont_id)
    msg = await context.bot.send_message(chat_id, f"⏳ Updating OpenAI key for *{cont['name']}*...", parse_mode='Markdown')

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: ssh.update_openai_key(
            cont['ip'], cont['login'], cont['name'], cont['openclaw_profile'] or '', new_key))
        label = db.make_key_label(new_key)
        await db.update_api_key(cont_id, 'openai', encrypt(new_key), label)
        await loop.run_in_executor(None, lambda: ssh.restart_gateway(
            cont['ip'], cont['login'], cont['name'], cont['openclaw_profile'] or '', force_restart=True))
        await msg.edit_text(f"✅ OpenAI key updated for *{cont['name']}*\n`{label}`\nGateway restarted",
                            parse_mode='Markdown', reply_markup=main_keyboard())
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def keys_tg_token_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_token = update.message.text.strip()
    chat_id = update.message.chat_id
    try:
        await update.message.delete()
    except Exception:
        pass

    cont_id = context.user_data.get('keys_cont_id')
    if not cont_id:
        await context.bot.send_message(chat_id, "❌ Context lost, please start again", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN

    cont = await db.get_container(cont_id)
    msg = await context.bot.send_message(chat_id, f"⏳ Updating Telegram token for *{cont['name']}*...", parse_mode='Markdown')

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: ssh.update_telegram_token(
            cont['ip'], cont['login'], cont['name'], cont['openclaw_profile'] or '', new_token))
        await db.update_api_key(cont_id, 'telegram', encrypt(new_token))
        await loop.run_in_executor(None, lambda: ssh.restart_gateway(
            cont['ip'], cont['login'], cont['name'], cont['openclaw_profile'] or '', force_restart=True))
        # Resolve new bot username
        bot_uname = await resolve_bot_username(new_token)
        if bot_uname:
            await db.update_bot_username(cont_id, bot_uname)
        await msg.edit_text(f"✅ Telegram token updated for *{cont['name']}*\n{bot_uname or '(username not resolved)'}\nGateway restarted",
                            parse_mode='Markdown', reply_markup=main_keyboard())
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def cont_rename_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import re
    new_name = update.message.text.strip().replace(' ', '-')
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]+$', new_name):
        await update.message.reply_text(
            "❌ Invalid container name. Use only letters, digits, `-`, `_`, `.`\nNo spaces or special characters.",
            reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN
    cont_id = context.user_data.get('rename_cont_id')
    if not cont_id:
        await update.message.reply_text("❌ Context lost, please start again", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN

    cont = await db.get_container(cont_id)
    old_name = cont['name']
    try:
        ssh.execute(cont['ip'], cont['login'], f"docker rename '{old_name}' '{new_name}'")
        await db.rename_container(cont_id, new_name)
        await update.message.reply_text(
            f"✅ Container renamed: *{old_name}* → *{new_name}*",
            parse_mode='Markdown', reply_markup=main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def pair_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    cont_id = context.user_data.get('pair_cont_id')
    if not cont_id:
        await update.message.reply_text("❌ Context lost, please start again", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN

    cont = await db.get_container(cont_id)
    await update.message.reply_text(f"⏳ Confirming pairing in container *{cont['name']}*...", parse_mode='Markdown')
    try:
        out = ssh.approve_pairing(cont['ip'], cont['login'], cont['name'], cont['openclaw_profile'] or '', code)
        result = out if out else "Pairing confirmed"
        # Extract Telegram ID from openclaw output if possible
        import re
        tg_id_match = re.search(r'(\d{5,})', out or '')
        context.user_data['pair_tg_id'] = tg_id_match.group(1) if tg_id_match else ''
        await update.message.reply_text(
            f"✅ *{result}*\n\n"
            f"Enter *Telegram username* for this user (e.g. @username)\n"
            f"or send /skip to skip:",
            parse_mode='Markdown'
        )
        return PAIR_USERNAME
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN


async def pair_username_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cont_id = context.user_data.get('pair_cont_id')
    tg_id = context.user_data.get('pair_tg_id', '')

    if text != '/skip' and cont_id and tg_id:
        username = text if text.startswith('@') else f"@{text}"
        await db.add_paired_user(cont_id, tg_id, username)
        await update.message.reply_text(f"✅ Saved: `{tg_id}` → {username}", parse_mode='Markdown', reply_markup=main_keyboard())
    elif text != '/skip' and cont_id and not tg_id:
        # No ID extracted — save with empty ID (manual entry)
        username = text if text.startswith('@') else f"@{text}"
        await db.add_paired_user(cont_id, username, username)
        await update.message.reply_text(f"✅ Saved: {username}", parse_mode='Markdown', reply_markup=main_keyboard())
    else:
        await update.message.reply_text("⏭ Skipped", reply_markup=main_keyboard())

    context.user_data.clear()
    return MAIN


async def pair_edit_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    cont_id = context.user_data.get('pu_cont_id')
    tg_id = context.user_data.get('pu_telegram_id')
    if cont_id and tg_id:
        username = text if text.startswith('@') else f"@{text}"
        await db.update_paired_username(cont_id, tg_id, username)
        await update.message.reply_text(f"✅ Updated: `{tg_id}` → {username}", parse_mode='Markdown', reply_markup=main_keyboard())
    else:
        await update.message.reply_text("❌ Context lost", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def emp_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['emp_name'] = update.message.text
    conts = await db.get_containers()
    if not conts:
        await update.message.reply_text("No containers", reply_markup=main_keyboard())
        return MAIN
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{c['name']}", callback_data=f"emp_cont_{c['id']}")] for c in conts])
    await update.message.reply_text("Select container:", reply_markup=kb)
    return EMP_CONT

async def emp_key_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ssh_key = update.message.text.strip()
    name = context.user_data['emp_name']
    cont_id = context.user_data['emp_cont_id']
    cont = await db.get_container(cont_id)
    await update.message.reply_text("⏳ Adding SSH key...")
    try:
        ssh.add_employee_key(cont['ip'], cont['login'], cont['name'], ssh_key)
        await db.add_employee(name, cont_id, ssh_key)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Mac Instructions", callback_data=f"inst_emp_mac_{cont_id}"),
             InlineKeyboardButton("💻 Windows Instructions", callback_data=f"inst_emp_win_{cont_id}")]
        ])
        await update.message.reply_text(
            f"✅ Employee *{name}* added\nSend instructions to the employee:", parse_mode='Markdown', reply_markup=kb)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def admin_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['adm_name'] = update.message.text
    await update.message.reply_text("Enter *Telegram ID* of new administrator:", parse_mode='Markdown')
    return ADMIN_ID

async def admin_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data['adm_name']
    tid = update.message.text.strip()
    added_by = update.effective_user.id
    await db.add_admin(tid, name, added_by)
    await update.message.reply_text(f"✅ Administrator *{name}* added", parse_mode='Markdown', reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def inst_emp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    inst_type = parts[2]
    cont_id = int(parts[3])
    cont = await db.get_container(cont_id)
    if inst_type == "mac":
        text = instructions.get_mac_instruction(cont['ip'], cont['name'])
    else:
        text = instructions.get_windows_instruction(cont['ip'], cont['name'])
    await q.edit_message_text(text, parse_mode='Markdown',
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_employees")]]))
    return MAIN


async def _notify_admins(app, text):
    """Send a message to all admins."""
    admins = await db.get_admins()
    for admin in admins:
        try:
            await app.bot.send_message(int(admin['telegram_id']), text, parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin['name']}: {e}")


async def monitor_container_health(app):
    """Background task: monitor OpenClaw containers every 30 min.
    - Immediate alert if container is DOWN or gateway crashed.
    - Daily diagnostics at ~08:00 UTC — only real issues, no noise."""
    import re as _re
    from datetime import datetime, timezone

    HEALTH_INTERVAL = 30 * 60  # 30 minutes
    _last_daily = None
    _alerted = set()  # (server_name, container_name, issue) — avoid spam

    await asyncio.sleep(60)

    while True:
        try:
            servers = await db.get_servers()
            now = datetime.now(timezone.utc)
            do_daily = _last_daily is None or (now.hour >= 8 and (now - _last_daily).total_seconds() > 20 * 3600)
            urgent_alerts = []
            daily_lines = []

            for srv in servers:
                try:
                    conts = await db.get_containers(srv['id'])
                    openclaw_conts = [c for c in conts if c['type'] == 'openclaw']
                    if not openclaw_conts:
                        continue

                    raw = ssh.execute(
                        srv['ip'], srv['login'],
                        "docker ps -a --format '{{.Names}}|{{.Status}}' 2>&1",
                        timeout=15
                    )
                    status_map = {}
                    for line in raw.strip().split('\n'):
                        if '|' in line:
                            name, status = line.split('|', 1)
                            status_map[name.strip()] = status.strip()

                    if do_daily:
                        daily_lines.append(f"\n*{srv['name']}* (`{srv['ip']}`)")

                    for cont in openclaw_conts:
                        cname = cont['name']
                        status = status_map.get(cname, 'NOT FOUND')
                        is_running = status.startswith('Up')

                        if not is_running:
                            # --- Container DOWN ---
                            key = (srv['name'], cname, 'down')
                            if key not in _alerted:
                                _alerted.add(key)
                                try:
                                    logs = ssh.execute(srv['ip'], srv['login'],
                                        f"docker logs {cname} --tail 5 2>&1", timeout=10)
                                    snippet = logs.strip()[-300:] if logs.strip() else "no logs"
                                except Exception:
                                    snippet = "failed to read logs"
                                urgent_alerts.append(
                                    f"*{cname}* on {srv['name']}\n"
                                    f"Status: `{status}`\n"
                                    f"```\n{snippet}\n```")

                            if do_daily:
                                daily_lines.append(f"  ❌ *{cname}* — DOWN: {status}")
                        else:
                            _alerted.discard((srv['name'], cname, 'down'))

                            # --- Check if gateway is actually running inside ---
                            gw_running = True
                            try:
                                profile = cont['openclaw_profile'] if 'openclaw_profile' in cont.keys() else ''
                                profile_dir = f".openclaw-{profile}" if profile else ".openclaw"
                                # Only check gateway if container has a configured bot
                                cfg_out, cfg_code = ssh._execute_checked(srv['ip'], srv['login'],
                                    f"docker exec {cname} cat /root/{profile_dir}/openclaw.json 2>/dev/null",
                                    timeout=10)
                                if cfg_code == 0 and cfg_out.strip():
                                    import json as _json
                                    try:
                                        cfg = _json.loads(cfg_out.strip())
                                        has_bot = bool((cfg.get("channels", {})
                                                        .get("telegram", {})
                                                        .get("botToken") or "").strip())
                                    except Exception:
                                        has_bot = False

                                    if has_bot:
                                        gw_out, gw_code = ssh._execute_checked(srv['ip'], srv['login'],
                                            f"docker exec {cname} pgrep -f openclaw-gateway 2>/dev/null",
                                            timeout=10)
                                        if gw_code != 0 or not gw_out.strip():
                                            gw_running = False
                                else:
                                    has_bot = False
                            except Exception:
                                has_bot = False

                            if not gw_running and has_bot:
                                key = (srv['name'], cname, 'gateway')
                                if key not in _alerted:
                                    _alerted.add(key)
                                    urgent_alerts.append(
                                        f"*{cname}* on {srv['name']}\n"
                                        f"Container is Up but gateway process is not running")
                                if do_daily:
                                    daily_lines.append(f"  ⚠️ *{cname}* — {status} | gateway not running")
                            else:
                                _alerted.discard((srv['name'], cname, 'gateway'))
                                if do_daily:
                                    daily_lines.append(f"  ✅ *{cname}* — {status}")

                    # Ghost containers
                    if do_daily:
                        for name, status in status_map.items():
                            if _re.match(r'^[0-9a-f]{12}_', name):
                                daily_lines.append(f"  👻 Ghost: `{name}` — {status}")

                except Exception as e:
                    logger.warning(f"Health check failed for server {srv['name']}: {e}")
                    if do_daily:
                        daily_lines.append(f"\n*{srv['name']}* — ❌ unreachable: {e}")

            if urgent_alerts:
                text = "🚨 *Critical alert*\n\n" + "\n\n".join(urgent_alerts)
                await _notify_admins(app, text[:4000])

            if do_daily and daily_lines:
                _last_daily = now
                header = f"📊 *Daily status* — {now.strftime('%Y-%m-%d %H:%M')} UTC\n"
                text = header + "\n".join(daily_lines)
                await _notify_admins(app, text[:4000])

        except Exception as e:
            logger.error(f"Container health monitor error: {e}")

        await asyncio.sleep(HEALTH_INTERVAL)


async def check_openclaw_updates(app):
    """Background task: check OpenClaw versions on all servers every 6 hours."""
    import re as _re
    CHECK_INTERVAL = 6 * 60 * 60  # 6 hours

    await asyncio.sleep(30)  # wait for bot to fully start

    while True:
        try:
            servers = await db.get_servers()
            updates_found = []

            for srv in servers:
                try:
                    conts = await db.get_containers(srv['id'])
                    openclaw_conts = [c for c in conts if c['type'] == 'openclaw']
                    if not openclaw_conts:
                        continue

                    for cont in openclaw_conts:
                        try:
                            profile = cont['openclaw_profile'] if 'openclaw_profile' in cont.keys() else '' or ''
                            profile_flag = f"--profile {profile}" if profile else ""
                            # Get version + update info in one call
                            out = ssh.execute(
                                srv['ip'], srv['login'],
                                f"docker exec {cont['name']} openclaw {profile_flag} --version 2>&1",
                                timeout=15
                            )
                            current = out.strip().split('\n')[0].strip()
                            # Clean version string
                            current = _re.sub(r'^OpenClaw\s+', '', current).split('(')[0].strip()

                            # Check for update
                            log_out = ssh.execute(
                                srv['ip'], srv['login'],
                                f"docker logs {cont['name']} --tail 30 2>&1 | grep 'update available' | tail -1",
                                timeout=15
                            )
                            latest_match = _re.search(r'v([\d.]+(?:-\d+)?)\s*\(current\s+v([\d.]+(?:-\d+)?)\)', log_out)
                            if latest_match:
                                latest = latest_match.group(1)
                                cur_from_log = latest_match.group(2)
                                if latest != cur_from_log:
                                    updates_found.append({
                                        'server': srv['name'],
                                        'container': cont['name'],
                                        'current': cur_from_log,
                                        'latest': latest,
                                    })
                        except Exception as e:
                            logger.warning(f"OpenClaw check failed for {cont['name']}: {e}")
                except Exception as e:
                    logger.warning(f"OpenClaw check failed for server {srv['name']}: {e}")

            if updates_found:
                lines = ["🦞 *OpenClaw update available!*\n"]
                for u in updates_found:
                    lines.append(f"• *{u['container']}* ({u['server']}): `{u['current']}` → `{u['latest']}`")
                await _notify_admins(app, "\n".join(lines))

        except Exception as e:
            logger.error(f"OpenClaw update check error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def post_init(app):
    await db.create_tables()
    await db.seed_admins()
    # Start background tasks
    asyncio.create_task(monitor_container_health(app))
    # Register bot commands for menu button
    await app.bot.set_my_commands([
        BotCommand("start", "Main menu"),
        BotCommand("cancel", "Cancel current action"),
    ])


# ── GitHub handlers ──────────────────────────────────────────────────────────

async def github_repo_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().replace(' ', '-').lower()
    import re
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]+$', name):
        await update.message.reply_text("Invalid name. Use letters, digits, - _ only.")
        return GITHUB_REPO_NAME
    context.user_data['gh_repo_name'] = name
    await update.message.reply_text(f"Repo: {name}\n\nEnter description (or /skip):")
    return GITHUB_REPO_DESC

async def github_repo_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gh_repo_desc'] = update.message.text.strip()
    return await _github_ask_server(update, context)

async def _github_ask_server(update, context):
    servers = await db.get_servers()
    if not servers:
        await update.message.reply_text("No servers in DB.", reply_markup=main_keyboard())
        return MAIN
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(s['name'], callback_data=f"gh_srv_{s['id']}_{s['ip']}")] for s in servers])
    await update.message.reply_text("Select server to deploy to:", reply_markup=kb)
    return GITHUB_REPO_SERVER

async def github_repo_path(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gh_deploy_path'] = update.message.text.strip()
    repo_name = context.user_data.get("gh_repo_name", "project")
    default_service = repo_name + ".service"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Default ({default_service})", callback_data="gh_service_default")],
    ])
    await update.message.reply_text(f"Service name — enter custom, /skip, or use default:", reply_markup=kb)
    return GITHUB_REPO_SERVICE

async def github_repo_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gh_service'] = update.message.text.strip()
    return await _github_create(update, context)

async def _github_skip_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gh_repo_desc'] = ''
    return await _github_ask_server(update, context)

async def _github_skip_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gh_service'] = ''
    return await _github_create(update, context)

async def _github_create(update, context):
    name = context.user_data.get('gh_repo_name', '')
    desc = context.user_data.get('gh_repo_desc', '')
    host = context.user_data.get('gh_deploy_host', '')
    path = context.user_data.get('gh_deploy_path', f'/root/{name}')
    service = context.user_data.get('gh_service', '')

    msg = await update.message.reply_text(f"Creating repo {name}...")

    try:
        mode = context.user_data.get("gh_mode", "create")
        if mode == "create":
            result = gh.create_repo(name, desc)
            if 'errors' in result or result.get('message'):
                await msg.edit_text(f"GitHub error: {result.get('message', result)}")
                return MAIN
            full_name = result['full_name']
            await msg.edit_text(f"Repo created: {full_name}\nSetting up secrets...")
        else:
            username = gh._get_username()
            full_name = name if '/' in name else f"{username}/{name}"
            await msg.edit_text(f"Linking {full_name}\nSetting up secrets...")

        gh.setup_repo_secrets(full_name, host)

        # Create deploy.yml on server via SSH if path and service are set
        if path and host:
            try:
                import ssh_manager as ssh_m
                restart_cmd = f'systemctl restart {service}' if service else 'echo deploy done'
                workflow = (
                    'name: Deploy\n'
                    'on:\n'
                    '  push:\n'
                    '    branches: [master]\n'
                    'jobs:\n'
                    '  deploy:\n'
                    '    runs-on: ubuntu-latest\n'
                    '    steps:\n'
                    '      - uses: appleboy/ssh-action@v1.0.3\n'
                    '        with:\n'
                    '          host: ${{ secrets.DEPLOY_HOST }}\n'
                    '          username: root\n'
                    '          key: ${{ secrets.DEPLOY_KEY }}\n'
                    '          script: |\n'
                    f'            cd {path}\n'
                    '            git pull\n'
                    f'            {restart_cmd}\n'
                )
                script = (
                    f'mkdir -p {path}/.github/workflows && '
                    f'cat > {path}/.github/workflows/deploy.yml << \'WFEOF\'\n'
                    + workflow +
                    'WFEOF'
                )
                c = ssh_m._client(host, 'root')
                c.exec_command(script)
                c.close()
            except Exception as e:
                pass  # deploy.yml creation is best-effort

        # Auto git init + push on the server via SSH
        git_ok = False
        git_err = ''
        if path and host:
            try:
                import ssh_manager as ssh_m
                token = gh._token()
                remote_url = f'https://x-access-token:{token}@github.com/{full_name}.git'
                git_script = (
                    f'cd {path} && '
                    'git init && '
                    'git checkout -b main 2>/dev/null; '
                    f'git remote remove origin 2>/dev/null; '
                    f'git remote add origin {remote_url} && '
                    'git add -A && '
                    'git commit -m "Initial commit" && '
                    'git push -u origin main'
                )
                c = ssh_m._client(host, 'root')
                _, stdout, stderr = c.exec_command(git_script, timeout=60)
                exit_code = stdout.channel.recv_exit_status()
                if exit_code == 0:
                    git_ok = True
                    # Replace token URL with clean SSH URL
                    clean_script = (
                        f'cd {path} && '
                        'git remote remove origin && '
                        f'git remote add origin git@github.com:{full_name}.git'
                    )
                    c.exec_command(clean_script)
                else:
                    git_err = stderr.read().decode().strip()
                c.close()
            except Exception as e:
                git_err = str(e)

        reply = (
            f"Repo: https://github.com/{full_name}\n"
            f"Secrets: DEPLOY_HOST={host}, DEPLOY_KEY set\n"
        )
        if service:
            reply += f"deploy.yml: restart {service}\n"
        if git_ok:
            reply += f"\n✅ Git initialized and pushed to GitHub."
        elif git_err:
            reply += f"\n⚠️ Auto-push failed: {git_err}\nManually: cd {path} && git init && git remote add origin git@github.com:{full_name}.git && git add -A && git commit -m 'init' && git push -u origin main"
        else:
            reply += f"\nNext: cd {path} && git init && git remote add origin git@github.com:{full_name}.git && git add -A && git commit -m 'init' && git push -u origin main"

        await msg.edit_text(reply, reply_markup=main_keyboard())

    except Exception as e:
        await msg.edit_text(f"Error: {e}", reply_markup=main_keyboard())

    context.user_data.clear()
    return MAIN


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN: [
                CallbackQueryHandler(inst_emp_callback, pattern=r"^inst_emp_"),
                CallbackQueryHandler(menu_callback),
            ],
            SRV_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, srv_name)],
            SRV_IP:        [MessageHandler(filters.TEXT & ~filters.COMMAND, srv_ip)],
            SRV_LOGIN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, srv_login)],
            SRV_PASS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, srv_pass)],
            SRV_DEL:       [CallbackQueryHandler(menu_callback)],
            CONT_SERVER:   [CallbackQueryHandler(menu_callback)],
            CONT_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, cont_name_handler)],
            CONT_ANTHROPIC:[MessageHandler(filters.TEXT & ~filters.COMMAND, cont_anthropic)],
            CONT_OPENAI:   [MessageHandler(filters.TEXT & ~filters.COMMAND, cont_openai)],
            CONT_TG:       [MessageHandler(filters.TEXT & ~filters.COMMAND, cont_tg)],
            CONT_DEL_SRV:  [CallbackQueryHandler(menu_callback)],
            CONT_DEL:      [CallbackQueryHandler(menu_callback)],
            EMP_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, emp_name_handler)],
            EMP_CONT:      [CallbackQueryHandler(menu_callback)],
            EMP_KEY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, emp_key_handler)],
            EMP_DEL:       [CallbackQueryHandler(menu_callback)],
            ADMIN_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_name_handler)],
            ADMIN_ID:      [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_id_handler)],
            ADMIN_DEL:     [CallbackQueryHandler(menu_callback)],
            CONT_RENAME_SEL: [CallbackQueryHandler(menu_callback)],
            CONT_RENAME_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cont_rename_name_handler)],
            PAIR_CONT:     [CallbackQueryHandler(menu_callback)],
            PAIR_CODE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, pair_code_handler)],
            PAIR_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pair_username_handler),
                CommandHandler("skip", pair_username_handler),
            ],
            PAIR_EDIT_CONT: [CallbackQueryHandler(menu_callback)],
            PAIR_EDIT_USER: [CallbackQueryHandler(menu_callback)],
            PAIR_EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, pair_edit_name_handler)],
            KEYS_CONT:      [CallbackQueryHandler(menu_callback)],
            KEYS_ANTHROPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, keys_anthropic_handler)],
            KEYS_OPENAI:    [MessageHandler(filters.TEXT & ~filters.COMMAND, keys_openai_handler)],
            KEYS_TG_TOKEN:  [MessageHandler(filters.TEXT & ~filters.COMMAND, keys_tg_token_handler)],
            GITHUB_REPO_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, github_repo_name)],
            GITHUB_REPO_DESC:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, github_repo_desc),
                CommandHandler('skip', _github_skip_desc),
            ],
            GITHUB_REPO_SERVER:  [CallbackQueryHandler(menu_callback)],
            GITHUB_REPO_PATH:    [
                CallbackQueryHandler(menu_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, github_repo_path),
            ],
            GITHUB_REPO_SERVICE: [
                CallbackQueryHandler(menu_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, github_repo_service),
                CommandHandler('skip', _github_skip_service),
            ],
            GITHUB_DEL_REPO:     [CallbackQueryHandler(menu_callback)],
            GITHUB_DEL_CONFIRM:  [CallbackQueryHandler(menu_callback)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.run_polling()


if __name__ == '__main__':
    main()
