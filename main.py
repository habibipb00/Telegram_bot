#!/usr/bin/env python3
"""
🚀 Professional Telegram Token Bot - COMPLETE VERSION
Features: Admin Upload, Auto Channel Posting, UPI Payments, Referrals
Author: Professional Bot Developer
"""

import os
import sys
import sqlite3
import logging
import time
import hashlib
import signal
from datetime import datetime
from functools import wraps
import telebot
from telebot import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ADMIN_ID = int(os.getenv('ADMIN_ID', 123456789))
UPI_ID = os.getenv('UPI_ID', 'your_upi@bank')
CHANNEL_ID = os.getenv('CHANNEL_ID', '@your_channel')
VIP_CHANNEL_USERNAME = os.getenv('VIP_CHANNEL_USERNAME', 'your_vip_channel')
VIP_CHANNEL_URL = f"https://t.me/{VIP_CHANNEL_USERNAME}" if VIP_CHANNEL_USERNAME != 'your_vip_channel' else "https://t.me/your_vip_channel"

# Initialize bot
try:
    bot = telebot.TeleBot(BOT_TOKEN, parse_mode='Markdown')
    logger = logging.getLogger(__name__)
except Exception as e:
    print(f"❌ Bot initialization failed: {e}")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)

# Global variables
user_last_action = {}
admin_upload_state = {}
RATE_LIMIT = 1
bot_running = True

# Signal handler for graceful shutdown
def signal_handler(signum, frame):
    global bot_running
    logger.info("🛑 Received shutdown signal. Stopping bot gracefully...")
    bot_running = False
    try:
        bot.stop_polling()
    except:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Database class
class TokenBotDB:
    def __init__(self):
        self.db_path = 'tokenbot.db'
        self.init_database()
        logger.info("🗄️ Database initialized successfully")
    
    def init_database(self):
        try:
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
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_banned INTEGER DEFAULT 0
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
            
            # Content table - Enhanced
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    description TEXT,
                    poster_file_id TEXT,
                    video_file_id TEXT,
                    file_type TEXT,
                    tokens_required INTEGER DEFAULT 10,
                    deeplink TEXT UNIQUE,
                    views INTEGER DEFAULT 0,
                    channel_message_id INTEGER,
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
            
            # Admin logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    action TEXT,
                    target_user_id INTEGER,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
    
    def execute(self, query, params=()):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(query, params)
            result = cursor.fetchall()
            conn.commit()
            conn.close()
            return result
        except Exception as e:
            logger.error(f"Database error: {e}")
            return []
    
    def get_user(self, user_id):
        try:
            result = self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Get user error: {e}")
            return None
    
    def create_user(self, user_id, username, first_name, referred_by=None):
        try:
            referral_code = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8].upper()
            
            self.execute(
                "INSERT OR REPLACE INTO users (user_id, username, first_name, referral_code, referred_by, tokens, total_earned) VALUES (?, ?, ?, ?, ?, 10, 10)",
                (user_id, username, first_name, referral_code, referred_by)
            )
            
            if referred_by:
                self.execute("UPDATE users SET tokens = tokens + 5, total_earned = total_earned + 5 WHERE user_id = ?", (referred_by,))
                self.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referred_by, user_id))
            
            return referral_code
        except Exception as e:
            logger.error(f"Create user error: {e}")
            return None
    
    def update_tokens(self, user_id, tokens):
        try:
            if tokens > 0:
                self.execute("UPDATE users SET tokens = tokens + ?, total_earned = total_earned + ? WHERE user_id = ?", (tokens, tokens, user_id))
            else:
                self.execute("UPDATE users SET tokens = tokens + ?, total_spent = total_spent + ? WHERE user_id = ?", (tokens, abs(tokens), user_id))
            return True
        except Exception as e:
            logger.error(f"Update tokens error: {e}")
            return False
    
    def get_user_by_referral(self, code):
        try:
            result = self.execute("SELECT * FROM users WHERE referral_code = ?", (code,))
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Get user by referral error: {e}")
            return None
    
    def log_admin_action(self, admin_id, action, target_user_id=None, details=""):
        try:
            self.execute("INSERT INTO admin_logs (admin_id, action, target_user_id, details) VALUES (?, ?, ?, ?)",
                        (admin_id, action, target_user_id, details))
        except Exception as e:
            logger.error(f"Admin log error: {e}")

# Initialize database
db = TokenBotDB()

# Decorators
def rate_limit(func):
    @wraps(func)
    def wrapper(message):
        try:
            user_id = message.from_user.id
            current_time = time.time()
            
            if user_id in user_last_action and current_time - user_last_action[user_id] < RATE_LIMIT:
                bot.reply_to(message, "⚡ Please wait a moment!")
                return
            
            user_last_action[user_id] = current_time
            return func(message)
        except Exception as e:
            logger.error(f"Rate limit error: {e}")
            return func(message)
    return wrapper

def admin_only(func):
    @wraps(func)
    def wrapper(message):
        try:
            if message.from_user.id != ADMIN_ID:
                bot.reply_to(message, "🚫 Admin access required!")
                return
            return func(message)
        except Exception as e:
            logger.error(f"Admin check error: {e}")
            bot.reply_to(message, "❌ Error occurred!")
    return wrapper

def registered_only(func):
    @wraps(func)
    def wrapper(message):
        try:
            user = db.get_user(message.from_user.id)
            if not user:
                start_command(message)
                return
            if user[10]:  # Check if banned
                bot.reply_to(message, "🚫 You are banned from using this bot!")
                return
            return func(message)
        except Exception as e:
            logger.error(f"Registration check error: {e}")
            bot.reply_to(message, "❌ Please use /start first!")
    return wrapper

# Safe message functions
def safe_send_message(chat_id, text, reply_markup=None, parse_mode=None):
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Send message error: {e}")
        try:
            return bot.send_message(chat_id, text, reply_markup=reply_markup)
        except:
            return None

def safe_edit_message(chat_id, message_id, text, reply_markup=None, parse_mode=None):
    try:
        return bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Edit message error: {e}")
        try:
            return bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)
        except:
            return None

