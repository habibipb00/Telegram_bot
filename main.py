#Optimized and error-handled version
#!/usr/bin/env python3
"""
🚀 Professional Telegram Bot with Token Economy
Features: Admin Panel, Referral System, UPI Payments, Content Management
"""

import os
import sqlite3
import logging
import time
import hashlib
from datetime import datetime
from functools import wraps
import telebot
from telebot import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
UPI_ID = os.getenv('UPI_ID')
CHANNEL_ID = os.getenv('CHANNEL_ID', '')

# Validate configuration
if not all([BOT_TOKEN, ADMIN_ID, UPI_ID]):
    print("❌ Missing required environment variables!")
    exit(1)

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rate limiting
user_last_action = {}
RATE_LIMIT = 2

# Database class
class TokenBotDB:
    def __init__(self):
        self.db_path = 'tokenbot.db'
        self.init_database()
        logger.info("🗄️ Database initialized successfully")
    
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                tokens INTEGER DEFAULT 10,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                total_earned INTEGER DEFAULT 10,
                total_spent INTEGER DEFAULT 0,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                tokens INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP
            )
        ''')
        
        # Content table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                file_id TEXT,
                file_type TEXT,
                tokens_required INTEGER DEFAULT 10,
                deeplink TEXT UNIQUE,
                views INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Referrals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                bonus_tokens INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def execute(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            result = cursor.fetchall()
            conn.commit()
            return result
        except Exception as e:
            logger.error(f"Database error: {e}")
            conn.rollback()
            return []
        finally:
            conn.close()
    
    def get_user(self, user_id):
        result = self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return result[0] if result else None
    
    def create_user(self, user_id, username, first_name, referred_by=None):
        referral_code = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8].upper()
        
        # Create user with 10 free tokens
        self.execute(
            "INSERT OR REPLACE INTO users (user_id, username, first_name, referral_code, referred_by, tokens, total_earned) VALUES (?, ?, ?, ?, ?, 10, 10)",
            (user_id, username, first_name, referral_code, referred_by)
        )
        
        # Add referral bonus
        if referred_by:
            self.execute("UPDATE users SET tokens = tokens + 5, total_earned = total_earned + 5 WHERE user_id = ?", (referred_by,))
            self.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referred_by, user_id))
        
        return referral_code
    
    def update_tokens(self, user_id, tokens):
        if tokens > 0:
            self.execute("UPDATE users SET tokens = tokens + ?, total_earned = total_earned + ? WHERE user_id = ?", (tokens, tokens, user_id))
        else:
            self.execute("UPDATE users SET tokens = tokens + ?, total_spent = total_spent + ? WHERE user_id = ?", (tokens, abs(tokens), user_id))
    
    def get_user_by_referral(self, code):
        result = self.execute("SELECT * FROM users WHERE referral_code = ?", (code,))
        return result[0] if result else None

# Initialize database
db = TokenBotDB()

# Decorators
def rate_limit(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        current_time = time.time()
        
        if user_id in user_last_action and current_time - user_last_action[user_id] < RATE_LIMIT:
            bot.reply_to(message, "⚡ Please wait a moment before sending another command!")
            return
        
        user_last_action[user_id] = current_time
        return func(message)
    return wrapper

def admin_only(func):
    @wraps(func)
    def wrapper(message):
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "🚫 Access denied! Admin only command.")
            return
        return func(message)
    return wrapper

def registered_only(func):
    @wraps(func)
    def wrapper(message):
        if not db.get_user(message.from_user.id):
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("🚀 Start Bot", callback_data="start_bot"))
            bot.reply_to(message, "❌ Please register first!", reply_markup=keyboard)
            return
        return func(message)
    return wrapper

# Utility functions
def create_keyboard(buttons):
    keyboard = types.InlineKeyboardMarkup()
    for row in buttons:
        keyboard_row = [types.InlineKeyboardButton(btn['text'], callback_data=btn.get('callback_data'), url=btn.get('url')) for btn in row]
        keyboard.row(*keyboard_row)
    return keyboard

def safe_send(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except:
        return None

# 🚀 USER COMMANDS

@bot.message_handler(commands=['start'])
@rate_limit
def start_command(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name or "User"
        
        # Handle content deeplink
        if len(message.text.split()) > 1 and message.text.split()[1].startswith('content_'):
            handle_content_access(message)
            return
        
        # Check referral
        referred_by = None
        if len(message.text.split()) > 1:
            ref_code = message.text.split()[1]
            referrer = db.get_user_by_referral(ref_code)
            if referrer and referrer[0] != user_id:
                referred_by = referrer[0]
        
        # Check existing user
        user = db.get_user(user_id)
        if user:
            welcome_text = f"""
🎉 **Welcome back, {first_name}!**

💰 **Current Balance:** {user[3]} tokens
📊 **Total Earned:** {user[8]} tokens
💸 **Total Spent:** {user[9]} tokens

Ready to explore premium content? 🚀
"""
            keyboard = create_keyboard([
                [{'text': '💰 Check Balance', 'callback_data': 'balance'}, {'text': '💳 Buy Tokens', 'callback_data': 'buy'}],
                [{'text': '👥 Referrals', 'callback_data': 'referrals'}, {'text': '📊 My Stats', 'callback_data': 'stats'}]
            ])
            bot.reply_to(message, welcome_text, reply_markup=keyboard)
            return
        
        # Create new user
        ref_code = db.create_user(user_id, username, first_name, referred_by)
        
        welcome_text = f"""
🎉 **Welcome to TokenBot, {first_name}!**

🎁 **Welcome Bonus:** 10 FREE tokens!
🔗 **Your Referral Code:** `{ref_code}`

**💡 How to earn more tokens:**
• 👥 Refer friends (+5 tokens each)
• 💳 Purchase token packages
• 🎯 Complete daily tasks

**🚀 Quick Start:**
"""
        
        if referred_by:
            welcome_text += "\n🎊 **Referral Bonus:** Your referrer got 5 tokens!"
        
        keyboard = create_keyboard([
            [{'text': '💰 Check Balance', 'callback_data': 'balance'}, {'text': '💳 Buy Tokens', 'callback_data': 'buy'}],
            [{'text': '👥 Share & Earn', 'callback_data': 'referrals'}, {'text': '❓ How it Works', 'callback_data': 'help'}]
        ])
        
        bot.reply_to(message, welcome_text, reply_markup=keyboard)
        logger.info(f"🆕 New user registered: {first_name} ({user_id})")
        
    except Exception as e:
        logger.error(f"Start command error: {e}")
        bot.reply_to(message, "❌ Registration error. Please try again!")

@bot.message_handler(commands=['balance'])
@rate_limit
@registered_only
def balance_command(message):
    try:
        user = db.get_user(message.from_user.id)
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals else 0
        
        balance_text = f"""
💰 **Your Token Wallet**

**💎 Current Balance:** {user[3]} tokens
**📈 Total Earned:** {user[8]} tokens  
**📉 Total Spent:** {user[9]} tokens
**👥 Referrals Made:** {total_refs}

**🔗 Your Referral Code:** `{user[4]}`
**📱 Share Link:** 
`https://t.me/{bot.get_me().username}?start={user[4]}`

💡 *Share your link to earn 5 tokens per referral!*
"""
        
        keyboard = create_keyboard([
            [{'text': '💳 Buy More Tokens', 'callback_data': 'buy'}, {'text': '👥 Invite Friends', 'callback_data': 'referrals'}],
            [{'text': '📊 Detailed Stats', 'callback_data': 'stats'}, {'text': '🔄 Refresh', 'callback_data': 'balance'}]
        ])
        
        bot.reply_to(message, balance_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Balance error: {e}")
        bot.reply_to(message, "❌ Error loading balance!")

@bot.message_handler(commands=['buy'])
@rate_limit
@registered_only
def buy_command(message):
    try:
        buy_text = f"""
💳 **Token Store - Premium Packages**

**🎯 Special Offers:**
• 💎 **100 Tokens** - ₹10 `(₹0.10 each)`
• 🔥 **500 Tokens** - ₹45 `(₹0.09 each)` **10% OFF**
• ⭐ **1000 Tokens** - ₹80 `(₹0.08 each)` **20% OFF**
• 👑 **2000 Tokens** - ₹150 `(₹0.075 each)` **25% OFF**

**💰 Payment Method:** UPI Only
**🏦 UPI ID:** `{UPI_ID}`

**📋 Purchase Process:**
1️⃣ Select package below
2️⃣ Pay via UPI
3️⃣ Send payment screenshot
4️⃣ Get tokens instantly after verification!

⚡ *Verification time: 1-24 hours*
"""
        
        keyboard = create_keyboard([
            [{'text': '💎 100 - ₹10', 'callback_data': 'buy_100'}, {'text': '🔥 500 - ₹45', 'callback_data': 'buy_500'}],
            [{'text': '⭐ 1000 - ₹80', 'callback_data': 'buy_1000'}, {'text': '👑 2000 - ₹150', 'callback_data': 'buy_2000'}],
            [{'text': '💬 Contact Support', 'url': f'tg://user?id={ADMIN_ID}'}]
        ])
        
        bot.reply_to(message, buy_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Buy error: {e}")
        bot.reply_to(message, "❌ Error loading store!")

@bot.message_handler(commands=['refer'])
@rate_limit
@registered_only
def refer_command(message):
    try:
        user = db.get_user(message.from_user.id)
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals else 0
        
        refer_text = f"""
👥 **Referral Program - Earn Together!**

**🎯 Your Stats:**
• 🔗 **Referral Code:** `{user[4]}`
• 👥 **Total Referrals:** {total_refs}
• 💰 **Tokens Earned:** {total_refs * 5}

**💡 How it works:**
1️⃣ Share your unique link
2️⃣ Friends join using your link  
3️⃣ You get **5 tokens** per referral
4️⃣ No limits - refer unlimited friends!

**📱 Your Magic Link:**
`https://t.me/{bot.get_me().username}?start={user[4]}`

🚀 *Start sharing and watch your tokens grow!*
"""
        
        keyboard = create_keyboard([
            [{'text': '📱 Share on Telegram', 'url': f'https://t.me/share/url?url=https://t.me/{bot.get_me().username}?start={user[4]}&text=🚀 Join this amazing bot and get FREE tokens!'}],
            [{'text': '📋 Copy Link', 'callback_data': f'copy_{user[4]}'}, {'text': '📊 Referral Stats', 'callback_data': 'ref_stats'}]
        ])
        
        bot.reply_to(message, refer_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Refer error: {e}")
        bot.reply_to(message, "❌ Error loading referral info!")

# 🔧 ADMIN COMMANDS

@bot.message_handler(commands=['admin_stats'])
@admin_only
def admin_stats(message):
    try:
        stats = {
            'users': db.execute("SELECT COUNT(*) FROM users")[0][0],
            'tokens_total': db.execute("SELECT SUM(tokens) FROM users")[0][0] or 0,
            'payments_total': db.execute("SELECT COUNT(*) FROM payments")[0][0],
            'payments_pending': db.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")[0][0],
            'content_total': db.execute("SELECT COUNT(*) FROM content")[0][0],
            'referrals_total': db.execute("SELECT COUNT(*) FROM referrals")[0][0],
            'revenue': db.execute("SELECT SUM(amount) FROM payments WHERE status = 'verified'")[0][0] or 0
        }
        
        stats_text = f"""
📊 **Admin Dashboard - Bot Analytics**

**👥 Users & Activity:**
• Total Users: {stats['users']:,}
• Active Tokens: {stats['tokens_total']:,}
• Total Referrals: {stats['referrals_total']:,}

**💰 Financial Overview:**
• Total Payments: {stats['payments_total']:,}
• Pending Verification: {stats['payments_pending']:,}
• Total Revenue: ₹{stats['revenue']:,.2f}

**📁 Content Library:**
• Total Content: {stats['content_total']:,}

**🕐 Last Updated:** {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""
        
        keyboard = create_keyboard([
            [{'text': '👥 User Management', 'callback_data': 'admin_users'}, {'text': '💳 Payments', 'callback_data': 'admin_payments'}],
            [{'text': '📁 Content Manager', 'callback_data': 'admin_content'}, {'text': '🔄 Refresh', 'callback_data': 'admin_refresh'}]
        ])
        
        bot.reply_to(message, stats_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        bot.reply_to(message, f"❌ Stats error: {e}")

@bot.message_handler(commands=['admin_tokens'])
@admin_only
def admin_tokens(message):
    try:
        args = message.text.split()
        if len(args) < 4:
            help_text = """
🔧 **Token Management System**

**Usage:** `/admin_tokens <action> <user_id> <amount>`

**Actions:**
• `add` - Add tokens to user
• `remove` - Remove tokens from user
• `set` - Set exact token amount

**Examples:**
• `/admin_tokens add 123456789 100`
• `/admin_tokens remove 123456789 50`
• `/admin_tokens set 123456789 200`
"""
            bot.reply_to(message, help_text)
            return
        
        action, user_id, amount = args[1].lower(), int(args[2]), int(args[3])
        
        user = db.get_user(user_id)
        if not user:
            bot.reply_to(message, f"❌ User {user_id} not found!")
            return
        
        current_tokens = user[3]
        
        if action == 'add':
            db.update_tokens(user_id, amount)
            new_balance = current_tokens + amount
            action_text = f"Added {amount} tokens"
        elif action == 'remove':
            if current_tokens < amount:
                bot.reply_to(message, f"❌ User only has {current_tokens} tokens!")
                return
            db.update_tokens(user_id, -amount)
            new_balance = current_tokens - amount
            action_text = f"Removed {amount} tokens"
        elif action == 'set':
            diff = amount - current_tokens
            db.update_tokens(user_id, diff)
            new_balance = amount
            action_text = f"Set balance to {amount} tokens"
        else:
            bot.reply_to(message, "❌ Invalid action! Use: add, remove, or set")
            return
        
        # Notify user
        safe_send(user_id, f"💰 **Token Update**\n\n{action_text}\n**New Balance:** {new_balance} tokens\n\nThank you! 🎉")
        
        bot.reply_to(message, f"✅ **Success!**\n\n👤 User: {user[2]} (`{user_id}`)\n🔧 Action: {action_text}\n💰 New Balance: {new_balance} tokens")
        logger.info(f"Admin token action: {action_text} for user {user_id}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID or amount!")
    except Exception as e:
        logger.error(f"Admin tokens error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['admin_upload'])
@admin_only
def admin_upload(message):
    try:
        upload_text = """
📁 **Content Upload Manager**

**📋 Instructions:**
1️⃣ Send any file (photo, video, document, audio)
2️⃣ Add caption in this format:
   `TITLE | DESCRIPTION | TOKENS_REQUIRED`

**📝 Example Caption:**
`Premium Course | Advanced Python Tutorial | 50`

**✅ Supported Files:**
• 📷 Photos & Images
• 🎥 Videos & GIFs  
• 📄 Documents & PDFs
• 🎵 Audio & Music

**🚀 Features:**
• Auto-generated access links
• View tracking & analytics
• Token-based access control
• Channel auto-posting (if configured)

Ready to upload? Send your file with caption! 📤
"""
        
        keyboard = create_keyboard([
            [{'text': '📊 Content Stats', 'callback_data': 'content_stats'}, {'text': '📋 Content List', 'callback_data': 'content_list'}],
            [{'text': '❌ Cancel Upload', 'callback_data': 'cancel_upload'}]
        ])
        
        bot.reply_to(message, upload_text, reply_markup=keyboard)
        bot.register_next_step_handler(message, handle_admin_upload)
        
    except Exception as e:
        logger.error(f"Admin upload error: {e}")
        bot.reply_to(message, "❌ Upload initialization failed!")

def handle_admin_upload(message):
    try:
        if message.text and message.text.lower() in ['cancel', '/cancel']:
            bot.reply_to(message, "❌ Upload cancelled!")
            return
        
        if message.content_type not in ['photo', 'video', 'document', 'audio']:
            bot.reply_to(message, "❌ Invalid file type! Send photo, video, document, or audio.")
            bot.register_next_step_handler(message, handle_admin_upload)
            return
        
        if not message.caption:
            bot.reply_to(message, "❌ Missing caption! Format: `TITLE | DESCRIPTION | TOKENS_REQUIRED`")
            bot.register_next_step_handler(message, handle_admin_upload)
            return
        
        parts = [p.strip() for p in message.caption.split(' | ')]
        if len(parts) != 3:
            bot.reply_to(message, "❌ Invalid format! Use: `TITLE | DESCRIPTION | TOKENS_REQUIRED`")
            bot.register_next_step_handler(message, handle_admin_upload)
            return
        
        title, description, tokens_str = parts
        tokens_required = int(tokens_str)
        
        # Get file ID
        file_id = getattr(message, message.content_type)
        if isinstance(file_id, list):
            file_id = file_id[-1].file_id
        else:
            file_id = file_id.file_id
        
        # Generate deeplink
        deeplink = hashlib.md5(f"{file_id}{time.time()}".encode()).hexdigest()[:12]
        
        # Save to database
        db.execute(
            "INSERT INTO content (title, description, file_id, file_type, tokens_required, deeplink) VALUES (?, ?, ?, ?, ?, ?)",
            (title, description, file_id, message.content_type, tokens_required, deeplink)
        )
        
        access_link = f"https://t.me/{bot.get_me().username}?start=content_{deeplink}"
        
        success_text = f"""
✅ **Content Uploaded Successfully!**

**📁 Details:**
• **Title:** {title}
• **Description:** {description}
• **Tokens Required:** {tokens_required}
• **File Type:** {message.content_type.title()}
• **Deeplink ID:** `{deeplink}`

**🔗 Access Link:**
`{access_link}`

**📊 Status:** Active & Ready for Users!
**📅 Upload Time:** {datetime.now().strftime('%d/%m/%Y %H:%M')}

Content is now live and accessible! 🚀
"""
        
        keyboard = create_keyboard([
            [{'text': '📤 Post to Channel', 'callback_data': f'post_{deeplink}'}, {'text': '👁️ Preview', 'callback_data': f'preview_{deeplink}'}],
            [{'text': '📁 Upload More', 'callback_data': 'upload_more'}, {'text': '📊 Content Stats', 'callback_data': 'content_stats'}]
        ])
        
        bot.reply_to(message, success_text, reply_markup=keyboard)
        logger.info(f"Content uploaded: {title} ({deeplink}) - {tokens_required} tokens")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid token amount! Use a number.")
        bot.register_next_step_handler(message, handle_admin_upload)
    except Exception as e:
        logger.error(f"Upload handler error: {e}")
        bot.reply_to(message, f"❌ Upload failed: {e}")

# 🎯 CALLBACK HANDLERS

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data
        user_id = call.from_user.id
        
        if data.startswith('buy_'):
            handle_buy_callback(call)
        elif data == 'balance':
            balance_command(call.message)
        elif data == 'referrals':
            refer_command(call.message)
        elif data.startswith('content_'):
            handle_content_callback(call)
        elif data.startswith('copy_'):
            ref_code = data.split('_')[1]
            bot.answer_callback_query(call.id, f"🔗 Link: https://t.me/{bot.get_me().username}?start={ref_code}", show_alert=True)
        elif data == 'help':
            help_text = """
❓ **How TokenBot Works**

**🎁 Welcome Bonus:** 10 FREE tokens on signup
**💰 Earn Tokens:** Refer friends (+5 each)
**🛒 Buy Tokens:** Premium packages available
**🔓 Access Content:** Use tokens for premium content

**🚀 Start earning and enjoying premium content!**
"""
            bot.edit_message_text(help_text, call.message.chat.id, call.message.message_id)
        
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "❌ Error occurred!")

def handle_buy_callback(call):
    try:
        packages = {
            'buy_100': {'tokens': 100, 'price': 10},
            'buy_500': {'tokens': 500, 'price': 45},
            'buy_1000': {'tokens': 1000, 'price': 80},
            'buy_2000': {'tokens': 2000, 'price': 150}
        }
        
        package = packages[call.data]
        user_id = call.from_user.id
        
        # Create payment record
        db.execute("INSERT INTO payments (user_id, amount, tokens) VALUES (?, ?, ?)", (user_id, package['price'], package['tokens']))
        
        payment_text = f"""
💳 **Payment Instructions**

**📦 Package:** {package['tokens']} Tokens
**💰 Amount:** ₹{package['price']}
**🏦 UPI ID:** `{UPI_ID}`

**📋 Step-by-Step Process:**
1️⃣ Open any UPI app (GPay, PhonePe, Paytm)
2️⃣ Pay ₹{package['price']} to: `{UPI_ID}`
3️⃣ Add note: `Tokens_{user_id}`
4️⃣ Complete payment
5️⃣ Send screenshot here for verification

**⚡ Verification Time:** 1-24 hours
**🎯 User ID:** `{user_id}` (include in payment note)

Ready to pay? Use the UPI link below! 👇
"""
        
        keyboard = create_keyboard([
            [{'text': '📱 Pay with UPI', 'url': f'upi://pay?pa={UPI_ID}&am={package["price"]}&tn=Tokens_{user_id}'}],
            [{'text': '💬 Contact Support', 'url': f'tg://user?id={ADMIN_ID}'}, {'text': '🔙 Back to Store', 'callback_data': 'buy'}]
        ])
        
        bot.edit_message_text(payment_text, call.message.chat.id, call.message.message_id, reply_markup=keyboard)
        logger.info(f"Payment initiated: {user_id} - {package['tokens']} tokens - ₹{package['price']}")
        
    except Exception as e:
        logger.error(f"Buy callback error: {e}")

def handle_content_callback(call):
    try:
        deeplink = call.data.split('_')[1]
        user_id = call.from_user.id
        
        content = db.execute("SELECT * FROM content WHERE deeplink = ?", (deeplink,))
        if not content:
            bot.answer_callback_query(call.id, "❌ Content not found!", show_alert=True)
            return
        
        content_data = content[0]
        tokens_required = content_data[5]
        
        user = db.get_user(user_id)
        if user[3] < tokens_required:
            bot.answer_callback_query(call.id, f"❌ Need {tokens_required} tokens! You have {user[3]}", show_alert=True)
            return
        
        # Deduct tokens and send content
        db.update_tokens(user_id, -tokens_required)
        db.execute("UPDATE content SET views = views + 1 WHERE deeplink = ?", (deeplink,))
        
        # Send content based on type
        caption = f"🎯 **{content_data[1]}**\n\n{content_data[2]}\n\n💰 {tokens_required} tokens deducted\n✅ Enjoy your premium content!"
        
        if content_data[4] == 'photo':
            bot.send_photo(user_id, content_data[3], caption=caption)
        elif content_data[4] == 'video':
            bot.send_video(user_id, content_data[3], caption=caption)
        elif content_data[4] == 'document':
            bot.send_document(user_id, content_data[3], caption=caption)
        elif content_data[4] == 'audio':
            bot.send_audio(user_id, content_data[3], caption=caption)
        
        bot.answer_callback_query(call.id, f"✅ Content unlocked! {tokens_required} tokens used")
        logger.info(f"Content accessed: {user_id} - {deeplink} - {tokens_required} tokens")
        
    except Exception as e:
        logger.error(f"Content callback error: {e}")
        bot.answer_callback_query(call.id, "❌ Access failed!")

def handle_content_access(message):
    try:
        deeplink = message.text.split('_')[1]
        user_id = message.from_user.id
        
        content = db.execute("SELECT * FROM content WHERE deeplink = ?", (deeplink,))
        if not content:
            bot.reply_to(message, "❌ Content not found or expired!")
            return
        
        content_data = content[0]
        tokens_required = content_data[5]
        
        user = db.get_user(user_id)
        if not user:
            keyboard = create_keyboard([[{'text': '🚀 Register Now', 'callback_data': 'start_bot'}]])
            bot.reply_to(message, "❌ Please register first to access content!", reply_markup=keyboard)
            return
        
        preview_text = f"""
🎯 **Premium Content Preview**

**📁 Title:** {content_data[1]}
**📝 Description:** {content_data[2]}
**💰 Required Tokens:** {tokens_required}
**👁️ Views:** {content_data[7]:,}
**📊 File Type:** {content_data[4].title()}

**💳 Your Balance:** {user[3]} tokens

{'✅ You have enough tokens!' if user[3] >= tokens_required else f'❌ You need {tokens_required - user[3]} more tokens!'}
"""
        
        if user[3] >= tokens_required:
            keyboard = create_keyboard([
                [{'text': f'🔓 Unlock Content ({tokens_required} tokens)', 'callback_data': f'content_{deeplink}'}],
                [{'text': '💰 Check Balance', 'callback_data': 'balance'}]
            ])
        else:
            keyboard = create_keyboard([
                [{'text': '💳 Buy Tokens', 'callback_data': 'buy'}, {'text': '👥 Earn via Referrals', 'callback_data': 'referrals'}]
            ])
        
        bot.reply_to(message, preview_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Content access error: {e}")
        bot.reply_to(message, "❌ Error accessing content!")

# 📸 PAYMENT SCREENSHOT HANDLER

@bot.message_handler(content_types=['photo'])
@rate_limit
def handle_payment_screenshot(message):
    try:
        user_id = message.from_user.id
        
        pending = db.execute("SELECT * FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1", (user_id,))
        if not pending:
            bot.reply_to(message, "❌ No pending payments found! Use /buy to purchase tokens first.")
            return
        
        payment = pending[0]
        
        # Forward to admin
        admin_text = f"""
💳 **Payment Verification Required**

**👤 User Details:**
• Name: {message.from_user.first_name}
• Username: @{message.from_user.username or 'None'}
• User ID: `{user_id}`

**💰 Payment Details:**
• Payment ID: `{payment[0]}`
• Amount: ₹{payment[2]}
• Tokens: {payment[3]:,}
• Date: {payment[5]}

**🔧 Quick Actions:**
• Approve: `/verify {payment[0]}`
• Reject: `/reject {payment[0]} [reason]`

📸 **Screenshot attached below:**
"""
        
        try:
            bot.send_message(ADMIN_ID, admin_text)
            bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            
            confirmation_text = f"""
✅ **Payment Screenshot Received!**

**📋 Payment Details:**
• Payment ID: `{payment[0]}`
• Amount: ₹{payment[2]}
• Tokens: {payment[3]:,}
• Status: Pending Verification

**⏱️ What's Next:**
• Admin team will verify your payment
• You'll get instant notification once approved
• Tokens will be added automatically
• Verification usually takes 1-24 hours

**💬 Need Help?** Contact support if verification takes longer than expected.

Thank you for your patience! 🙏
"""
            
            keyboard = create_keyboard([
                [{'text': '💰 Check Balance', 'callback_data': 'balance'}, {'text': '💬 Contact Support', 'url': f'tg://user?id={ADMIN_ID}'}]
            ])
            
            bot.reply_to(message, confirmation_text, reply_markup=keyboard)
            logger.info(f"Payment screenshot received: {user_id} - Payment ID: {payment[0]}")
            
        except Exception as e:
            logger.error(f"Forward error: {e}")
            bot.reply_to(message, "❌ Error processing screenshot. Please contact admin directly.")
        
    except Exception as e:
        logger.error(f"Screenshot handler error: {e}")
        bot.reply_to(message, "❌ Error processing payment screenshot!")

# 💳 PAYMENT VERIFICATION COMMANDS

@bot.message_handler(commands=['verify'])
@admin_only
def verify_payment(message):
    try:
        args = message.text.split()
        if len(args) != 2:
            bot.reply_to(message, "Usage: `/verify <payment_id>`")
            return
        
        payment_id = int(args[1])
        payment = db.execute("SELECT * FROM payments WHERE id = ? AND status = 'pending'", (payment_id,))
        
        if not payment:
            bot.reply_to(message, "❌ Payment not found or already processed!")
            return
        
        payment_data = payment[0]
        user_id, amount, tokens = payment_data[1], payment_data[2], payment_data[3]
        
        # Update payment and add tokens
        db.execute("UPDATE payments SET status = 'verified', verified_at = CURRENT_TIMESTAMP WHERE id = ?", (payment_id,))
        db.update_tokens(user_id, tokens)
        
        # Notify user
        user_text = f"""
🎉 **Payment Verified Successfully!**

**💰 Payment Details:**
• Payment ID: `{payment_id}`
• Amount Paid: ₹{amount}
• Tokens Added: {tokens:,}

**✅ Your account has been updated!**
Use /balance to check your new balance.

Thank you for your purchase! 🚀
"""
        
        safe_send(user_id, user_text)
        
        bot.reply_to(message, f"""
✅ **Payment Verified!**

**📋 Details:**
• Payment ID: `{payment_id}`
• User ID: `{user_id}`
• Amount: ₹{amount}
• Tokens: {tokens:,}

**✅ Actions Completed:**
• Payment marked as verified
• {tokens:,} tokens added to user account
• User notification sent

**🕐 Verification Time:** {datetime.now().strftime('%d/%m/%Y %H:%M')}
""")
        
        logger.info(f"Payment verified: ID {payment_id} - User {user_id} - {tokens} tokens")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid payment ID!")
    except Exception as e:
        logger.error(f"Verify error: {e}")
        bot.reply_to(message, f"❌ Verification failed: {e}")

@bot.message_handler(commands=['reject'])
@admin_only
def reject_payment(message):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: `/reject <payment_id> [reason]`")
            return
        
        payment_id = int(args[1])
        reason = " ".join(args[2:]) if len(args) > 2 else "Payment verification failed"
        
        payment = db.execute("SELECT * FROM payments WHERE id = ? AND status = 'pending'", (payment_id,))
        if not payment:
            bot.reply_to(message, "❌ Payment not found or already processed!")
            return
        
        payment_data = payment[0]
        user_id = payment_data[1]
        
        # Update payment status
        db.execute("UPDATE payments SET status = 'rejected' WHERE id = ?", (payment_id,))
        
        # Notify user
        user_text = f"""
❌ **Payment Rejected**

**📋 Payment Details:**
• Payment ID: `{payment_id}`
• Rejection Reason: {reason}

**🔄 What you can do:**
• Check the reason above
• Ensure payment details are correct
• Contact support if you believe this is an error
• Try making a new payment with correct details

**💬 Need Help?** Contact our support team for assistance.
"""
        
        keyboard = create_keyboard([
            [{'text': '💳 Try Again', 'callback_data': 'buy'}, {'text': '💬 Contact Support', 'url': f'tg://user?id={ADMIN_ID}'}]
        ])
        
        safe_send(user_id, user_text, reply_markup=keyboard)
        
        bot.reply_to(message, f"""
❌ **Payment Rejected**

**📋 Details:**
• Payment ID: `{payment_id}`
• User ID: `{user_id}`
• Reason: {reason}

**✅ Actions Completed:**
• Payment marked as rejected
�� User notification sent with reason

**🕐 Rejection Time:** {datetime.now().strftime('%d/%m/%Y %H:%M')}
""")
        
        logger.info(f"Payment rejected: ID {payment_id} - User {user_id} - Reason: {reason}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid payment ID!")
    except Exception as e:
        logger.error(f"Reject error: {e}")
        bot.reply_to(message, f"❌ Rejection failed: {e}")

# 🔍 UNKNOWN MESSAGE HANDLER

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    try:
        help_text = """
❓ **Unknown Command**

**🚀 Available Commands:**
• `/start` - Register & get 10 FREE tokens
• `/balance` - Check your token wallet
• `/buy` - Purchase token packages
• `/refer` - Earn through referrals

**🔧 Admin Commands:**
• `/admin_stats` - Bot analytics
• `/admin_tokens` - Manage user tokens
• `/admin_upload` - Upload premium content

**💡 Quick Actions:**
"""
        
        keyboard = create_keyboard([
            [{'text': '🚀 Get Started', 'callback_data': 'start_bot'}, {'text': '💰 Check Balance', 'callback_data': 'balance'}],
            [{'text': '💳 Buy Tokens', 'callback_data': 'buy'}, {'text': '👥 Refer Friends', 'callback_data': 'referrals'}],
            [{'text': '💬 Contact Support', 'url': f'tg://user?id={ADMIN_ID}'}]
        ])
        
        bot.reply_to(message, help_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Unknown handler error: {e}")

# 🚀 MAIN FUNCTION

def main():
    try:
        logger.info("🚀 TokenBot starting...")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"💳 UPI ID: {UPI_ID}")
        
        # Test bot connection
        bot_info = bot.get_me()
        logger.info(f"🤖 Bot: @{bot_info.username} ({bot_info.first_name})")
        
        logger.info("✅ Bot started successfully! Ready to serve users...")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
        
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        time.sleep(5)
        main()

if __name__ == "__main__":
    main()
