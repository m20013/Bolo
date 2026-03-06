# -*- coding: utf-8 -*-
import logging
import asyncio
import nest_asyncio
import aiosqlite
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

nest_asyncio.apply()

# ────────────────────────────────────────────────
#                         الإعدادات
# ────────────────────────────────────────────────
BOT_TOKEN  = "2017218286:AAFst7OplP67uPA8b17abteISoe-eV04yeQ"
ADMIN_ID   = 1148510962 
ADMIN_USER = "@user98eh70s2" 
INSTA_URL  = "https://instagram.com/user98eh70s2"
SERPER_KEY = "6066e39e9cf4c71733aa04a1d0c47970f099f025"
DB_FILE    = "bot_final_v17.db"

logging.basicConfig(level=logging.INFO)

# ────────────────────────────────────────────────
#                    قاعدة البيانات
# ────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            username TEXT,
            full_name TEXT,
            status TEXT DEFAULT 'new',
            is_banned INTEGER DEFAULT 0
        )''')
        await db.execute('CREATE TABLE IF NOT EXISTS hidden_users (username TEXT PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)')
        await db.execute('INSERT OR IGNORE INTO settings VALUES ("maintenance", 0)')
        await db.commit()

# ────────────────────────────────────────────────
#                دالة البحث
# ────────────────────────────────────────────────
async def search_insta_links(username: str):
    user_clean = username.lower().strip()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT 1 FROM hidden_users WHERE username = ?", (user_clean,)) as c:
            if await c.fetchone():
                return "❌ عذراً، هذا الحساب محمي بطلب من صاحبه."

    url = "https://google.serper.dev/search"
    queries = [f'site:instagram.com "{username}"', f'"{username}" instagram comment']
    headers = {"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"}
    all_links = []
    
    async with aiohttp.ClientSession() as session:
        for q in queries:
            try:
                payload = {"q": q, "num": 10}
                async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("organic", []):
                            link = item.get('link')
                            if link and "instagram.com" in link:
                                if link not in all_links: all_links.append(link)
            except: continue
            
        if all_links:
            res = f"✅ تم العثور على نتائج لـ: {username}\n\n"
            for i, link in enumerate(all_links, 1):
                res += f"{i} - {link}\n"
            return res
        return f"❌ لم يتم العثور على تعليقات مؤرشفة لليوزر {username}"

# ────────────────────────────────────────────────
#                   لوحة التحكم
# ────────────────────────────────────────────────
async def get_admin_menu():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT value FROM settings WHERE key='maintenance'") as c:
            m_status = (await c.fetchone())[0]
    m_text = "🟢 الصيانة: مطفأ" if m_status == 0 else "🔴 الصيانة: يعمل"
    kb = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"), InlineKeyboardButton("📢 إذاعة", callback_data="adm_bc")],
        [InlineKeyboardButton("🚫 حظر/إلغاء", callback_data="adm_ban_req"), InlineKeyboardButton("👁️ إخفاء يوزر", callback_data="adm_hide_req")],
        [InlineKeyboardButton(m_text, callback_data="adm_toggle_m"), InlineKeyboardButton("🔙 عودة", callback_data="verify")]
    ]
    return InlineKeyboardMarkup(kb)

# ────────────────────────────────────────────────
#                   المعالجات
# ────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)", 
                       (user.id, user.username, user.full_name))
        await db.commit()
    
    if user.id != ADMIN_ID:
        await context.bot.send_message(ADMIN_ID, f"👤 مستخدم جديد:\nالاسم: {user.full_name}\nاليوزر: @{user.username}\nالآيدي: {user.id}")

    txt = "👋 أهلاً بك في بوت كاشف التعليقات\n\nأتعهد أمام الله باستخدام البوت في الخير وعدم الإضرار بالآخرين."
    kb = [[InlineKeyboardButton("✅ أوافق وأتعهد", callback_data="agree")]]
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data
    await q.answer()

    # --- القسم العام ---
    if data == "agree":
        kb = [[InlineKeyboardButton("📱 متابعة الحساب", url=INSTA_URL)], 
              [InlineKeyboardButton("✅ تم المتابعة", callback_data="verify")]]
        await q.edit_message_text("🛡️ تابع حساب المطور لتفعيل البوت:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "verify":
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("UPDATE users SET status = 'active' WHERE user_id = ?", (uid,))
            await db.commit()
        kb = [[InlineKeyboardButton("🔍 ابدأ البحث عن يوزر", callback_data="start_search")]]
        if uid == ADMIN_ID:
            kb.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_main")])
        await q.edit_message_text("🎊 تم التفعيل بنجاح!", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "start_search":
        kb = [[InlineKeyboardButton("🛡️ إخفاء حسابي", callback_data="user_request_hide")]]
        await q.edit_message_text("📝 أرسل الآن يوزر الإنستقرام (بدون @):", reply_markup=InlineKeyboardMarkup(kb))
        context.user_data['state'] = 'WAIT_SEARCH'

    # --- قسم الأدمن ---
    elif uid == ADMIN_ID:
        if data == "admin_main":
            await q.edit_message_text("🛠 لوحة تحكم الإدارة:", reply_markup=await get_admin_menu())
        
        elif data == "adm_stats":
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT COUNT(*) FROM users") as c:
                    count = (await c.fetchone())[0]
            await q.edit_message_text(f"📊 إجمالي المستخدمين: {count}", reply_markup=await get_admin_menu())
        
        elif data == "adm_bc":
            await q.edit_message_text("📢 أرسل نص الإذاعة الآن:")
            context.user_data['state'] = 'WAIT_BC'
            
        elif data == "adm_ban_req":
            await q.edit_message_text("🚫 أرسل آيدي (ID) المستخدم المراد حظره/إلغاء حظره:")
            context.user_data['state'] = 'WAIT_BAN'

        elif data == "adm_hide_req":
            await q.edit_message_text("👁️ أرسل اليوزر المراد إخفاؤه من البحث:")
            context.user_data['state'] = 'WAIT_HIDE'
            
        elif data == "adm_toggle_m":
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT value FROM settings WHERE key='maintenance'") as c:
                    new_v = 1 if (await c.fetchone())[0] == 0 else 0
                    await db.execute("UPDATE settings SET value=? WHERE key='maintenance'", (new_v,))
                    await db.commit()
            await q.edit_message_text("🛠 تم تغيير وضع الصيانة.", reply_markup=await get_admin_menu())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = context.user_data.get('state')
    text = update.message.text.strip()

    # --- منطق الأدمن ---
    if uid == ADMIN_ID:
        if state == 'WAIT_BC':
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT user_id FROM users") as cur:
                    rows = await cur.fetchall()
                    for r in rows:
                        try: await context.bot.send_message(r[0], f"📢 إعلان من الإدارة:\n\n{text}")
                        except: pass
            await update.message.reply_text("✅ تم إرسال الإذاعة للجميع.", reply_markup=await get_admin_menu())
            context.user_data['state'] = None
            return

        elif state == 'WAIT_BAN':
            try:
                tid = int(text)
                async with aiosqlite.connect(DB_FILE) as db:
                    async with db.execute("SELECT is_banned FROM users WHERE user_id=?", (tid,)) as c:
                        res = await c.fetchone()
                        if res:
                            new_b = 0 if res[0] == 1 else 1
                            await db.execute("UPDATE users SET is_banned=? WHERE user_id=?", (new_b, tid))
                            await db.commit()
                            await update.message.reply_text(f"✅ تم تحديث حالة الحظر للآيدي {tid}", reply_markup=await get_admin_menu())
                        else: await update.message.reply_text("❌ الآيدي غير موجود بالقاعدة.")
            except: await update.message.reply_text("❌ يرجى إرسال آيدي رقمي صحيح.")
            context.user_data['state'] = None
            return

        elif state == 'WAIT_HIDE':
            u_hide = text.replace("@", "").lower()
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("INSERT OR IGNORE INTO hidden_users VALUES (?)", (u_hide,))
                await db.commit()
            await update.message.reply_text(f"✅ اليوزر {u_hide} أصبح مخفياً الآن.", reply_markup=await get_admin_menu())
            context.user_data['state'] = None
            return

    # --- فحص الصيانة والحظر ---
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT value FROM settings WHERE key='maintenance'") as c:
            if uid != ADMIN_ID and (await c.fetchone())[0] == 1:
                await update.message.reply_text("⚠️ البوت في صيانة حالياً.")
                return
        async with db.execute("SELECT is_banned, status FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                await update.message.reply_text("❌ أنت محظور.")
                return

    # --- منطق البحث ---
    if state == 'WAIT_SEARCH' or (row and row[1] == 'active'):
        target = text.replace("@", "")
        msg = await update.message.reply_text("🔎 جاري البحث عن تعليقات...")
        res = await search_insta_links(target)
        await msg.edit_text(res, disable_web_page_preview=True)
        context.user_data['state'] = None

async def main():
    await init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("--- البوت V17 يعمل بكامل طاقته ---")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