# 🚀 USER COMMANDS

@bot.message_handler(commands=['start'])
@rate_limit
def start_command(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or ""
        first_name = message.from_user.first_name or "User"
        
        logger.info(f"Start command from: {first_name} ({user_id})")
        
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
            if user[10]:  # Check if banned
                bot.reply_to(message, "🚫 You are banned from using this bot!")
                return
                
            welcome_text = f"""🎉 *Welcome back, {first_name}!*

💰 *Current Balance:* {user[3]} tokens
📊 *Total Earned:* {user[6]} tokens

🌟 *VIP Channel:* @{VIP_CHANNEL_USERNAME}

*How This Bot Works:*
• 🎁 Get FREE tokens daily
• 💳 Buy token packages via UPI
• 🔓 Use tokens to unlock premium content
• 👥 Refer friends to earn more tokens
• 🎯 Access exclusive videos, courses & files

Ready to explore premium content? 🚀"""
        else:
            # Create new user
            ref_code = db.create_user(user_id, username, first_name, referred_by)
            if not ref_code:
                bot.reply_to(message, "❌ Registration failed. Please try again!")
                return
                
            welcome_text = f"""🎉 *Welcome to TokenBot, {first_name}!*

🎁 *Welcome Bonus:* 10 FREE tokens!
🔗 *Your Referral Code:* `{ref_code}`

*How This Bot Works:*
• 🎁 You get 10 FREE tokens to start
• 💳 Buy more tokens via UPI payments
• 🔓 Use tokens to unlock premium content
• 👥 Refer friends (+5 tokens each)
• 🎯 Access videos, courses, documents & more

🌟 *VIP Channel:* @{VIP_CHANNEL_USERNAME}
_Join for exclusive premium content!_

🚀 *Quick Start Guide:*"""
            
            if referred_by:
                welcome_text += "\n🎊 *Bonus:* Your referrer got 5 tokens!"
        
        # Create inline keyboard
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💰 My Wallet", callback_data="balance"),
            types.InlineKeyboardButton("💳 Buy Tokens", callback_data="buy")
        )
        keyboard.add(
            types.InlineKeyboardButton("👥 Earn Free", callback_data="referrals")
        )
        if VIP_CHANNEL_USERNAME != 'your_vip_channel':
            keyboard.add(
                types.InlineKeyboardButton("🌟 Join VIP Channel", url=VIP_CHANNEL_URL)
            )
        
        safe_send_message(message.chat.id, welcome_text, reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"✅ User started successfully: {first_name} ({user_id})")
        
    except Exception as e:
        logger.error(f"Start command error: {e}")
        bot.reply_to(message, "❌ Error occurred. Please try again!")

@bot.message_handler(commands=['balance'])
@rate_limit
@registered_only
def balance_command(message):
    try:
        user = db.get_user(message.from_user.id)
        if not user:
            bot.reply_to(message, "❌ Please use /start first!")
            return
            
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals and referrals[0] else 0
        
        balance_text = f"""💰 *Your Token Wallet*

💎 *Current Balance:* {user[3]} tokens
📈 *Total Earned:* {user[6]} tokens  
📉 *Total Spent:* {user[7]} tokens
👥 *Referrals Made:* {total_refs}

🔗 *Your Referral Code:* `{user[4]}`
📱 *Share Link:* 
`https://t.me/{bot.get_me().username}?start={user[4]}`

💡 *Share your link to earn 5 tokens per referral!*"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💳 Buy More", callback_data="buy"),
            types.InlineKeyboardButton("👥 Invite Friends", callback_data="referrals")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔄 Refresh", callback_data="balance")
        )
        
        safe_send_message(message.chat.id, balance_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Balance error: {e}")
        bot.reply_to(message, "❌ Error loading balance!")

@bot.message_handler(commands=['buy'])
@rate_limit
@registered_only
def buy_command(message):
    try:
        buy_text = f"""💳 *Token Store - Premium Packages*

🎯 *Special Offers:*
• 💎 *100 Tokens* - ₹10 _(₹0.10 each)_
• 🔥 *500 Tokens* - ₹45 _(₹0.09 each)_ *10% OFF*
• ⭐ *1000 Tokens* - ₹80 _(₹0.08 each)_ *20% OFF*
• 👑 *2000 Tokens* - ₹150 _(₹0.075 each)_ *25% OFF*

💰 *Payment Method:* UPI Only
🏦 *UPI ID:* `{UPI_ID}`

📋 *UPI Payment Steps:*
1️⃣ Select package below
2️⃣ Open any UPI app (GPay, PhonePe, Paytm)
3️⃣ Pay to UPI ID: `{UPI_ID}`
4️⃣ Add note: `Tokens_YourUserID`
5️⃣ Send payment screenshot here
6️⃣ Get tokens after verification!

