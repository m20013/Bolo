# -*- coding: utf-8 -*-
import logging
import asyncio
import nest_asyncio
import aiosqlite
import aiohttp
from datetime import datetime, timedelta
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
BOT_TOKEN           = "2017218286:AAFst7OplP67uPA8b17abteISoe-eV04yeQ"
ADMIN_ID            = 1148510962
ADMIN_USER          = "@M1000j"
CONTACT_USER        = "@M1000j"          # حساب التواصل للاشتراك
INSTA_URL           = "https://instagram.com/user98eh70s2"
SERPER_KEY          = "401885cb1e18e89a9b755f4cd0bb225d5032e5fe"
DB_FILE             = "bot_final_v17.db"

FREE_DAILY_LIMIT    = 2
SPAM_SECONDS        = 3
MILESTONE_USERS     = [10, 50, 100, 500, 1000]

# ── باقات الاشتراك ──
PLANS = [
    {
        "name":    "⚡ الباقة الأساسية",
        "trials":  30,
        "btc":     "0.00002",
        "sar":     "5",
        "days":    30,
    },
    {
        "name":    "🚀 الباقة المتقدمة",
        "trials":  100,
        "btc":     "0.00006",
        "sar":     "15.99",
        "days":    30,
    },
]

logging.basicConfig(level=logging.INFO)

