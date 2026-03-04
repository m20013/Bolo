import logging
import asyncio
import aiohttp
import aiosqlite
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
DB_FILE = "bot_final_v12.db"

logging.basicConfig(level=logging.INFO)

# ==========================================
# 🗄️ إدارة قاعدة البيانات
# ==========================================
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, 
                  attempts INTEGER DEFAULT 0, last_use TEXT, is_vip INTEGER DEFAULT 0, 
                  state TEXT, referred_by INTEGER)''')
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
# 🔍 محرك البحث (مع فحص انتهاء المفتاح)
# ==========================================
async def get_insta_data(target, context: ContextTypes.DEFAULT_TYPE):
    api_key_data = await db_exec("SELECT value FROM settings WHERE key = 'api_key'", fetch="one")
    api_key = api_key_data[0] if api_key_data else ""

    url = "https://api.hasdata.com/scrape/google/serp"
    query = f'site:instagram.com "{target}"'
    params = {'q': query, 'num': 100, 'deviceType': 'mobile'}
    headers = {'x-api-key': api_key}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params, timeout=35) as resp:
                if resp.status in [401, 402]: 
                    await context.bot.send_message(ADMIN_ID, "🚨 <b>تنبيه عاجل:</b>\nرصيد HasData API انتهى! تم تحويل البوت لوضع الصيانة.")
                    await db_exec("UPDATE settings SET value = 'off' WHERE key = 'bot_status'")
                    return "API_EXPIRED"
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('organicResults', [])
                return []
        except: return []

# ==========================================
# 🤖 معالجة الأوامر والتدفق
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = await db_exec("SELECT value FROM settings WHERE key = 'bot_status'", fetch="one")
    if status and status[0] == "off" and user.id != ADMIN_ID:
        return await update.message.reply_text("🛠️ <b>البوت تحت الصيانة حالياً.</b>")

    is_registered = await db_exec("SELECT 1 FROM users WHERE user_id = ?", (user.id,), fetch="one")
    if not is_registered:
        await db_exec("INSERT INTO users (user_id, username, name, state) VALUES (?, ?, ?, ?)", 
                      (user.id, user.username, user.full_name, "START"))

    kb = [[InlineKeyboardButton("✅ موافق وأتعهد", callback_data="flow_agree")]]
    await update.message.reply_text("👋 أهلاً بك في بوت البحث العلني.", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "flow_agree":
        kb = [[InlineKeyboardButton("📱 متابعة المطور", url=INSTA_FOLLOW_LINK)],
              [InlineKeyboardButton("✅ تم المتابعة", callback_data="flow_main")]]
        await query.edit_message_text("🚀 يرجى متابعة المطور للاستمرار:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "flow_main":
        kb = [
            [InlineKeyboardButton("🔍 ابدأ البحث", callback_data="flow_search")],
            [InlineKeyboardButton("➕ زد محاولاتي", callback_data="flow_invite")],
            [InlineKeyboardButton("🛡️ إخفاء يوزري", callback_data="flow_hide_me")]
        ]
        await query.edit_message_text("🌟 <b>القائمة الرئيسية:</b>\nلديك 3 محاولات يومية مجانية.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    elif data == "flow_hide_me":
        # إصلاح الخلل: إرسال رسالة التواصل مع الأدمن
        await query.message.reply_text(f"🛡️ لطلب خدمة إخفاء حسابك من نتائج البحث، يرجى التواصل مع الإدارة:\n{ADMIN_USER}")

    elif data == "flow_invite":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        await query.message.reply_text(f"🎁 <b>ادعو صديقك واحصل على محاولتين:</b>\n\n<code>{ref_link}</code>", parse_mode="HTML")

    elif data == "flow_search":
        await query.edit_message_text("📝 أرسل يوزر الحساب المطلوب (بدون @):")
        await db_exec("UPDATE users SET state = 'WAITING_USER' WHERE user_id = ?", (user_id,))

# (بقية الكود الخاص بالـ Admin والـ Messages يظل كما هو)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    # أضف بقية الـ handlers هنا...
    app.run_polling()