⚡ *Verification time:* 1-24 hours
💡 *Always add your User ID in payment note*"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💎 100 - ₹10", callback_data="buy_100"),
            types.InlineKeyboardButton("🔥 500 - ₹45", callback_data="buy_500")
        )
        keyboard.add(
            types.InlineKeyboardButton("⭐ 1000 - ₹80", callback_data="buy_1000"),
            types.InlineKeyboardButton("👑 2000 - ₹150", callback_data="buy_2000")
        )
        keyboard.add(
            types.InlineKeyboardButton("💬 Support", url=f"tg://user?id={ADMIN_ID}")
        )
        
        safe_send_message(message.chat.id, buy_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Buy error: {e}")
        bot.reply_to(message, "❌ Error loading store!")

# 🔧 ADMIN COMMANDS

@bot.message_handler(commands=['admin'])
@admin_only
def admin_panel(message):
    try:
        stats = {
            'users': 0,
            'tokens_total': 0,
            'payments_total': 0,
            'payments_pending': 0,
            'revenue': 0,
            'content_total': 0,
            'banned_users': 0
        }
        
        try:
            users_result = db.execute("SELECT COUNT(*) FROM users")
            stats['users'] = users_result[0][0] if users_result and users_result[0] else 0
            
            tokens_result = db.execute("SELECT SUM(tokens) FROM users")
            stats['tokens_total'] = tokens_result[0][0] if tokens_result and tokens_result[0] and tokens_result[0][0] else 0
            
            payments_result = db.execute("SELECT COUNT(*) FROM payments")
            stats['payments_total'] = payments_result[0][0] if payments_result and payments_result[0] else 0
            
            pending_result = db.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
            stats['payments_pending'] = pending_result[0][0] if pending_result and pending_result[0] else 0
            
            revenue_result = db.execute("SELECT SUM(amount) FROM payments WHERE status = 'verified'")
            stats['revenue'] = revenue_result[0][0] if revenue_result and revenue_result[0] and revenue_result[0][0] else 0
            
            content_result = db.execute("SELECT COUNT(*) FROM content")
            stats['content_total'] = content_result[0][0] if content_result and content_result[0] else 0
            
            banned_result = db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
            stats['banned_users'] = banned_result[0][0] if banned_result and banned_result[0] else 0
            
        except Exception as e:
            logger.error(f"Stats query error: {e}")
        
        admin_text = f"""📊 *Admin Dashboard*

👥 *Users:* {stats['users']:,}
💰 *Total Tokens:* {stats['tokens_total']:,}
💳 *Payments:* {stats['payments_total']:,}
⏳ *Pending:* {stats['payments_pending']:,}
💵 *Revenue:* ₹{stats['revenue']:,.2f}
📁 *Content:* {stats['content_total']:,}
🚫 *Banned:* {stats['banned_users']:,}

🕐 *Updated:* {datetime.now().strftime('%d/%m/%Y %H:%M')}"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            types.InlineKeyboardButton("💳 Payments", callback_data="admin_payments")
        )
        keyboard.add(
            types.InlineKeyboardButton("📁 Content", callback_data="admin_content"),
            types.InlineKeyboardButton("📤 Upload", callback_data="admin_upload")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔨 Moderation", callback_data="admin_moderation"),
            types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh")
        )
        
        safe_send_message(message.chat.id, admin_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Admin panel error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['upload'])
@admin_only
def admin_upload_command(message):
    try:
        upload_text = """📤 *Content Upload System*

📋 *Upload Process:*
1️⃣ Send poster image first
2️⃣ Send video/document file
3️⃣ Add title and description
4️⃣ Set token requirement
5️⃣ Auto-post to channel with deeplink

✅ *Supported Files:*
• 📷 Poster: JPG, PNG images
• 🎥 Video: MP4, AVI, MOV files
• 📄 Documents: PDF, ZIP files

🚀 *Features:*
• Auto-generated deeplinks
• Channel posting with buttons
• View tracking & analytics
• Token-based access control

Ready to upload? Send poster image first! 📤"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("📊 Content Stats", callback_data="admin_content"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="admin_refresh")
        )
        
        bot.reply_to(message, upload_text, reply_markup=keyboard, parse_mode='Markdown')
        
        # Set upload state
        admin_upload_state[ADMIN_ID] = {'step': 'waiting_poster'}
        
    except Exception as e:
        logger.error(f"Admin upload command error: {e}")
        bot.reply_to(message, "❌ Upload initialization failed!")

