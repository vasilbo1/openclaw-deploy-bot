import logging
import os
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)
import database as db
import ssh_manager as ssh
import instructions
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
 CONT_RENAME_SEL, CONT_RENAME_NAME
) = range(27)


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 Servers", callback_data="menu_servers"),
         InlineKeyboardButton("📦 Containers", callback_data="menu_containers")],
        [InlineKeyboardButton("👥 Employees", callback_data="menu_employees"),
         InlineKeyboardButton("📋 Instructions", callback_data="menu_instructions")],
        [InlineKeyboardButton("⚙️ Administrators", callback_data="menu_admins")],
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
                try:
                    users = ssh.get_paired_users(c['ip'], c['login'], c['name'], c['openclaw_profile'] or '')
                    label += f" | 👥 {len(users)}"
                except Exception:
                    label += " | 👥 ?"
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
            try:
                user_ids = ssh.get_paired_users(c['ip'], c['login'], c['name'], c['openclaw_profile'] or '')
                if not user_ids:
                    lines.append("No connected users")
                else:
                    for uid in user_ids:
                        try:
                            chat = await context.bot.get_chat(int(uid))
                            name = chat.first_name or ""
                            if chat.last_name:
                                name += f" {chat.last_name}"
                            username = f" (@{chat.username})" if chat.username else ""
                            lines.append(f"• {name}{username} — `{uid}`")
                        except Exception:
                            lines.append(f"• ID `{uid}`")
            except Exception:
                lines.append("Failed to fetch list")
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
    context.user_data['cont_name'] = update.message.text
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

async def cont_rename_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    cont_id = context.user_data.get('rename_cont_id')
    if not cont_id:
        await update.message.reply_text("❌ Context lost, please start again", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN

    cont = await db.get_container(cont_id)
    old_name = cont['name']
    try:
        ssh.execute(cont['ip'], cont['login'], f"docker rename {old_name} {new_name}")
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
        await update.message.reply_text(f"✅ *{result}*", parse_mode='Markdown', reply_markup=main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=main_keyboard())

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


async def post_init(app):
    await db.create_tables()
    await db.seed_admins()


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
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.run_polling()


if __name__ == '__main__':
    main()