# ════════════════════════════════════════════════
#                    قاعدة البيانات
# ════════════════════════════════════════════════
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id           INTEGER PRIMARY KEY,
            username          TEXT,
            full_name         TEXT,
            status            TEXT    DEFAULT 'new',
            is_banned         INTEGER DEFAULT 0,
            is_premium        INTEGER DEFAULT 0,
            premium_until     TEXT    DEFAULT NULL,
            searches_today    INTEGER DEFAULT 0,
            last_search_date  TEXT    DEFAULT NULL,
            total_searches    INTEGER DEFAULT 0,
            joined_at         TEXT    DEFAULT NULL,
            last_seen         TEXT    DEFAULT NULL,
            last_msg_time     REAL    DEFAULT 0,
            daily_limit       INTEGER DEFAULT 2
        )''')
        # جدول سجل الرسائل الكامل
        await db.execute('''CREATE TABLE IF NOT EXISTS messages_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            username   TEXT,
            full_name  TEXT,
            message    TEXT,
            msg_type   TEXT DEFAULT 'text',
            logged_at  TEXT
        )''')
        # جدول سجل عمليات البحث
        await db.execute('''CREATE TABLE IF NOT EXISTS search_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            username   TEXT,
            target     TEXT,
            searched_at TEXT
        )''')
        await db.execute('CREATE TABLE IF NOT EXISTS hidden_users (username TEXT PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        await db.execute('INSERT OR IGNORE INTO settings VALUES ("maintenance", "0")')
        await db.execute('INSERT OR IGNORE INTO settings VALUES ("serper_key", ?)', (SERPER_KEY,))
        await db.execute('INSERT OR IGNORE INTO settings VALUES ("forced_sub", "0")')
        await db.execute('INSERT OR IGNORE INTO settings VALUES ("forced_sub_channel", "")')
        await db.commit()

        # ── ترقية الأعمدة الجديدة إن لم تكن موجودة (للقواعد القديمة) ──
        new_columns = [
            ("is_premium",       "INTEGER DEFAULT 0"),
            ("premium_until",    "TEXT DEFAULT NULL"),
            ("searches_today",   "INTEGER DEFAULT 0"),
            ("last_search_date", "TEXT DEFAULT NULL"),
            ("total_searches",   "INTEGER DEFAULT 0"),
            ("joined_at",        "TEXT DEFAULT NULL"),
            ("last_seen",        "TEXT DEFAULT NULL"),
            ("last_msg_time",    "REAL DEFAULT 0"),
            ("daily_limit",      "INTEGER DEFAULT 2"),
        ]
        for col, col_def in new_columns:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def}")
                await db.commit()
                logging.info(f"✅ تمت إضافة العمود: {col}")
            except:
                pass  # العمود موجود مسبقاً

# ════════════════════════════════════════════════
#              دالة جلب وتحديث مفتاح API
# ════════════════════════════════════════════════
async def get_forced_sub() -> tuple[str, str]:
    """يرجع (حالة الاشتراك الإجباري، معرف القناة)"""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT value FROM settings WHERE key='forced_sub'") as c:
            status = (await c.fetchone())[0]
        async with db.execute("SELECT value FROM settings WHERE key='forced_sub_channel'") as c:
            channel = (await c.fetchone())[0]
    return status, channel

async def check_forced_sub(bot, uid: int) -> bool:
    """True = مشترك أو الاشتراك الإجباري مطفأ، False = غير مشترك"""
    status, channel = await get_forced_sub()
    if status == "0" or not channel:
        return True
    try:
        member = await bot.get_chat_member(channel, uid)
        return member.status not in ["left", "kicked"]
    except:
        return True  # لو فشل الفحص نسمح بالمرور


async def get_serper_key() -> str:
    """جلب مفتاح Serper من قاعدة البيانات"""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT value FROM settings WHERE key='serper_key'") as c:
            row = await c.fetchone()
    return row[0] if row else SERPER_KEY

async def set_serper_key(new_key: str):
    """تحديث مفتاح Serper في قاعدة البيانات"""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='serper_key'", (new_key,))
        await db.commit()

# ════════════════════════════════════════════════
#              دوال مساعدة عامة
# ════════════════════════════════════════════════
async def log_message(user, text: str, msg_type: str = "text"):
    """تسجيل كل رسالة في قاعدة البيانات"""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO messages_log (user_id, username, full_name, message, msg_type, logged_at) VALUES (?,?,?,?,?,?)",
            (user.id, user.username or "", user.full_name or "", text, msg_type, now)
        )
        await db.execute("UPDATE users SET last_seen=? WHERE user_id=?", (now, user.id))
        await db.commit()

async def log_search(user, target: str):
    """تسجيل عملية بحث"""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO search_log (user_id, username, target, searched_at) VALUES (?,?,?,?)",
            (user.id, user.username or "", target, now)
        )
        await db.execute(
            "UPDATE users SET total_searches = total_searches + 1 WHERE user_id=?", (user.id,)
        )
        await db.commit()

async def check_spam(uid: int) -> bool:
    """True = مسموح، False = سبام"""
    import time
    now = time.time()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT last_msg_time FROM users WHERE user_id=?", (uid,)) as c:
            row = await c.fetchone()
        if row and (now - row[0]) < SPAM_SECONDS:
            return False
        await db.execute("UPDATE users SET last_msg_time=? WHERE user_id=?", (now, uid))
        await db.commit()
    return True

async def check_premium_expired(uid):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT is_premium, premium_until FROM users WHERE user_id=?", (uid,)
        ) as c:
            row = await c.fetchone()
        if row and row[0] == 1 and row[1]:
            if datetime.now() > datetime.fromisoformat(row[1]):
                await db.execute(
                    "UPDATE users SET is_premium=0, premium_until=NULL WHERE user_id=?", (uid,)
                )
                await db.commit()
                return True
    return False

async def can_search(uid) -> tuple[bool, str]:
    await check_premium_expired(uid)
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT searches_today, last_search_date, is_premium, daily_limit FROM users WHERE user_id=?", (uid,)
        ) as c:
            row = await c.fetchone()
    if not row:
        return False, "❌ حدث خطأ، أعد تشغيل البوت بـ /start"
    searches_today, last_date, is_premium, daily_limit = row
    if last_date != today:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "UPDATE users SET searches_today=0, last_search_date=? WHERE user_id=?", (today, uid)
            )
            await db.commit()
        searches_today = 0
    limit = daily_limit if is_premium else FREE_DAILY_LIMIT
    if searches_today >= limit:
        if is_premium:
            return False, f"⚠️ وصلت للحد اليومي ({limit} محاولة).\nيتجدد منتصف الليل 🕛"
        return False, (
            f"⚠️ انتهت محاولاتك اليومية ({FREE_DAILY_LIMIT} محاولات).\n\n"
            f"💎 اشترك للحصول على محاولات أكثر!\n"
            f"تواصل مع: {CONTACT_USER}"
        )
    return True, ""

async def increment_search(uid):
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "UPDATE users SET searches_today=searches_today+1, last_search_date=? WHERE user_id=?",
            (today, uid)
        )
        await db.commit()

# ════════════════════════════════════════════════
#                دالة البحث
# ════════════════════════════════════════════════
async def search_insta_links(username: str):
    user_clean = username.lower().strip()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT 1 FROM hidden_users WHERE username=?", (user_clean,)) as c:
            if await c.fetchone():
                return "❌ عذراً، هذا الحساب محمي بطلب من صاحبه."
    url = "https://google.serper.dev/search"
    queries = [f'site:instagram.com "{username}"', f'"{username}" instagram comment']
    current_key = await get_serper_key()
    headers = {"X-API-KEY": current_key, "Content-Type": "application/json"}
    all_links = []
    async with aiohttp.ClientSession() as session:
        for q in queries:
            try:
                async with session.post(url, json={"q": q, "num": 10}, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        for item in (await resp.json()).get("organic", []):
                            link = item.get('link')
                            if link and "instagram.com" in link and link not in all_links:
                                all_links.append(link)
                    else:
                        logging.warning(f"Serper API رد بكود: {resp.status} | الرد: {await resp.text()}")
            except Exception as e:
                logging.error(f"خطأ في البحث: {e}")
                continue
    if all_links:
        res = f"✅ تم العثور على نتائج لـ: {username}\n\n"
        for i, link in enumerate(all_links, 1):
            res += f"{i} - {link}\n"
        return res
    return f"❌ لم يتم العثور على تعليقات مؤرشفة لليوزر {username}"

# ════════════════════════════════════════════════
#                   لوحة التحكم
# ════════════════════════════════════════════════
async def get_admin_menu():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT value FROM settings WHERE key='maintenance'") as c:
            m_val = (await c.fetchone())[0]
        async with db.execute("SELECT value FROM settings WHERE key='forced_sub'") as c:
            fs_val = (await c.fetchone())[0]
        async with db.execute("SELECT value FROM settings WHERE key='forced_sub_channel'") as c:
            fs_channel = (await c.fetchone())[0]
    m_text  = "🟢 الصيانة: مطفأ"      if m_val  == "0" else "🔴 الصيانة: يعمل"
    fs_text = "🔕 اشتراك إجباري: مطفأ" if fs_val == "0" else "🔔 اشتراك إجباري: يعمل"
    ch_label = f"📣 القناة: {fs_channel}" if fs_channel else "📣 تعيين قناة الاشتراك"
    kb = [
        [InlineKeyboardButton("📊 إحصائيات متقدمة", callback_data="adm_stats"),
         InlineKeyboardButton("📢 إذاعة", callback_data="adm_bc")],
        [InlineKeyboardButton("🚫 حظر/إلغاء", callback_data="adm_ban_req"),
         InlineKeyboardButton("👁️ إخفاء يوزر", callback_data="adm_hide_req")],
        [InlineKeyboardButton("👑 تفعيل اشتراك", callback_data="adm_premium_req"),
         InlineKeyboardButton("❌ إلغاء اشتراك", callback_data="adm_unpremium_req")],
        [InlineKeyboardButton("📝 سجل رسائل مستخدم", callback_data="adm_msglog_req"),
         InlineKeyboardButton("🔍 سجل بحث مستخدم", callback_data="adm_searchlog_req")],
        [InlineKeyboardButton("👥 المشتركين المدفوعين", callback_data="adm_premium_list"),
         InlineKeyboardButton("🔎 بحث عن مستخدم", callback_data="adm_find_user")],
        [InlineKeyboardButton("📋 آخر الرسائل الكلية", callback_data="adm_latest_msgs"),
         InlineKeyboardButton(m_text, callback_data="adm_toggle_m")],
        [InlineKeyboardButton(fs_text, callback_data="adm_toggle_fs"),
         InlineKeyboardButton(ch_label, callback_data="adm_set_channel")],
        [InlineKeyboardButton("🔑 تغيير مفتاح Serper API", callback_data="adm_change_api")],
        [InlineKeyboardButton("🔙 عودة", callback_data="verify")]
    ]
    return InlineKeyboardMarkup(kb)

# ════════════════════════════════════════════════
#           دالة الإحصائيات المتقدمة
# ════════════════════════════════════════════════
async def build_stats_text():
    today = datetime.now().date().isoformat()
    week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
    month_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_premium=1") as c:
            premium_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned=1") as c:
            banned_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (today,)) as c:
            new_today = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_ago,)) as c:
            new_week = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (month_ago,)) as c:
            new_month = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM search_log WHERE searched_at >= ?", (today,)) as c:
            searches_today = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM search_log") as c:
            searches_total = (await c.fetchone())[0]
        async with db.execute(
            "SELECT username, full_name, total_searches FROM users ORDER BY total_searches DESC LIMIT 5"
        ) as c:
            top_users = await c.fetchall()

    top_txt = ""
    for i, u in enumerate(top_users, 1):
        name = f"@{u[0]}" if u[0] else u[1] or "مجهول"
        top_txt += f"  {i}. {name} — {u[2]} بحث\n"

    pct = round((premium_count / total * 100) if total else 0, 1)
    return (
        f"📊 إحصائيات متقدمة\n"
        f"{'─'*28}\n"
        f"👥 إجمالي المستخدمين : {total}\n"
        f"🆕 جدد اليوم         : {new_today}\n"
        f"📅 جدد هذا الأسبوع   : {new_week}\n"
        f"🗓 جدد هذا الشهر     : {new_month}\n"
        f"{'─'*28}\n"
        f"👑 مشتركون مدفوعون  : {premium_count} ({pct}%)\n"
        f"🚫 محظورون           : {banned_count}\n"
        f"{'─'*28}\n"
        f"🔍 بحث اليوم         : {searches_today}\n"
        f"🔢 إجمالي عمليات البحث: {searches_total}\n"
        f"{'─'*28}\n"
        f"🏆 أكثر المستخدمين بحثاً:\n{top_txt}"
    )

# ════════════════════════════════════════════════
#                   المعالجات
# ════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now  = datetime.now().isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,)) as c:
            exists = await c.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO users (user_id, username, full_name, joined_at, last_seen) VALUES (?,?,?,?,?)",
                (user.id, user.username, user.full_name, now, now)
            )
            await db.commit()
            # فحص مايلستون
            async with db.execute("SELECT COUNT(*) FROM users") as c:
                count = (await c.fetchone())[0]
            if count in MILESTONE_USERS:
                try:
                    await context.bot.send_message(
                        ADMIN_ID, f"🎉 وصل البوت إلى {count} مستخدم!"
                    )
                except: pass

    if user.id != ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"👤 مستخدم جديد:\n"
            f"الاسم: {user.full_name}\n"
            f"اليوزر: @{user.username}\n"
            f"الآيدي: {user.id}"
        )
    txt = "👋 أهلاً بك في بوت كاشف التعليقات\n\nأتعهد أمام الله باستخدام البوت في الخير وعدم الإضرار بالآخرين."
    kb = [[InlineKeyboardButton("✅ أوافق وأتعهد", callback_data="agree")]]
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    data = q.data
    await q.answer()

    # ── القسم العام ──
    if data == "agree":
        kb = [[InlineKeyboardButton("📱 متابعة الحساب", url=INSTA_URL)],
              [InlineKeyboardButton("✅ تم المتابعة", callback_data="verify")]]
        await q.edit_message_text("🛡️ تابع حساب المطور لتفعيل البوت:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "verify":
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("UPDATE users SET status='active' WHERE user_id=?", (uid,))
            await db.commit()
        # فحص الاشتراك الإجباري
        if uid != ADMIN_ID:
            is_subbed = await check_forced_sub(q.get_bot(), uid)
            if not is_subbed:
                _, channel = await get_forced_sub()
                ch_link = f"https://t.me/{channel.lstrip('@')}"
                kb = [
                    [InlineKeyboardButton("📣 اشترك في القناة", url=ch_link)],
                    [InlineKeyboardButton("✅ تحققت من اشتراكي", callback_data="verify")]
                ]
                await q.edit_message_text(
                    f"⚠️ يجب الاشتراك في قناتنا أولاً للاستمرار:\n{channel}",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
                return
        kb = [[InlineKeyboardButton("🔍 ابدأ البحث عن يوزر", callback_data="start_search")]]
        if uid == ADMIN_ID:
            kb.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_main")])
        await q.edit_message_text("🎊 تم التفعيل بنجاح!", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "start_search":
        # فحص الاشتراك الإجباري عند كل بحث
        if uid != ADMIN_ID:
            is_subbed = await check_forced_sub(q.get_bot(), uid)
            if not is_subbed:
                _, channel = await get_forced_sub()
                ch_link = f"https://t.me/{channel.lstrip('@')}"
                kb = [
                    [InlineKeyboardButton("📣 اشترك في القناة", url=ch_link)],
                    [InlineKeyboardButton("✅ تحققت من اشتراكي", callback_data="start_search")]
                ]
                await q.edit_message_text(
                    f"⚠️ يجب الاشتراك في قناتنا للاستمرار:\n{channel}",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
                return
        await check_premium_expired(uid)
        today = datetime.now().date().isoformat()
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute(
                "SELECT searches_today, last_search_date, is_premium, premium_until FROM users WHERE user_id=?", (uid,)
            ) as c:
                row = await c.fetchone()
        searches_today = row[0] if row and row[1] == today else 0
        is_premium     = row[2] if row else 0
        premium_until  = row[3] if row else None
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT daily_limit FROM users WHERE user_id=?", (uid,)) as c:
                dl_row = await c.fetchone()
        limit     = (dl_row[0] if dl_row else FREE_DAILY_LIMIT) if is_premium else FREE_DAILY_LIMIT
        remaining = max(0, limit - searches_today)
        if is_premium and premium_until:
            expiry_str = datetime.fromisoformat(premium_until).strftime("%Y-%m-%d")
            status_line = f"👑 مشترك مدفوع | ينتهي: {expiry_str}"
        else:
            status_line = "🆓 حساب مجاني"
        info = (
            f"📊 حالة حسابك:\n{status_line}\n"
            f"🔍 المحاولات المتبقية اليوم: {remaining}/{limit}\n\n"
            "📝 أرسل الآن يوزر الإنستقرام (بدون @):"
        )
        kb = [[InlineKeyboardButton("🛡️ إخفاء حسابي", callback_data="user_request_hide")]]
        if not is_premium:
            kb.append([InlineKeyboardButton(
                "💎 اشترك وزد محاولاتك",
                url=f"https://t.me/{CONTACT_USER.replace('@','')}"
            )])
        kb.append([InlineKeyboardButton("ℹ️ الباقات والأسعار", callback_data="sub_info")])
        await q.edit_message_text(info, reply_markup=InlineKeyboardMarkup(kb))
        context.user_data['state'] = 'WAIT_SEARCH'

    elif data == "sub_info":
        await check_premium_expired(uid)
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute(
                "SELECT is_premium, premium_until, searches_today, last_search_date, total_searches, daily_limit FROM users WHERE user_id=?", (uid,)
            ) as c:
                row = await c.fetchone()
        today          = datetime.now().date().isoformat()
        is_premium     = row[0] if row else 0
        premium_until  = row[1] if row else None
        searches_today = row[2] if row and row[3] == today else 0
        total_searches = row[4] if row else 0
        daily_limit    = row[5] if row else FREE_DAILY_LIMIT
        limit          = daily_limit if is_premium else FREE_DAILY_LIMIT
        remaining      = max(0, limit - searches_today)

        # ── حالة الحساب ──
        if is_premium and premium_until:
            expiry_str = datetime.fromisoformat(premium_until).strftime("%Y-%m-%d")
            days_left  = max(0, (datetime.fromisoformat(premium_until) - datetime.now()).days)
            status_block = (
                f"👑 نوع الحساب: مشترك مدفوع\n"
                f"⚡ محاولاتك اليومية: {daily_limit}\n"
                f"📅 ينتهي في: {expiry_str}\n"
                f"⏳ الأيام المتبقية: {days_left} يوم"
            )
        else:
            status_block = f"🆓 نوع الحساب: مجاني ({FREE_DAILY_LIMIT} محاولات/يوم)"

        # ── بناء نص الباقات ──
        plans_txt = ""
        for p in PLANS:
            plans_txt += (
                f"┌ {p['name']}\n"
                f"├ 🔍 {p['trials']} محاولة يومياً\n"
                f"├ ₿ {p['btc']} BTC\n"
                f"└ 💵 {p['sar']} ﷼\n\n"
            )

        txt = (
            f"💎 الباقات والأسعار\n"
            f"{'─'*28}\n"
            f"{status_block}\n"
            f"{'─'*28}\n"
            f"🔍 محاولات اليوم : {searches_today}/{limit}\n"
            f"✅ متبقي          : {remaining}\n"
            f"📊 إجمالي بحثك   : {total_searches}\n"
            f"{'─'*28}\n"
            f"🛒 الباقات المتاحة:\n\n"
            f"{plans_txt}"
            f"📩 للاشتراك تواصل مع: {CONTACT_USER}"
        )
        kb = []
        if not is_premium:
            kb.append([InlineKeyboardButton(
                "💎 اشترك الآن",
                url=f"https://t.me/{CONTACT_USER.replace('@','')}"
            )])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="start_search")])
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

    # ── قسم الأدمن ──
    elif uid == ADMIN_ID:

        if data == "admin_main":
            await q.edit_message_text("🛠 لوحة تحكم الإدارة:", reply_markup=await get_admin_menu())

        elif data == "adm_stats":
            stats_txt = await build_stats_text()
            await q.edit_message_text(stats_txt, reply_markup=await get_admin_menu())

        elif data == "adm_bc":
            await q.edit_message_text("📢 أرسل نص الإذاعة الآن:")
            context.user_data['state'] = 'WAIT_BC'

        elif data == "adm_ban_req":
            await q.edit_message_text("🚫 أرسل آيدي المستخدم لحظره/إلغاء حظره:")
            context.user_data['state'] = 'WAIT_BAN'

        elif data == "adm_hide_req":
            await q.edit_message_text("👁️ أرسل اليوزر لإخفائه من البحث:")
            context.user_data['state'] = 'WAIT_HIDE'

        elif data == "adm_toggle_m":
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT value FROM settings WHERE key='maintenance'") as c:
                    cur_val = (await c.fetchone())[0]
                new_val = "0" if cur_val == "1" else "1"
                await db.execute("UPDATE settings SET value=? WHERE key='maintenance'", (new_val,))
                await db.commit()
            await q.edit_message_text("🛠 تم تغيير وضع الصيانة.", reply_markup=await get_admin_menu())

        elif data == "adm_premium_req":
            plans_txt = "\n".join([f"{i+1}. {p['name']} — {p['trials']} محاولة/يوم" for i, p in enumerate(PLANS)])
            await q.edit_message_text(
                f"👑 تفعيل اشتراك مدفوع\n\n"
                f"الباقات:\n{plans_txt}\n\n"
                f"الصيغة:\n<آيدي> <أيام> <رقم الباقة>\n\n"
                f"مثال (باقة 1 لمدة 30 يوم):\n123456789 30 1"
            )
            context.user_data['state'] = 'WAIT_PREMIUM'

        elif data == "adm_unpremium_req":
            await q.edit_message_text("❌ أرسل آيدي المستخدم لإلغاء اشتراكه:")
            context.user_data['state'] = 'WAIT_UNPREMIUM'

        # ── سجل رسائل مستخدم ──
        elif data == "adm_msglog_req":
            await q.edit_message_text(
                "📝 سجل رسائل مستخدم\n\nأرسل آيدي المستخدم:"
            )
            context.user_data['state'] = 'WAIT_MSGLOG'

        # ── سجل بحث مستخدم ──
        elif data == "adm_searchlog_req":
            await q.edit_message_text(
                "🔍 سجل بحث مستخدم\n\nأرسل آيدي المستخدم:"
            )
            context.user_data['state'] = 'WAIT_SEARCHLOG'

        # ── قائمة المشتركين المدفوعين ──
        elif data == "adm_premium_list":
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute(
                    "SELECT user_id, username, full_name, premium_until FROM users WHERE is_premium=1"
                ) as c:
                    rows = await c.fetchall()
            if not rows:
                txt = "❌ لا يوجد مشتركون مدفوعون حالياً."
            else:
                txt = "👑 المشتركون المدفوعون:\n\n"
                for r in rows:
                    name = f"@{r[1]}" if r[1] else r[2] or "مجهول"
                    exp  = r[3][:10] if r[3] else "غير محدد"
                    txt += f"• {name} (ID: {r[0]}) — ينتهي: {exp}\n"
            await q.edit_message_text(txt, reply_markup=await get_admin_menu())

        # ── بحث عن مستخدم ──
        elif data == "adm_find_user":
            await q.edit_message_text(
                "🔎 بحث عن مستخدم\n\nأرسل الآيدي أو اليوزر (بدون @):"
            )
            context.user_data['state'] = 'WAIT_FIND_USER'

        # ── تغيير مفتاح Serper API ──
        elif data == "adm_change_api":
            current_key = await get_serper_key()
            masked = current_key[:6] + "••••••••••••••••" + current_key[-4:]
            await q.edit_message_text(
                f"🔑 تغيير مفتاح Serper API\n\n"
                f"المفتاح الحالي:\n`{masked}`\n\n"
                f"أرسل المفتاح الجديد الآن:",
                parse_mode="Markdown"
            )
            context.user_data['state'] = 'WAIT_CHANGE_API'

        # ── تبديل الاشتراك الإجباري ──
        elif data == "adm_toggle_fs":
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT value FROM settings WHERE key='forced_sub'") as c:
                    cur = (await c.fetchone())[0]
                new_v = "0" if cur == "1" else "1"
                await db.execute("UPDATE settings SET value=? WHERE key='forced_sub'", (new_v,))
                await db.commit()
            state_txt = "✅ تم تفعيل الاشتراك الإجباري!" if new_v == "1" else "❌ تم إيقاف الاشتراك الإجباري!"
            await q.edit_message_text(state_txt, reply_markup=await get_admin_menu())

        # ── تعيين قناة الاشتراك الإجباري ──
        elif data == "adm_set_channel":
            _, current_ch = await get_forced_sub()
            ch_display = current_ch if current_ch else "غير محددة"
            await q.edit_message_text(
                f"📣 تعيين قناة الاشتراك الإجباري\n\n"
                f"القناة الحالية: {ch_display}\n\n"
                "أرسل معرف القناة مثال:\n@mychannel"
            )
            context.user_data['state'] = 'WAIT_SET_CHANNEL'

        # ── آخر الرسائل الكلية ──
        elif data == "adm_latest_msgs":
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute(
                    "SELECT user_id, username, full_name, message, msg_type, logged_at "
                    "FROM messages_log ORDER BY id DESC LIMIT 15"
                ) as c:
                    rows = await c.fetchall()
            if not rows:
                txt = "📭 لا توجد رسائل مسجلة بعد."
            else:
                txt = "📋 آخر 15 رسالة في البوت:\n\n"
                for r in rows:
                    name = f"@{r[1]}" if r[1] else r[2] or "مجهول"
                    time_str = r[5][:16] if r[5] else ""
                    msg_preview = (r[3][:40] + "…") if r[3] and len(r[3]) > 40 else (r[3] or "")
                    txt += f"[{time_str}] {name}:\n{msg_preview}\n\n"
            await q.edit_message_text(txt, reply_markup=await get_admin_menu())


# ════════════════════════════════════════════════
#               معالج الرسائل النصية
# ════════════════════════════════════════════════
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    uid   = user.id
    state = context.user_data.get('state')
    text  = update.message.text.strip()

    # ── تسجيل الرسالة فوراً ──
    if uid != ADMIN_ID:
        await log_message(user, text)
        # تحويل فوري للأدمن
        name = f"@{user.username}" if user.username else user.full_name or str(uid)
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💬 رسالة جديدة\n"
                f"👤 {name} (ID: {uid})\n"
                f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"📝 {text}"
            )
        except:
            pass

    # ══ منطق الأدمن ══
    if uid == ADMIN_ID:
        if state == 'WAIT_BC':
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT user_id FROM users") as cur:
                    for r in await cur.fetchall():
                        try: await context.bot.send_message(r[0], f"📢 إعلان من الإدارة:\n\n{text}")
                        except: pass
            await update.message.reply_text("✅ تم إرسال الإذاعة.", reply_markup=await get_admin_menu())
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
                        s = "محظور ✅" if new_b else "غير محظور ✅"
                        await update.message.reply_text(f"تم تحديث حالة {tid}: {s}", reply_markup=await get_admin_menu())
                    else:
                        await update.message.reply_text("❌ الآيدي غير موجود.")
            except:
                await update.message.reply_text("❌ يرجى إرسال آيدي رقمي صحيح.")
            context.user_data['state'] = None
            return

        elif state == 'WAIT_HIDE':
            u_hide = text.replace("@", "").lower()
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("INSERT OR IGNORE INTO hidden_users VALUES (?)", (u_hide,))
                await db.commit()
            await update.message.reply_text(f"✅ {u_hide} أصبح مخفياً.", reply_markup=await get_admin_menu())
            context.user_data['state'] = None
            return

        elif state == 'WAIT_PREMIUM':
            try:
                parts = text.split()
                if len(parts) not in (2, 3): raise ValueError
                tid  = int(parts[0])
                days = int(parts[1])
                # اختيار الباقة: 1 أو 2، الافتراضي 1
                plan_num = int(parts[2]) - 1 if len(parts) == 3 else 0
                if plan_num not in range(len(PLANS)): plan_num = 0
                plan   = PLANS[plan_num]
                trials = plan["trials"]
                expiry = (datetime.now() + timedelta(days=days)).isoformat()
                async with aiosqlite.connect(DB_FILE) as db:
                    async with db.execute("SELECT user_id FROM users WHERE user_id=?", (tid,)) as c:
                        if not await c.fetchone():
                            await update.message.reply_text("❌ الآيدي غير موجود.")
                            context.user_data['state'] = None
                            return
                    await db.execute(
                        "UPDATE users SET is_premium=1, premium_until=?, daily_limit=? WHERE user_id=?",
                        (expiry, trials, tid)
                    )
                    await db.commit()
                exp_str = datetime.fromisoformat(expiry).strftime("%Y-%m-%d")
                try:
                    await context.bot.send_message(
                        tid,
                        f"🎉 تم تفعيل اشتراكك!\n\n"
                        f"👑 الباقة: {plan['name']}\n"
                        f"⚡ {trials} محاولة يومياً\n"
                        f"📅 تنتهي في: {exp_str}\n\nاستمتع! 🚀"
                    )
                except: pass
                await update.message.reply_text(
                    f"✅ تم تفعيل اشتراك {tid}\n"
                    f"📦 الباقة: {plan['name']}\n"
                    f"⚡ {trials} محاولة/يوم\n"
                    f"📅 حتى: {exp_str}",
                    reply_markup=await get_admin_menu()
                )
            except:
                plans_help = "\n".join([f"{i+1} = {p['name']} ({p['trials']} محاولة)" for i, p in enumerate(PLANS)])
                await update.message.reply_text(
                    f"❌ الصيغة غير صحيحة.\n\n"
                    f"الصيغة: <آيدي> <أيام> <رقم الباقة>\n"
                    f"مثال: 123456789 30 1\n\n"
                    f"الباقات:\n{plans_help}"
                )
            context.user_data['state'] = None
            return

        elif state == 'WAIT_UNPREMIUM':
            try:
                tid = int(text)
                async with aiosqlite.connect(DB_FILE) as db:
                    async with db.execute("SELECT is_premium FROM users WHERE user_id=?", (tid,)) as c:
                        res = await c.fetchone()
                    if res:
                        await db.execute(
                            "UPDATE users SET is_premium=0, premium_until=NULL WHERE user_id=?", (tid,)
                        )
                        await db.commit()
                        try: await context.bot.send_message(tid, "⚠️ تم إلغاء اشتراكك المدفوع.")
                        except: pass
                        await update.message.reply_text(f"✅ تم إلغاء اشتراك {tid}.", reply_markup=await get_admin_menu())
                    else:
                        await update.message.reply_text("❌ الآيدي غير موجود.")
            except:
                await update.message.reply_text("❌ يرجى إرسال آيدي رقمي صحيح.")
            context.user_data['state'] = None
            return

        # ── سجل رسائل مستخدم ──
        # ── تغيير مفتاح Serper API ──
        # ── تعيين قناة الاشتراك الإجباري ──
        elif state == 'WAIT_SET_CHANNEL':
            channel = text.strip()
            if not channel.startswith("@"):
                channel = "@" + channel
            # تحقق من صحة القناة
            try:
                chat = await context.bot.get_chat(channel)
                async with aiosqlite.connect(DB_FILE) as db:
                    await db.execute(
                        "UPDATE settings SET value=? WHERE key='forced_sub_channel'", (channel,)
                    )
                    await db.commit()
                await update.message.reply_text(
                    f"✅ تم تعيين القناة بنجاح!\n📣 القناة: {channel}\n👥 الاسم: {chat.title}",
                    reply_markup=await get_admin_menu()
                )
            except:
                await update.message.reply_text(
                    "❌ تعذر إيجاد القناة.\n\n"
                    "تأكد من:\n"
                    "1. أن البوت مضاف كأدمن في القناة\n"
                    "2. أن المعرف صحيح مثل @mychannel",
                    reply_markup=await get_admin_menu()
                )
            context.user_data['state'] = None
            return

        elif state == 'WAIT_CHANGE_API':
            new_key = text.strip()
            if len(new_key) < 10:
                await update.message.reply_text(
                    "❌ المفتاح يبدو قصيراً جداً، تأكد منه وأعد المحاولة."
                )
                context.user_data['state'] = None
                return
            # اختبار المفتاح الجديد قبل الحفظ
            test_ok = False
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://google.serper.dev/search",
                        json={"q": "test", "num": 1},
                        headers={"X-API-KEY": new_key, "Content-Type": "application/json"},
                        timeout=10
                    ) as resp:
                        test_ok = resp.status == 200
            except:
                pass
            if not test_ok:
                await update.message.reply_text(
                    "❌ المفتاح غير صحيح أو منتهي الصلاحية.\n"
                    "تحقق منه من موقع serper.dev وأعد المحاولة.",
                    reply_markup=await get_admin_menu()
                )
                context.user_data['state'] = None
                return
            await set_serper_key(new_key)
            masked = new_key[:6] + "••••••••••••••••" + new_key[-4:]
            await update.message.reply_text(
                f"✅ تم تحديث مفتاح Serper API بنجاح!\n\n"
                f"المفتاح الجديد:\n`{masked}`",
                parse_mode="Markdown",
                reply_markup=await get_admin_menu()
            )
            context.user_data['state'] = None
            return

        elif state == 'WAIT_MSGLOG':
            try:
                tid = int(text)
                async with aiosqlite.connect(DB_FILE) as db:
                    async with db.execute(
                        "SELECT message, msg_type, logged_at FROM messages_log "
                        "WHERE user_id=? ORDER BY id DESC LIMIT 20", (tid,)
                    ) as c:
                        rows = await c.fetchall()
                if not rows:
                    await update.message.reply_text("📭 لا توجد رسائل مسجلة لهذا المستخدم.", reply_markup=await get_admin_menu())
                else:
                    txt = f"📝 آخر 20 رسالة للمستخدم {tid}:\n\n"
                    for r in rows:
                        time_str = r[2][:16] if r[2] else ""
                        preview  = (r[0][:50] + "…") if r[0] and len(r[0]) > 50 else (r[0] or "")
                        txt += f"[{time_str}] {preview}\n"
                    await update.message.reply_text(txt, reply_markup=await get_admin_menu())
            except:
                await update.message.reply_text("❌ يرجى إرسال آيدي رقمي صحيح.")
            context.user_data['state'] = None
            return

        # ── سجل بحث مستخدم ──
        elif state == 'WAIT_SEARCHLOG':
            try:
                tid = int(text)
                async with aiosqlite.connect(DB_FILE) as db:
                    async with db.execute(
                        "SELECT target, searched_at FROM search_log "
                        "WHERE user_id=? ORDER BY id DESC LIMIT 20", (tid,)
                    ) as c:
                        rows = await c.fetchall()
                if not rows:
                    await update.message.reply_text("📭 لا توجد عمليات بحث لهذا المستخدم.", reply_markup=await get_admin_menu())
                else:
                    txt = f"🔍 آخر 20 بحث للمستخدم {tid}:\n\n"
                    for r in rows:
                        time_str = r[1][:16] if r[1] else ""
                        txt += f"[{time_str}] بحث عن: {r[0]}\n"
                    await update.message.reply_text(txt, reply_markup=await get_admin_menu())
            except:
                await update.message.reply_text("❌ يرجى إرسال آيدي رقمي صحيح.")
            context.user_data['state'] = None
            return

        # ── بحث عن مستخدم ──
        elif state == 'WAIT_FIND_USER':
            query_clean = text.replace("@", "").lower()
            async with aiosqlite.connect(DB_FILE) as db:
                # جرب آيدي أولاً
                row = None
                try:
                    tid = int(text)
                    async with db.execute("SELECT * FROM users WHERE user_id=?", (tid,)) as c:
                        row = await c.fetchone()
                except: pass
                # جرب اليوزر
                if not row:
                    async with db.execute(
                        "SELECT * FROM users WHERE lower(username)=?", (query_clean,)
                    ) as c:
                        row = await c.fetchone()
            if not row:
                await update.message.reply_text("❌ لم يتم إيجاد المستخدم.", reply_markup=await get_admin_menu())
            else:
                # row: id, username, full_name, status, is_banned, is_premium, premium_until,
                #       searches_today, last_search_date, total_searches, joined_at, last_seen, last_msg_time
                prem_txt = f"👑 نعم — ينتهي: {row[6][:10]}" if row[5] else "🆓 لا"
                txt = (
                    f"🔎 معلومات المستخدم:\n\n"
                    f"🆔 الآيدي       : {row[0]}\n"
                    f"👤 الاسم        : {row[2] or 'غير محدد'}\n"
                    f"📛 اليوزر       : @{row[1] or 'غير محدد'}\n"
                    f"🚫 محظور        : {'نعم' if row[4] else 'لا'}\n"
                    f"💎 مشترك مدفوع : {prem_txt}\n"
                    f"🔍 بحث اليوم    : {row[7]}\n"
                    f"📊 إجمالي البحث : {row[9]}\n"
                    f"📅 انضم في      : {(row[10] or '')[:10]}\n"
                    f"🕒 آخر ظهور     : {(row[11] or '')[:16]}\n"
                )
                await update.message.reply_text(txt, reply_markup=await get_admin_menu())
            context.user_data['state'] = None
            return

    # ══ فحص الصيانة والحظر ══
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT value FROM settings WHERE key='maintenance'") as c:
            m_val = (await c.fetchone())[0]
        if uid != ADMIN_ID and m_val == "1":
            await update.message.reply_text("⚠️ البوت في صيانة حالياً.")
            return
        async with db.execute("SELECT is_banned, status FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                await update.message.reply_text("❌ أنت محظور.")
                return

    # ══ حماية السبام ══
    if uid != ADMIN_ID:
        allowed = await check_spam(uid)
        if not allowed:
            await update.message.reply_text(f"⏳ انتظر {SPAM_SECONDS} ثواني بين كل طلب.")
            return

    # ══ منطق البحث ══
    if state == 'WAIT_SEARCH' or (row and row[1] == 'active'):
        allowed, reason = await can_search(uid)
        if not allowed:
            kb = [[InlineKeyboardButton("💎 اشترك الآن", url=f"https://t.me/{ADMIN_USER.replace('@','')}")]]
            await update.message.reply_text(reason, reply_markup=InlineKeyboardMarkup(kb))
            return

        target = text.replace("@", "")
        msg = await update.message.reply_text("🔎 جاري البحث عن تعليقات...")
        await increment_search(uid)
        await log_search(user, target)
        res = await search_insta_links(target)

        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute(
                "SELECT searches_today, is_premium FROM users WHERE user_id=?", (uid,)
            ) as c:
                urow = await c.fetchone()
        if urow:
            limit     = PREMIUM_DAILY_LIMIT if urow[1] else FREE_DAILY_LIMIT
            remaining = max(0, limit - urow[0])
            res += f"\n\n🔍 محاولاتك المتبقية اليوم: {remaining}/{limit}"

        await msg.edit_text(res, disable_web_page_preview=True)
        context.user_data['state'] = None


# ════════════════════════════════════════════════
async def main():
    await init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("--- البوت V22 يعمل بكامل طاقته ---")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