@bot.message_handler(commands=['add_tokens'])
@admin_only
def add_tokens_command(message):
    try:
        args = message.text.split()
        if len(args) != 3:
            bot.reply_to(message, "Usage: `/add_tokens <user_id> <amount>`")
            return
        
        user_id, amount = int(args[1]), int(args[2])
        user = db.get_user(user_id)
        
        if not user:
            bot.reply_to(message, f"❌ User {user_id} not found!")
            return
        
        success = db.update_tokens(user_id, amount)
        if not success:
            bot.reply_to(message, "❌ Failed to update tokens!")
            return
            
        new_balance = user[3] + amount
        db.log_admin_action(ADMIN_ID, "ADD_TOKENS", user_id, f"Added {amount} tokens")
        
        # Notify user
        try:
            safe_send_message(user_id, f"""🎉 *Token Bonus!*

💰 *Added:* {amount} tokens
💎 *New Balance:* {new_balance} tokens

Enjoy! 🚀""", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"User notification error: {e}")
        
        bot.reply_to(message, f"""✅ *Success!*

👤 User: {user[2]} (`{user_id}`)
💰 Added: {amount} tokens
💎 New Balance: {new_balance} tokens""", parse_mode='Markdown')
        
        logger.info(f"Admin added {amount} tokens to user {user_id}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID or amount!")
    except Exception as e:
        logger.error(f"Add tokens error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

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
        success = db.update_tokens(user_id, tokens)
        
        if not success:
            bot.reply_to(message, "❌ Failed to add tokens!")
            return
        
        db.log_admin_action(ADMIN_ID, "VERIFY_PAYMENT", user_id, f"Verified payment {payment_id} - {tokens} tokens")
        
        # Notify user
        try:
            safe_send_message(user_id, f"""🎉 *Payment Verified!*

*💰 Details:*
• Payment ID: `{payment_id}`
• Amount: ₹{amount}
• Tokens Added: {tokens:,}

*✅ Your account updated!*
Use /balance to check new balance.

Thank you! 🚀""", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"User notification error: {e}")
        
        bot.reply_to(message, f"""✅ *Payment Verified!*

• Payment ID: `{payment_id}`
• User ID: `{user_id}`
• Amount: ₹{amount}
• Tokens: {tokens:,}

User notified successfully! ✅""", parse_mode='Markdown')
        
        logger.info(f"Payment verified: ID {payment_id} - User {user_id} - {tokens} tokens")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid payment ID!")
    except Exception as e:
        logger.error(f"Verify error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['ban'])
@admin_only
def ban_user_command(message):
    try:
        args = message.text.split()
        if len(args) != 2:
            bot.reply_to(message, "Usage: `/ban <user_id>`")
            return
        
        user_id = int(args[1])
        user = db.get_user(user_id)
        
        if not user:
            bot.reply_to(message, f"❌ User {user_id} not found!")
            return
        
        if user[10]:  # Already banned
            bot.reply_to(message, f"❌ User {user_id} is already banned!")
            return
        
        # Ban user
        db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        db.log_admin_action(ADMIN_ID, "BAN_USER", user_id, f"Banned user {user[2]}")
        
        # Notify user
        try:
            safe_send_message(user_id, "🚫 *You have been banned from using this bot!*\n\nContact admin if you think this is a mistake.", parse_mode='Markdown')
        except:
            pass
        
        bot.reply_to(message, f"✅ *User Banned!*\n\n👤 User: {user[2]} (`{user_id}`)\n🚫 Status: Banned", parse_mode='Markdown')
        logger.info(f"Admin banned user: {user_id}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        logger.error(f"Ban user error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['broadcast'])
@admin_only
def broadcast_command(message):
    try:
        if len(message.text.split(' ', 1)) < 2:
            bot.reply_to(message, "Usage: `/broadcast <message>`")
            return
        
        broadcast_text = message.text.split(' ', 1)[1]
        
        # Get all users
        users = db.execute("SELECT user_id, first_name FROM users WHERE is_banned = 0")
        
        if not users:
            bot.reply_to(message, "❌ No users found!")
            return
        
        success_count = 0
        failed_count = 0
        
        bot.reply_to(message, f"📢 *Broadcasting to {len(users)} users...*", parse_mode='Markdown')
        
        for user in users:
            try:
                safe_send_message(user[0], f"📢 *Broadcast Message*\n\n{broadcast_text}", parse_mode='Markdown')
                success_count += 1
                time.sleep(0.1)  # Rate limiting
            except:
                failed_count += 1
        
        db.log_admin_action(ADMIN_ID, "BROADCAST", None, f"Sent to {success_count} users")
        
        bot.reply_to(message, f"""✅ *Broadcast Complete!*

📤 *Sent:* {success_count} users
❌ *Failed:* {failed_count} users
📊 *Total:* {len(users)} users""", parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

# 📤 ADMIN UPLOAD HANDLERS

@bot.message_handler(content_types=['photo', 'video', 'document'])
def handle_admin_upload(message):
    try:
        if message.from_user.id != ADMIN_ID:
            return
        
        if ADMIN_ID not in admin_upload_state:
            return
        
        state = admin_upload_state[ADMIN_ID]
        
        if state['step'] == 'waiting_poster' and message.content_type == 'photo':
            # Store poster
            state['poster_file_id'] = message.photo[-1].file_id
            state['step'] = 'waiting_video'
            
            bot.reply_to(message, """✅ *Poster received!*

📹 *Next:* Send the video file

📝 *Note:* Video will be the main content that users unlock with tokens.""", parse_mode='Markdown')
            
        elif state['step'] == 'waiting_video' and message.content_type in ['video', 'document']:
            # Store video
            if message.content_type == 'video':
                state['video_file_id'] = message.video.file_id
                state['file_type'] = 'video'
            else:
                state['video_file_id'] = message.document.file_id
                state['file_type'] = 'document'
            
            state['step'] = 'waiting_details'
            
            bot.reply_to(message, """✅ *Video received!*

📝 *Next:* Send content details in this format:
`Title | Description | Tokens Required`

*Example:*
`Premium Course | Advanced Python Tutorial | 50`""", parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Admin upload handler error: {e}")

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and ADMIN_ID in admin_upload_state and admin_upload_state[ADMIN_ID]['step'] == 'waiting_details')
def handle_upload_details(message):
    try:
        if '|' not in message.text:
            bot.reply_to(message, "❌ Invalid format! Use: `Title | Description | Tokens Required`")
            return
        
        parts = [p.strip() for p in message.text.split('|')]
        if len(parts) != 3:
            bot.reply_to(message, "❌ Invalid format! Use: `Title | Description | Tokens Required`")
            return
        
        title, description, tokens_str = parts
        tokens_required = int(tokens_str)
        
        state = admin_upload_state[ADMIN_ID]
        
        # Generate deeplink
        deeplink = hashlib.md5(f"{state['video_file_id']}{time.time()}".encode()).hexdigest()[:12]
        
        # Save to database
        db.execute(
            "INSERT INTO content (title, description, poster_file_id, video_file_id, file_type, tokens_required, deeplink) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, description, state['poster_file_id'], state['video_file_id'], state['file_type'], tokens_required, deeplink)
        )
        
        # Post to channel
        channel_message_id = post_to_channel(title, description, state['poster_file_id'], deeplink, tokens_required)
        
        if channel_message_id:
            db.execute("UPDATE content SET channel_message_id = ? WHERE deeplink = ?", (channel_message_id, deeplink))
        
        access_link = f"https://t.me/{bot.get_me().username}?start=content_{deeplink}"
        
        success_text = f"""✅ *Content Uploaded Successfully!*

*📁 Details:*
• *Title:* {title}
• *Description:* {description}
• *Tokens Required:* {tokens_required}
• *File Type:* {state['file_type'].title()}
• *Deeplink ID:* `{deeplink}`

*🔗 Access Link:*
`{access_link}`

*📢 Channel Status:* {'✅ Posted' if channel_message_id else '❌ Failed to post'}
*📊 Status:* Active & Ready for Users!
*📅 Upload Time:* {datetime.now().strftime('%d/%m/%Y %H:%M')}

Content is now live and accessible! 🚀"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("👁️ Preview", callback_data=f"preview_{deeplink}"),
            types.InlineKeyboardButton("📊 Stats", callback_data="admin_content")
        )
        keyboard.add(
            types.InlineKeyboardButton("📤 Upload More", callback_data="admin_upload"),
            types.InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_refresh")
        )
        
        bot.reply_to(message, success_text, reply_markup=keyboard, parse_mode='Markdown')
        
        # Clear upload state
        del admin_upload_state[ADMIN_ID]
        
        db.log_admin_action(ADMIN_ID, "UPLOAD_CONTENT", None, f"Uploaded: {title} - {tokens_required} tokens")
        logger.info(f"Content uploaded: {title} ({deeplink}) - {tokens_required} tokens")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid token amount! Use a number.")
    except Exception as e:
        logger.error(f"Upload details handler error: {e}")
        bot.reply_to(message, f"❌ Upload failed: {e}")

def post_to_channel(title, description, poster_file_id, deeplink, tokens_required):
    try:
        if not CHANNEL_ID or CHANNEL_ID == '@your_channel':
            logger.warning("Channel ID not configured")
            return None
        
        bot_username = bot.get_me().username
        access_link = f"https://t.me/{bot_username}?start=content_{deeplink}"
        
        caption = f"""🎯 *{title}*

📝 *Description:* {description}

💰 *Required Tokens:* {tokens_required}
🔓 *Access:* Click button below

🌟 *Join VIP Channel:* @{VIP_CHANNEL_USERNAME}

#premium #content #tokens"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(f"🔓 Unlock Content ({tokens_required} tokens)", url=access_link)
        )
        keyboard.add(
            types.InlineKeyboardButton("🤖 Start Bot", url=f"https://t.me/{bot_username}")
        )
        if VIP_CHANNEL_USERNAME != 'your_vip_channel':
            keyboard.add(
                types.InlineKeyboardButton("🌟 VIP Channel", url=VIP_CHANNEL_URL)
            )
        
        message = bot.send_photo(CHANNEL_ID, poster_file_id, caption=caption, reply_markup=keyboard, parse_mode='Markdown')
        return message.message_id
        
    except Exception as e:
        logger.error(f"Channel posting error: {e}")
        return None

# 🎯 CALLBACK HANDLERS

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data
        user_id = call.from_user.id
        
        # Always answer callback query first
        bot.answer_callback_query(call.id)
        
        # Route to appropriate handler
        if data == 'balance':
            handle_balance_callback(call)
        elif data == 'buy':
            handle_buy_menu_callback(call)
        elif data.startswith('buy_'):
            handle_buy_callback(call)
        elif data == 'referrals':
            handle_referrals_callback(call)
        elif data.startswith('content_'):
            handle_content_callback(call)
        elif data.startswith('admin_'):
            handle_admin_callback(call)
        else:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❓ Unknown action!")
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Error occurred!")
        except:
            pass

def handle_balance_callback(call):
    try:
        user = db.get_user(call.from_user.id)
        if not user:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❌ Please register first! Use /start")
            return
            
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals and referrals[0] else 0
        
        balance_text = f"""💰 *Your Token Wallet*

💎 *Current Balance:* {user[3]} tokens
📈 *Total Earned:* {user[6]} tokens  
📉 *Total Spent:* {user[7]} tokens
👥 *Referrals Made:* {total_refs}

🔗 *Referral Code:* `{user[4]}`
📱 *Share Link:* 
`https://t.me/{bot.get_me().username}?start={user[4]}`"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💳 Buy More", callback_data="buy"),
            types.InlineKeyboardButton("👥 Invite", callback_data="referrals")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔄 Refresh", callback_data="balance")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, balance_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Balance callback error: {e}")

def handle_buy_menu_callback(call):
    try:
        buy_text = f"""💳 *Token Store - Premium Packages*

🎯 *Special Offers:*
• 💎 *100 Tokens* - ₹10 _(₹0.10 each)_
• 🔥 *500 Tokens* - ₹45 _(₹0.09 each)_ *10% OFF*
• ⭐ *1000 Tokens* - ₹80 _(₹0.08 each)_ *20% OFF*
• 👑 *2000 Tokens* - ₹150 _(₹0.075 each)_ *25% OFF*

💰 *Payment:* UPI Only
🏦 *UPI ID:* `{UPI_ID}`

📋 *Quick UPI Steps:*
1. Select package → 2. Pay via UPI → 3. Send screenshot

Select package below:"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💎 100 - ₹10", callback_data="buy_100"),
            types.InlineKeyboardButton("🔥 500 - ₹45", callback_data="buy_500")
        )
        keyboard.add(
            types.InlineKeyboardButton("⭐ 1000 - ₹80", callback_data="buy_1000"),
            types.InlineKeyboardButton("👑 2000 - ₹150", callback_data="buy_2000")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="balance")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, buy_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Buy menu callback error: {e}")

