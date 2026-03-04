import logging
import asyncio
import aiohttp
import aiosqlite
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)

# ==========================================
# ⚙️ الإعدادات الأساسية
# ==========================================
BOT_TOKEN = "2017218286:AAGh_0CO3bOyOJ-UkPDGJvITYwguA25icw4"
ADMIN_ID = 1148510962
ADMIN_USER = "@M1000j"
INSTA_FOLLOW_LINK = "https://instagram.com/user98eh70s2"
DB_FILE = "bot_database_v7.db"

logging.basicConfig(level=logging.INFO)

# ==========================================
# 🗄️ إدارة قاعدة البيانات
# ==========================================
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, 
                  attempts INTEGER DEFAULT 0, last_use TEXT, is_vip INTEGER DEFAULT 0, state TEXT)''')
        await db.execute('CREATE TABLE IF NOT EXISTS hidden (target TEXT PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        await db.execute('INSERT OR IGNORE INTO settings VALUES ("api_key", "fc2b9d4e-1618-4483-b9f7-309011e57713")')
        await db.execute('INSERT OR IGNORE INTO settings VALUES ("bot_status", "on")')
        await db.commit()

async def db_exec(query, params=(), fetch=None):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(query, params)
        if fetch == "one": return await cursor.fetchone()
        if fetch == "all": return await cursor.fetchall()
        await db.commit()
        return None

# ==========================================
# 🔍 محرك البحث (HasData API)
# ==========================================
async def get_comments(target):
    is_hidden = await db_exec("SELECT 1 FROM hidden WHERE target = ?", (target.lower(),), fetch="one")
    if is_hidden: return "HIDDEN"

    api_key_data = await db_exec("SELECT value FROM settings WHERE key = 'api_key'", fetch="one")
    api_key = api_key_data[0] if api_key_data else ""

    url = "https://api.hasdata.com/scrape/google/serp"
    query = f'site:instagram.com "{target}"'
    params = {'q': query, 'num': 100, 'deviceType': 'mobile'}
    headers = {'x-api-key': api_key}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params, timeout=35) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw = data.get('organicResults', []) + data.get('videoResults', [])
                    results = []
                    for item in raw:
                        link = item.get('link', '').split('?')[0].rstrip('/')
                        if "/p/" in link or "/reel/" in link:
                            snippet = item.get('snippet', '').replace("...", "").strip()
                            results.append({"text": snippet, "link": link})
                    return results
                elif resp.status == 401: return "KEY_EXPIRED"
                return []
        except: return []

# ==========================================
# 🤖 لوحة التحكم ومعالجة التدفق
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = await db_exec("SELECT value FROM settings WHERE key = 'bot_status'", fetch="one")
    if status and status[0] == "off" and user.id != ADMIN_ID:
        return await update.message.reply_text("🛠️ عذراً، البوت واقف حالياً قيد التطوير.. ارجع بعد شوي.")

    is_new = await db_exec("SELECT 1 FROM users WHERE user_id = ?", (user.id,), fetch="one")
    if not is_new:
        await db_exec("INSERT INTO users (user_id, username, name, state) VALUES (?, ?, ?, ?)", 
                      (user.id, user.username, user.full_name, "START"))
        await context.bot.send_message(ADMIN_ID, f"🔔 <b>دخول مستخدم جديد:</b>\nالاسم: {user.full_name}\nاليوزر: @{user.username}", parse_mode="HTML")

    msg = "⚠️ <b>تنبيه هام:</b>\nهذا البوت مخصص للاستخدام التعليمي والبحث العلني فقط."
    kb = [[InlineKeyboardButton("✅ موافق وأتعهد", callback_data="flow_agree")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "adm_toggle":
        if user_id != ADMIN_ID: return
        current = await db_exec("SELECT value FROM settings WHERE key = 'bot_status'", fetch="one")
        new_status = "off" if current[0] == "on" else "on"
        await db_exec("UPDATE settings SET value = ? WHERE key = 'bot_status'", (new_status,))
        await query.edit_message_text(f"✅ تم تغيير حالة البوت إلى: **{new_status.upper()}**")
        await admin_panel(update, context)

    elif data == "flow_hide_me":
        # الرسالة التي طلبتها
        await query.message.reply_text(f"🛡️ لطلب خدمة إخفاء حسابك من نتائج البحث، يرجى التواصل مع الإدارة: {ADMIN_USER}")

    elif data == "flow_agree":
        msg = "🚀 تابع المطور للمتابعة:"
        kb = [[InlineKeyboardButton("📸 تابعني هنا", url=INSTA_FOLLOW_LINK)],
              [InlineKeyboardButton("✅ تم المتابعة", callback_data="flow_main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    elif data == "flow_main_menu":
        msg = "🌟 **القائمة الرئيسية:**\nأهلاً بك، اختر الخدمة المطلوبة:"
        kb = [
            [InlineKeyboardButton("🔍 ابدأ البحث عن يوزر", callback_data="flow_start_search")],
            [InlineKeyboardButton("🛡️ إخفاء حسابي", callback_data="flow_hide_me")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    elif data == "flow_start_search":
        await query.edit_message_text("📝 أرسل يوزر الشخص المطلوب بدون @:")
        await db_exec("UPDATE users SET state = 'WAITING_USER' WHERE user_id = ?", (user_id,))

    elif data == "adm_stats":
        total = await db_exec("SELECT COUNT(*) FROM users", fetch="one")
        await query.message.reply_text(f"📊 إجمالي المستخدمين: {total[0]}")

    elif data == "adm_setkey":
        context.user_data['adm_action'] = "setkey"
        await query.message.reply_text("📥 أرسل مفتاح API الجديد أو 'إلغاء':")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    status = await db_exec("SELECT value FROM settings WHERE key = 'bot_status'", fetch="one")
    if status and status[0] == "off" and user_id != ADMIN_ID:
        return await update.message.reply_text("🛠️ البوت واقف حالياً للتطوير..")

    if user_id == ADMIN_ID and context.user_data.get('adm_action') == "setkey":
        if text == "إلغاء":
            context.user_data.pop('adm_action')
            return await update.message.reply_text("❌ تم الإلغاء.")
        await db_exec("UPDATE settings SET value = ? WHERE key = 'api_key'", (text,))
        context.user_data.pop('adm_action')
        await update.message.reply_text("✅ تم تحديث المفتاح!")
        return

    u_state = await db_exec("SELECT state FROM users WHERE user_id = ?", (user_id,), fetch="one")
    if u_state and u_state[0] == 'WAITING_USER':
        await context.bot.send_message(ADMIN_ID, f"🔍 <b>بحث جديد:</b>\nمن: {update.effective_user.full_name}\nعن: <code>{text}</code>", parse_mode="HTML")
        
        loading = await update.message.reply_text("⏳ جاري البحث...")
        results = await get_comments(text.replace("@",""))
        
        if results == "HIDDEN":
             await loading.edit_text("🛡️ عذراً، هذا الحساب محمي بخدمة VIP ولا يمكن البحث عنه.")
        elif results and isinstance(results, list):
            await loading.delete()
            for res in results[:5]:
                await update.message.reply_text(f"💬 {res['text']}\n🔗 {res['link']}", disable_web_page_preview=True)
        else:
            await loading.edit_text("❌ لا توجد نتائج.")

# ==========================================
# 🛠️ لوحة الأدمن
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    status = await db_exec("SELECT value FROM settings WHERE key = 'bot_status'", fetch="one")
    toggle_btn = "🔴 إيقاف البوت" if status[0] == "on" else "🟢 تشغيل البوت"
    kb = [
        [InlineKeyboardButton(toggle_btn, callback_data="adm_toggle")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="adm_stats"), InlineKeyboardButton("🔑 تحديث API", callback_data="adm_setkey")]
    ]
    await update.message.reply_text("📊 لوحة التحكم:", reply_markup=InlineKeyboardMarkup(kb))

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.run_polling()
  