def handle_buy_callback(call):
    try:
        packages = {
            'buy_100': {'tokens': 100, 'price': 10},
            'buy_500': {'tokens': 500, 'price': 45},
            'buy_1000': {'tokens': 1000, 'price': 80},
            'buy_2000': {'tokens': 2000, 'price': 150}
        }
        
        if call.data not in packages:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❌ Invalid package!")
            return
            
        package = packages[call.data]
        user_id = call.from_user.id
        
        # Create payment record
        db.execute("INSERT INTO payments (user_id, amount, tokens) VALUES (?, ?, ?)", 
                  (user_id, package['price'], package['tokens']))
        
        payment_text = f"""💳 *UPI Payment Instructions*

*📦 Package:* {package['tokens']} Tokens
*💰 Amount:* ₹{package['price']}
*🏦 UPI ID:* `{UPI_ID}`

*📋 Step-by-Step Process:*
1️⃣ Open any UPI app (GPay, PhonePe, Paytm)
2️⃣ Pay ₹{package['price']} to: `{UPI_ID}`
3️⃣ *Important:* Add note: `Tokens_{user_id}`
4️⃣ Complete payment
5️⃣ Send screenshot here for verification

*⚡ Verification:* 1-24 hours
*🎯 Your User ID:* `{user_id}` (must include in payment note)

*💡 Pro Tip:* Adding correct User ID speeds up verification!"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("💬 Support", url=f"tg://user?id={ADMIN_ID}"),
            types.InlineKeyboardButton("🔙 Back", callback_data="buy")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, payment_text, reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"Payment initiated: {user_id} - {package['tokens']} tokens - ₹{package['price']}")
        
    except Exception as e:
        logger.error(f"Buy callback error: {e}")

def handle_referrals_callback(call):
    try:
        user = db.get_user(call.from_user.id)
        if not user:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❌ Please register first!")
            return
            
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals and referrals[0] else 0
        
        bot_username = bot.get_me().username
        
        refer_text = f"""👥 *Referral Program*

*🎯 Your Stats:*
• 🔗 *Code:* `{user[4]}`
• 👥 *Referrals:* {total_refs}
• 💰 *Earned:* {total_refs * 5} tokens

*📱 Your Link:*
`https://t.me/{bot_username}?start={user[4]}`

*💡 How it works:*
• Share your link
• Friends join using it
• You get 5 tokens each
• No limits!"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("📱 Share Link", 
                url=f"https://t.me/share/url?url=https://t.me/{bot_username}?start={user[4]}&text=🚀 Join and get FREE tokens!")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="balance")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, refer_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Referrals callback error: {e}")

def handle_admin_callback(call):
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "🚫 Admin only!")
            return
            
        data = call.data
        
        if data == 'admin_refresh':
            handle_admin_refresh(call)
        elif data == 'admin_upload':
            handle_admin_upload_callback(call)
        elif data == 'admin_content':
            handle_admin_content_callback(call)
        elif data == 'admin_payments':
            handle_admin_payments_callback(call)
        elif data == 'admin_users':
            handle_admin_users_callback(call)
        elif data == 'admin_moderation':
            handle_admin_moderation_callback(call)
        
    except Exception as e:
        logger.error(f"Admin callback error: {e}")

def handle_admin_refresh(call):
    try:
        # Same as admin_panel but for callback
        stats = {
            'users': 0,
            'tokens_total': 0,
            'payments_total': 0,
            'payments_pending': 0,
            'revenue': 0,
            'content_total': 0,
            'banned_users': 0
        }
        
        try:
            users_result = db.execute("SELECT COUNT(*) FROM users")
            stats['users'] = users_result[0][0] if users_result and users_result[0] else 0
            
            tokens_result = db.execute("SELECT SUM(tokens) FROM users")
            stats['tokens_total'] = tokens_result[0][0] if tokens_result and tokens_result[0] and tokens_result[0][0] else 0
            
            payments_result = db.execute("SELECT COUNT(*) FROM payments")
            stats['payments_total'] = payments_result[0][0] if payments_result and payments_result[0] else 0
            
            pending_result = db.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
            stats['payments_pending'] = pending_result[0][0] if pending_result and pending_result[0] else 0
            
            revenue_result = db.execute("SELECT SUM(amount) FROM payments WHERE status = 'verified'")
            stats['revenue'] = revenue_result[0][0] if revenue_result and revenue_result[0] and revenue_result[0][0] else 0
            
            content_result = db.execute("SELECT COUNT(*) FROM content")
            stats['content_total'] = content_result[0][0] if content_result and content_result[0] else 0
            
            banned_result = db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
            stats['banned_users'] = banned_result[0][0] if banned_result and banned_result[0] else 0
            
        except Exception as e:
            logger.error(f"Stats query error: {e}")
        
        admin_text = f"""📊 *Admin Dashboard*

👥 *Users:* {stats['users']:,}
💰 *Total Tokens:* {stats['tokens_total']:,}
💳 *Payments:* {stats['payments_total']:,}
⏳ *Pending:* {stats['payments_pending']:,}
💵 *Revenue:* ₹{stats['revenue']:,.2f}
📁 *Content:* {stats['content_total']:,}
🚫 *Banned:* {stats['banned_users']:,}

🕐 *Updated:* {datetime.now().strftime('%d/%m/%Y %H:%M')}"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            types.InlineKeyboardButton("💳 Payments", callback_data="admin_payments")
        )
        keyboard.add(
            types.InlineKeyboardButton("📁 Content", callback_data="admin_content"),
            types.InlineKeyboardButton("📤 Upload", callback_data="admin_upload")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔨 Moderation", callback_data="admin_moderation"),
            types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, admin_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Admin refresh error: {e}")

def handle_admin_upload_callback(call):
    try:
        upload_text = """📤 *Content Upload System*

*📋 Upload Process:*
1️⃣ Send poster image first
2️⃣ Send video/document file
3️⃣ Add title and description
4️⃣ Set token requirement
5️⃣ Auto-post to channel with deeplink

*✅ Supported Files:*
• 📷 Poster: JPG, PNG images
• 🎥 Video: MP4, AVI, MOV files
• 📄 Documents: PDF, ZIP files

*🚀 Features:*
• Auto-generated deeplinks
• Channel posting with buttons
• View tracking & analytics
• Token-based access control

Ready to upload? Send poster image first! 📤"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("📊 Content Stats", callback_data="admin_content"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, upload_text, reply_markup=keyboard, parse_mode='Markdown')
        
        # Set upload state
        admin_upload_state[ADMIN_ID] = {'step': 'waiting_poster'}
        
    except Exception as e:
        logger.error(f"Admin upload callback error: {e}")

def handle_admin_content_callback(call):
    try:
        content_count_result = db.execute("SELECT COUNT(*) FROM content")
        content_count = content_count_result[0][0] if content_count_result and content_count_result[0] else 0
        
        total_views_result = db.execute("SELECT SUM(views) FROM content")
        total_views = total_views_result[0][0] if total_views_result and total_views_result[0] and total_views_result[0][0] else 0
        
        content_text = f"""📁 *Content Management*

*📊 Statistics:*
• Total Content: {content_count}
• Total Views: {total_views:,}

*🔧 Management:*
• Use `/upload` to add content
• Content gets auto-generated access links
• Token-based access control
• Auto-posting to channel

*📋 Recent Content:*"""
        
        recent_content = db.execute("""
            SELECT title, tokens_required, views, created_at 
            FROM content 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        
        if recent_content:
            for content in recent_content:
                title, tokens, views, date = content
                date = date[:10] if date else "Unknown"
                content_text += f"\n• {title} - {tokens} tokens - {views} views - {date}"
        else:
            content_text += "\n• No content uploaded yet"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("📤 Upload New", callback_data="admin_upload"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, content_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Admin content callback error: {e}")

def handle_admin_payments_callback(call):
    try:
        pending_payments = db.execute("""
            SELECT p.id, p.user_id, u.first_name, p.amount, p.tokens, p.created_at
            FROM payments p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at DESC
            LIMIT 10
        """)
        
        payments_text = "💳 *Pending Payments*\n\n"
        
        if pending_payments:
            for payment in pending_payments:
                pid, uid, name, amount, tokens, date = payment
                name = name or "User"
                date = date[:16] if date else "Unknown"
                payments_text += f"• ID: `{pid}` - {name} (`{uid}`)\n  ₹{amount} for {tokens} tokens - {date}\n\n"
            
            payments_text += "*Commands:*\n• `/verify <payment_id>` - Approve\n• `/reject <payment_id>` - Reject"
        else:
            payments_text += "✅ No pending payments!"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, payments_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Admin payments callback error: {e}")

def handle_admin_users_callback(call):
    try:
        recent_users = db.execute("""
            SELECT user_id, first_name, tokens, join_date, is_banned 
            FROM users 
            ORDER BY join_date DESC 
            LIMIT 10
        """)
        
        users_text = "👥 *Recent Users (Last 10)*\n\n"
        
        if recent_users:
            for user in recent_users:
                user_id, name, tokens, join_date, is_banned = user
                name = name or "User"
                date = join_date[:10] if join_date else "Unknown"
                status = "🚫 Banned" if is_banned else "✅ Active"
                users_text += f"• {name} (`{user_id}`) - {tokens} tokens - {date} - {status}\n"
        else:
            users_text += "• No users found"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, users_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Admin users callback error: {e}")

def handle_admin_moderation_callback(call):
    try:
        banned_users = db.execute("""
            SELECT user_id, first_name, join_date 
            FROM users 
            WHERE is_banned = 1 
            ORDER BY join_date DESC 
            LIMIT 10
        """)
        
        moderation_text = """🔨 *Moderation Panel*

*🔧 Available Commands:*
• `/ban <user_id>` - Ban user
• `/unban <user_id>` - Unban user
• `/broadcast <message>` - Send message to all users

*🚫 Banned Users:*"""
        
        if banned_users:
            for user in banned_users:
                user_id, name, join_date = user
                name = name or "User"
                date = join_date[:10] if join_date else "Unknown"
                moderation_text += f"\n• {name} (`{user_id}`) - Banned on {date}"
        else:
            moderation_text += "\n• No banned users"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, moderation_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Admin moderation callback error: {e}")

def handle_content_callback(call):
    try:
        deeplink = call.data.split('_')[1]
        user_id = call.from_user.id
        
        content = db.execute("SELECT * FROM content WHERE deeplink = ?", (deeplink,))
        if not content:
            bot.answer_callback_query(call.id, "❌ Content not found!", show_alert=True)
            return
        
        content_data = content[0]
        tokens_required = content_data[6]
        
        user = db.get_user(user_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ Please register first!", show_alert=True)
            return
            
        if user[10]:  # Check if banned
            bot.answer_callback_query(call.id, "🚫 You are banned!", show_alert=True)
            return
            
        if user[  "🚫 You are banned!", show_alert=True)
            return
            
        if user[3] < tokens_required:
            bot.answer_callback_query(call.id, f"❌ Need {tokens_required} tokens! You have {user[3]}", show_alert=True)
            return
        
        # Deduct tokens and send content
        success = db.update_tokens(user_id, -tokens_required)
        if not success:
            bot.answer_callback_query(call.id, "❌ Error processing tokens!", show_alert=True)
            return
            
        db.execute("UPDATE content SET views = views + 1 WHERE deeplink = ?", (deeplink,))
        
        # Send poster first
        try:
            poster_caption = f"""🎯 *{content_data[1]}*

📝 *Description:* {content_data[2]}

💰 {tokens_required} tokens used
✅ Enjoy your premium content!

🌟 *Join VIP Channel:* @{VIP_CHANNEL_USERNAME}"""
            
            bot.send_photo(user_id, content_data[3], caption=poster_caption, parse_mode='Markdown')
            
            # Send main content
            if content_data[5] == 'video':
                bot.send_video(user_id, content_data[4], caption="🎥 *Main Content*", parse_mode='Markdown')
            elif content_data[5] == 'document':
                bot.send_document(user_id, content_data[4], caption="📄 *Main Content*", parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Content send error: {e}")
            # Refund tokens if content send fails
            db.update_tokens(user_id, tokens_required)
            bot.send_message(user_id, "❌ Error sending content. Tokens refunded. Contact admin.")
            return
        
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
        tokens_required = content_data[6]
        
        user = db.get_user(user_id)
        if not user:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("🚀 Register Now", callback_data="start_bot"))
            bot.reply_to(message, "❌ Please register first!", reply_markup=keyboard)
            return
        
        if user[10]:  # Check if banned
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        preview_text = f"""🎯 *Premium Content Preview*

*📁 Title:* {content_data[1]}
*📝 Description:* {content_data[2]}
*💰 Required:* {tokens_required} tokens
*👁️ Views:* {content_data[8]:,}
*📊 Type:* {content_data[5].title()}

*💳 Your Balance:* {user[3]} tokens

{'✅ You have enough tokens!' if user[3] >= tokens_required else f'❌ Need {tokens_required - user[3]} more tokens!'}

*🌟 VIP Channel:* @{VIP_CHANNEL_USERNAME}
_Join for exclusive premium content!_"""
        
        keyboard = types.InlineKeyboardMarkup()
        if user[3] >= tokens_required:
            keyboard.add(
                types.InlineKeyboardButton(f"🔓 Unlock ({tokens_required} tokens)", callback_data=f"content_{deeplink}")
            )
        else:
            keyboard.add(
                types.InlineKeyboardButton("💳 Buy Tokens", callback_data="buy"),
                types.InlineKeyboardButton("👥 Earn Free", callback_data="referrals")
            )
        
        keyboard.add(
            types.InlineKeyboardButton("💰 Check Balance", callback_data="balance")
        )
        if VIP_CHANNEL_USERNAME != 'your_vip_channel':
            keyboard.add(
                types.InlineKeyboardButton("🌟 Join VIP", url=VIP_CHANNEL_URL)
            )
        
        safe_send_message(message.chat.id, preview_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Content access error: {e}")
        bot.reply_to(message, "❌ Error accessing content!")

# 📸 PAYMENT SCREENSHOT HANDLER

@bot.message_handler(content_types=['photo'])
@rate_limit
def handle_payment_screenshot(message):
    try:
        user_id = message.from_user.id
        
        # Check if user is registered
        user = db.get_user(user_id)
        if not user:
            bot.reply_to(message, "❌ Please register first using /start")
            return
        
        if user[10]:  # Check if banned
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        pending = db.execute("SELECT * FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1", (user_id,))
        if not pending:
            bot.reply_to(message, "❌ No pending payments! Use /buy first.")
            return
        
        payment = pending[0]
        
        # Forward to admin with better formatting
        admin_text = f"""💳 *Payment Screenshot Received*

*👤 User:* {message.from_user.first_name or 'User'}
*🆔 Username:* @{message.from_user.username or 'None'}
*🔢 User ID:* `{user_id}`

*💰 Payment Details:*
• *Payment ID:* `{payment[0]}`
• *Amount:* ₹{payment[2]}
• *Tokens:* {payment[3]:,}
• *Date:* {payment[5][:16] if payment[5] else 'Unknown'}

*🔧 Quick Actions:*
• Approve: `/verify {payment[0]}`

*💡 UPI Payment Note Should Include:* `Tokens_{user_id}`

Screenshot attached below ⬇️"""
        
        try:
            safe_send_message(ADMIN_ID, admin_text, parse_mode='Markdown')
            bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            
            confirmation_text = f"""✅ *Payment Screenshot Received!*

*📋 Details:*
• Payment ID: `{payment[0]}`
• Amount: ₹{payment[2]}
• Tokens: {payment[3]:,}
• Status: ⏳ Pending Verification

*⏱️ What's Next:*
• Admin will verify your payment
• You'll get instant notification
• Tokens added automatically
• Usually takes 1-24 hours

*💡 Pro Tip:* Make sure you added `Tokens_{user_id}` in payment note for faster processing!

Thank you for your patience! 🙏"""
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("💰 Check Balance", callback_data="balance"),
                types.InlineKeyboardButton("💬 Support", url=f"tg://user?id={ADMIN_ID}")
            )
            
            safe_send_message(message.chat.id, confirmation_text, reply_markup=keyboard, parse_mode='Markdown')
            logger.info(f"Payment screenshot: {user_id} - Payment ID: {payment[0]}")
            
        except Exception as e:
            logger.error(f"Forward error: {e}")
            bot.reply_to(message, "❌ Error processing screenshot. Contact admin directly.")
        
    except Exception as e:
        logger.error(f"Screenshot handler error: {e}")
        bot.reply_to(message, "❌ Error processing screenshot!")

# 🔍 UNKNOWN MESSAGE HANDLER

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    try:
        # Check if admin is in upload state
        if message.from_user.id == ADMIN_ID and ADMIN_ID in admin_upload_state:
            return  # Let upload handler deal with it
            
        help_text = f"""❓ *Unknown Command*

*🚀 Available Commands:*
• `/start` - Register & get 10 FREE tokens
• `/balance` - Check token wallet
• `/buy` - Purchase tokens

*🔧 Admin Commands:*
• `/admin` - Admin dashboard
• `/upload` - Upload content system
• `/add_tokens <user_id> <amount>` - Add tokens
• `/ban <user_id>` - Ban user
• `/broadcast <message>` - Send to all users
• `/verify <payment_id>` - Verify payment

*💡 UPI Payment Info:*
• UPI ID: `{UPI_ID}`
• Add note: `Tokens_YourUserID`
• Send screenshot for verification

*🌟 VIP Channel:* @{VIP_CHANNEL_USERNAME}

*💡 Quick Actions:*"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("🚀 Start", callback_data="balance"),
            types.InlineKeyboardButton("💰 Balance", callback_data="balance")
        )
        keyboard.add(
            types.InlineKeyboardButton("💳 Buy", callback_data="buy"),
            types.InlineKeyboardButton("👥 Refer", callback_data="referrals")
        )
        keyboard.add(
            types.InlineKeyboardButton("💬 Support", url=f"tg://user?id={ADMIN_ID}")
        )
        if VIP_CHANNEL_USERNAME != 'your_vip_channel':
            keyboard.add(
                types.InlineKeyboardButton("🌟 VIP Channel", url=VIP_CHANNEL_URL)
            )
        
        safe_send_message(message.chat.id, help_text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Unknown handler error: {e}")

# 🚀 MAIN FUNCTION

def main():
    global bot_running
    
    try:
        logger.info("🚀 Enhanced TokenBot Starting...")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"💳 UPI ID: {UPI_ID}")
        logger.info(f"📢 Channel ID: {CHANNEL_ID}")
        logger.info(f"🌟 VIP Channel: @{VIP_CHANNEL_USERNAME}")
        logger.info(f"🔗 VIP Channel URL: {VIP_CHANNEL_URL}")
        
        # Test bot connection
        try:
            bot_info = bot.get_me()
            logger.info(f"🤖 Bot Connected: @{bot_info.username} ({bot_info.first_name})")
        except Exception as e:
            logger.error(f"❌ Bot connection failed: {e}")
            return False
        
        # Test database
        try:
            test_query = db.execute("SELECT COUNT(*) FROM users")
            logger.info("✅ Database connection successful")
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            return False
        
        logger.info("✅ All systems ready!")
        logger.info("🚀 Bot started successfully - Listening for messages...")
        logger.info("📤 Admin Upload System: ACTIVE")
        logger.info("💳 UPI Payment System: ACTIVE")
        logger.info("👥 Referral System: ACTIVE")
        logger.info("🔗 Auto Channel Posting: ACTIVE")
        
        # Start polling with better error handling
        while bot_running:
            try:
                bot.infinity_polling(
                    timeout=10, 
                    long_polling_timeout=5,
                    none_stop=True,
                    interval=1
                )
            except Exception as e:
                if bot_running:
                    logger.error(f"Polling error: {e}")
                    logger.info("Restarting polling in 5 seconds...")
                    time.sleep(5)
                else:
                    break
        
        return True
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
        return True
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        return False

if __name__ == "__main__":
    try:
        success = main()
        if not success:
            logger.error("❌ Bot failed to start properly")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")
        sys.exit(1)
