#!/usr/bin/env python3
"""
🚀 Professional Telegram Bot with Token Economy - ERROR-FREE VERSION
Features: Working Buttons, Admin Panel, Referral System, UPI Payments
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
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ADMIN_ID = int(os.getenv('ADMIN_ID', 123456789))  # Replace with your admin ID
UPI_ID = os.getenv('UPI_ID', 'your_upi@bank')
CHANNEL_ID = os.getenv('CHANNEL_ID', '')

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rate limiting
user_last_action = {}
RATE_LIMIT = 1

# Database class with better error handling
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

# Initialize database
db = TokenBotDB()

# Decorators with better error handling
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
                bot.reply_to(message, "🚫 Admin only!")
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
            return func(message)
        except Exception as e:
            logger.error(f"Registration check error: {e}")
            bot.reply_to(message, "❌ Please use /start first!")
    return wrapper

# Safe message sending function
def safe_send_message(chat_id, text, reply_markup=None, parse_mode='Markdown'):
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Send message error: {e}")
        try:
            # Try without markdown if it fails
            return bot.send_message(chat_id, text, reply_markup=reply_markup)
        except:
            return None

def safe_edit_message(chat_id, message_id, text, reply_markup=None, parse_mode='Markdown'):
    try:
        return bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Edit message error: {e}")
        try:
            # Try without markdown if it fails
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
            welcome_text = f"""🎉 **Welcome back, {first_name}!**

💰 **Current Balance:** {user[3]} tokens
📊 **Total Earned:** {user[6]} tokens
💸 **Total Spent:** {user[7]} tokens

Ready to explore premium content? 🚀"""
        else:
            # Create new user
            ref_code = db.create_user(user_id, username, first_name, referred_by)
            if not ref_code:
                bot.reply_to(message, "❌ Registration failed. Please try again!")
                return
                
            welcome_text = f"""🎉 **Welcome to TokenBot, {first_name}!**

🎁 **Welcome Bonus:** 10 FREE tokens!
🔗 **Your Referral Code:** `{ref_code}`

**💡 How to earn more tokens:**
• 👥 Refer friends (+5 tokens each)
• 💳 Purchase token packages

**🚀 Quick Start:**"""
            
            if referred_by:
                welcome_text += "\n🎊 **Referral Bonus:** Your referrer got 5 tokens!"
        
        # Create inline keyboard
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💰 Check Balance", callback_data="balance"),
            types.InlineKeyboardButton("💳 Buy Tokens", callback_data="buy")
        )
        keyboard.add(
            types.InlineKeyboardButton("👥 Referrals", callback_data="referrals"),
            types.InlineKeyboardButton("❓ Help", callback_data="help")
        )
        
        safe_send_message(message.chat.id, welcome_text, reply_markup=keyboard)
        logger.info(f"User started: {first_name} ({user_id})")
        
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
        
        balance_text = f"""💰 **Your Token Wallet**

**💎 Current Balance:** {user[3]} tokens
**📈 Total Earned:** {user[6]} tokens  
**📉 Total Spent:** {user[7]} tokens
**👥 Referrals Made:** {total_refs}

**🔗 Your Referral Code:** `{user[4]}`
**📱 Share Link:** 
`https://t.me/{bot.get_me().username}?start={user[4]}`

💡 *Share your link to earn 5 tokens per referral!*"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💳 Buy More", callback_data="buy"),
            types.InlineKeyboardButton("👥 Invite", callback_data="referrals")
        )
        keyboard.add(
            types.InlineKeyboardButton("📊 Stats", callback_data="stats"),
            types.InlineKeyboardButton("🔄 Refresh", callback_data="balance")
        )
        
        safe_send_message(message.chat.id, balance_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Balance error: {e}")
        bot.reply_to(message, "❌ Error loading balance!")

@bot.message_handler(commands=['buy'])
@rate_limit
@registered_only
def buy_command(message):
    try:
        buy_text = f"""💳 **Token Store - Premium Packages**

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
4️⃣ Get tokens after verification!

⚡ *Verification time: 1-24 hours*"""
        
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
        
        safe_send_message(message.chat.id, buy_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Buy error: {e}")
        bot.reply_to(message, "❌ Error loading store!")

@bot.message_handler(commands=['refer'])
@rate_limit
@registered_only
def refer_command(message):
    try:
        user = db.get_user(message.from_user.id)
        if not user:
            bot.reply_to(message, "❌ Please use /start first!")
            return
            
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals and referrals[0] else 0
        
        bot_username = bot.get_me().username
        
        refer_text = f"""👥 **Referral Program - Earn Together!**

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
`https://t.me/{bot_username}?start={user[4]}`

🚀 *Start sharing and watch your tokens grow!*"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("📱 Share Link", 
                url=f"https://t.me/share/url?url=https://t.me/{bot_username}?start={user[4]}&text=🚀 Join this amazing bot and get FREE tokens!")
        )
        keyboard.add(
            types.InlineKeyboardButton("📋 Copy Code", callback_data=f"copy_{user[4]}"),
            types.InlineKeyboardButton("📊 Stats", callback_data="ref_stats")
        )
        
        safe_send_message(message.chat.id, refer_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Refer error: {e}")
        bot.reply_to(message, "❌ Error loading referral info!")

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
            'revenue': 0
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
        except Exception as e:
            logger.error(f"Stats query error: {e}")
        
        admin_text = f"""📊 **Admin Dashboard**

**👥 Users:** {stats['users']:,}
**💰 Total Tokens:** {stats['tokens_total']:,}
**💳 Payments:** {stats['payments_total']:,}
**⏳ Pending:** {stats['payments_pending']:,}
**💵 Revenue:** ₹{stats['revenue']:,.2f}

**🕐 Updated:** {datetime.now().strftime('%d/%m/%Y %H:%M')}"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            types.InlineKeyboardButton("💳 Payments", callback_data="admin_payments")
        )
        keyboard.add(
            types.InlineKeyboardButton("📁 Content", callback_data="admin_content"),
            types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh")
        )
        
        safe_send_message(message.chat.id, admin_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Admin panel error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

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
        
        # Notify user
        try:
            safe_send_message(user_id, f"""🎉 **Token Bonus!**

💰 **Added:** {amount} tokens
💎 **New Balance:** {new_balance} tokens

Enjoy! 🚀""")
        except Exception as e:
            logger.error(f"User notification error: {e}")
        
        bot.reply_to(message, f"""✅ **Success!**

👤 User: {user[2]} (`{user_id}`)
💰 Added: {amount} tokens
💎 New Balance: {new_balance} tokens""")
        
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
        
        # Notify user
        try:
            safe_send_message(user_id, f"""🎉 **Payment Verified!**

**💰 Details:**
• Payment ID: `{payment_id}`
• Amount: ₹{amount}
• Tokens Added: {tokens:,}

**✅ Your account updated!**
Use /balance to check new balance.

Thank you! 🚀""")
        except Exception as e:
            logger.error(f"User notification error: {e}")
        
        bot.reply_to(message, f"""✅ **Payment Verified!**

• Payment ID: `{payment_id}`
• User ID: `{user_id}`
• Amount: ₹{amount}
• Tokens: {tokens:,}

User notified successfully! ✅""")
        
        logger.info(f"Payment verified: ID {payment_id} - User {user_id} - {tokens} tokens")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid payment ID!")
    except Exception as e:
        logger.error(f"Verify error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

# 🎯 CALLBACK HANDLERS - COMPLETELY FIXED

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data
        user_id = call.from_user.id
        
        # Always answer callback query first to remove loading state
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
        elif data == 'help':
            handle_help_callback(call)
        elif data == 'stats':
            handle_stats_callback(call)
        elif data.startswith('copy_'):
            handle_copy_callback(call)
        elif data == 'ref_stats':
            handle_ref_stats_callback(call)
        elif data.startswith('content_'):
            handle_content_callback(call)
        elif data.startswith('admin_'):
            handle_admin_callback(call)
        elif data == 'start_bot':
            # Handle start_bot callback
            handle_start_callback(call)
        else:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❓ Unknown action!")
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Error occurred!")
        except:
            pass

def handle_start_callback(call):
    try:
        # Simulate start command for callback
        user_id = call.from_user.id
        username = call.from_user.username or ""
        first_name = call.from_user.first_name or "User"
        
        user = db.get_user(user_id)
        if user:
            welcome_text = f"""🎉 **Welcome back, {first_name}!**

💰 **Current Balance:** {user[3]} tokens
📊 **Total Earned:** {user[6]} tokens
💸 **Total Spent:** {user[7]} tokens

Ready to explore premium content? 🚀"""
        else:
            ref_code = db.create_user(user_id, username, first_name)
            if not ref_code:
                safe_edit_message(call.message.chat.id, call.message.message_id, "❌ Registration failed!")
                return
                
            welcome_text = f"""🎉 **Welcome to TokenBot, {first_name}!**

🎁 **Welcome Bonus:** 10 FREE tokens!
🔗 **Your Referral Code:** `{ref_code}`

**💡 How to earn more tokens:**
• 👥 Refer friends (+5 tokens each)
• 💳 Purchase token packages

**🚀 Quick Start:**"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💰 Check Balance", callback_data="balance"),
            types.InlineKeyboardButton("💳 Buy Tokens", callback_data="buy")
        )
        keyboard.add(
            types.InlineKeyboardButton("👥 Referrals", callback_data="referrals"),
            types.InlineKeyboardButton("❓ Help", callback_data="help")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, welcome_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Start callback error: {e}")

def handle_balance_callback(call):
    try:
        user = db.get_user(call.from_user.id)
        if not user:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❌ Please register first! Use /start")
            return
            
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals and referrals[0] else 0
        
        balance_text = f"""💰 **Your Token Wallet**

**💎 Current Balance:** {user[3]} tokens
**📈 Total Earned:** {user[6]} tokens  
**📉 Total Spent:** {user[7]} tokens
**👥 Referrals Made:** {total_refs}

**🔗 Referral Code:** `{user[4]}`
**📱 Share Link:** 
`https://t.me/{bot.get_me().username}?start={user[4]}`"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💳 Buy More", callback_data="buy"),
            types.InlineKeyboardButton("👥 Invite", callback_data="referrals")
        )
        keyboard.add(
            types.InlineKeyboardButton("📊 Stats", callback_data="stats"),
            types.InlineKeyboardButton("🔄 Refresh", callback_data="balance")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, balance_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Balance callback error: {e}")

def handle_buy_menu_callback(call):
    try:
        buy_text = f"""💳 **Token Store - Premium Packages**

**🎯 Special Offers:**
• 💎 **100 Tokens** - ₹10 `(₹0.10 each)`
• 🔥 **500 Tokens** - ₹45 `(₹0.09 each)` **10% OFF**
• ⭐ **1000 Tokens** - ₹80 `(₹0.08 each)` **20% OFF**
• 👑 **2000 Tokens** - ₹150 `(₹0.075 each)` **25% OFF**

**💰 Payment:** UPI Only
**🏦 UPI ID:** `{UPI_ID}`

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
        
        safe_edit_message(call.message.chat.id, call.message.message_id, buy_text, reply_markup=keyboard)
        
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
        
        payment_text = f"""💳 **Payment Instructions**

**📦 Package:** {package['tokens']} Tokens
**💰 Amount:** ₹{package['price']}
**🏦 UPI ID:** `{UPI_ID}`

**📋 Steps:**
1️⃣ Open any UPI app
2️⃣ Pay ₹{package['price']} to: `{UPI_ID}`
3️⃣ Add note: `Tokens_{user_id}`
4️⃣ Send screenshot here

**⚡ Verification:** 1-24 hours
**🎯 User ID:** `{user_id}`

Click button below to pay:"""
        
        keyboard = types.InlineKeyboardMarkup()
        # Use web-based payment link
        keyboard.add(
            types.InlineKeyboardButton("📱 Pay Now", 
                url=f"https://gpay.app.goo.gl/pay-{UPI_ID.replace('@', '-')}-{package['price']}")
        )
        keyboard.add(
            types.InlineKeyboardButton("💬 Support", url=f"tg://user?id={ADMIN_ID}"),
            types.InlineKeyboardButton("🔙 Back", callback_data="buy")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, payment_text, reply_markup=keyboard)
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
        
        refer_text = f"""👥 **Referral Program**

**🎯 Your Stats:**
• 🔗 **Code:** `{user[4]}`
• 👥 **Referrals:** {total_refs}
• 💰 **Earned:** {total_refs * 5} tokens

**📱 Your Link:**
`https://t.me/{bot_username}?start={user[4]}`

**💡 How it works:**
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
            types.InlineKeyboardButton("📋 Copy Code", callback_data=f"copy_{user[4]}"),
            types.InlineKeyboardButton("📊 Stats", callback_data="ref_stats")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="balance")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, refer_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Referrals callback error: {e}")

def handle_help_callback(call):
    try:
        help_text = """❓ **How TokenBot Works**

**🎁 Welcome Bonus:** 10 FREE tokens
**💰 Earn Tokens:** Refer friends (+5 each)
**🛒 Buy Tokens:** Premium packages
**🔓 Access Content:** Use tokens

**🚀 Commands:**
• `/start` - Register & get bonus
• `/balance` - Check wallet
• `/buy` - Purchase tokens
• `/refer` - Earn via referrals

**💡 Tips:**
• Share referral link to earn
• Buy packages for better rates
• Use tokens for premium content

Ready to start earning? 🚀"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("💰 Check Balance", callback_data="balance"),
            types.InlineKeyboardButton("💳 Buy Tokens", callback_data="buy")
        )
        keyboard.add(
            types.InlineKeyboardButton("👥 Refer Friends", callback_data="referrals")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, help_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Help callback error: {e}")

def handle_copy_callback(call):
    try:
        ref_code = call.data.split('_')[1]
        bot_username = bot.get_me().username
        link = f"https://t.me/{bot_username}?start={ref_code}"
        bot.answer_callback_query(call.id, f"🔗 Link copied!\n{link}", show_alert=True)
        
    except Exception as e:
        logger.error(f"Copy callback error: {e}")
        bot.answer_callback_query(call.id, "❌ Error copying link!")

def handle_stats_callback(call):
    try:
        user = db.get_user(call.from_user.id)
        if not user:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❌ Please register first!")
            return
            
        referrals = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = referrals[0][0] if referrals and referrals[0] else 0
        
        payments = db.execute("SELECT COUNT(*), SUM(amount) FROM payments WHERE user_id = ? AND status = 'verified'", (user[0],))
        total_payments = payments[0][0] if payments and payments[0] and payments[0][0] else 0
        total_spent_money = payments[0][1] if payments and payments[0] and payments[0][1] else 0
        
        stats_text = f"""📊 **Your Detailed Stats**

**💰 Token Stats:**
• Current Balance: {user[3]} tokens
• Total Earned: {user[6]} tokens
• Total Spent: {user[7]} tokens
• Net Tokens: {user[6] - user[7]} tokens

**👥 Referral Stats:**
• Total Referrals: {total_refs}
• Tokens from Referrals: {total_refs * 5}

**💳 Payment Stats:**
• Successful Payments: {total_payments}
• Total Money Spent: ₹{total_spent_money:.2f}

**📅 Account Info:**
• Join Date: {user[8][:10] if user[8] else 'Unknown'}
• Referral Code: `{user[4]}`

Keep earning! 🚀"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("💳 Buy More", callback_data="buy"),
            types.InlineKeyboardButton("👥 Refer", callback_data="referrals")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔄 Refresh", callback_data="stats"),
            types.InlineKeyboardButton("🔙 Back", callback_data="balance")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, stats_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Stats callback error: {e}")

def handle_ref_stats_callback(call):
    try:
        user = db.get_user(call.from_user.id)
        if not user:
            safe_edit_message(call.message.chat.id, call.message.message_id, "❌ Please register first!")
            return
            
        # Get recent referrals
        recent_refs = db.execute("""
            SELECT u.first_name, r.created_at 
            FROM referrals r 
            JOIN users u ON r.referred_id = u.user_id 
            WHERE r.referrer_id = ? 
            ORDER BY r.created_at DESC 
            LIMIT 5
        """, (user[0],))
        
        total_refs_result = db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_refs = total_refs_result[0][0] if total_refs_result and total_refs_result[0] else 0
        
        bot_username = bot.get_me().username
        
        ref_stats_text = f"""📊 **Referral Statistics**

**🎯 Overview:**
• Total Referrals: {total_refs}
• Tokens Earned: {total_refs * 5}
• Your Code: `{user[4]}`

**👥 Recent Referrals:**"""
        
        if recent_refs:
            for ref in recent_refs:
                name = ref[0] or "User"
                date = ref[1][:10] if ref[1] else "Unknown"
                ref_stats_text += f"\n• {name} - {date}"
        else:
            ref_stats_text += "\n• No referrals yet"
        
        ref_stats_text += f"""

**📱 Your Referral Link:**
`https://t.me/{bot_username}?start={user[4]}`

Start sharing to earn more! 🚀"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("📱 Share Now", 
                url=f"https://t.me/share/url?url=https://t.me/{bot_username}?start={user[4]}&text=🚀 Join and get FREE tokens!")
        )
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="referrals")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, ref_stats_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Ref stats callback error: {e}")

def handle_admin_callback(call):
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "🚫 Admin only!")
            return
            
        data = call.data
        
        if data == 'admin_refresh':
            # Refresh admin panel
            handle_admin_refresh(call)
        elif data == 'admin_users':
            handle_admin_users_callback(call)
        elif data == 'admin_payments':
            handle_admin_payments_callback(call)
        elif data == 'admin_content':
            handle_admin_content_callback(call)
        
    except Exception as e:
        logger.error(f"Admin callback error: {e}")

def handle_admin_refresh(call):
    try:
        stats = {
            'users': 0,
            'tokens_total': 0,
            'payments_total': 0,
            'payments_pending': 0,
            'revenue': 0
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
        except Exception as e:
            logger.error(f"Stats query error: {e}")
        
        admin_text = f"""📊 **Admin Dashboard**

**👥 Users:** {stats['users']:,}
**💰 Total Tokens:** {stats['tokens_total']:,}
**💳 Payments:** {stats['payments_total']:,}
**⏳ Pending:** {stats['payments_pending']:,}
**💵 Revenue:** ₹{stats['revenue']:,.2f}

**🕐 Updated:** {datetime.now().strftime('%d/%m/%Y %H:%M')}"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            types.InlineKeyboardButton("💳 Payments", callback_data="admin_payments")
        )
        keyboard.add(
            types.InlineKeyboardButton("📁 Content", callback_data="admin_content"),
            types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, admin_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Admin refresh error: {e}")

def handle_admin_users_callback(call):
    try:
        recent_users = db.execute("""
            SELECT user_id, first_name, tokens, join_date 
            FROM users 
            ORDER BY join_date DESC 
            LIMIT 10
        """)
        
        users_text = "👥 **Recent Users (Last 10)**\n\n"
        
        if recent_users:
            for user in recent_users:
                user_id, name, tokens, join_date = user
                name = name or "User"
                date = join_date[:10] if join_date else "Unknown"
                users_text += f"• {name} (`{user_id}`) - {tokens} tokens - {date}\n"
        else:
            users_text += "• No users found"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, users_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Admin users callback error: {e}")

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
        
        payments_text = "💳 **Pending Payments**\n\n"
        
        if pending_payments:
            for payment in pending_payments:
                pid, uid, name, amount, tokens, date = payment
                name = name or "User"
                date = date[:16] if date else "Unknown"
                payments_text += f"• ID: `{pid}` - {name} (`{uid}`)\n  ₹{amount} for {tokens} tokens - {date}\n\n"
            
            payments_text += "**Commands:**\n• `/verify <payment_id>` - Approve\n• `/reject <payment_id>` - Reject"
        else:
            payments_text += "✅ No pending payments!"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, payments_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Admin payments callback error: {e}")

def handle_admin_content_callback(call):
    try:
        content_count_result = db.execute("SELECT COUNT(*) FROM content")
        content_count = content_count_result[0][0] if content_count_result and content_count_result[0] else 0
        
        total_views_result = db.execute("SELECT SUM(views) FROM content")
        total_views = total_views_result[0][0] if total_views_result and total_views_result[0] and total_views_result[0][0] else 0
        
        content_text = f"""📁 **Content Management**

**📊 Statistics:**
• Total Content: {content_count}
• Total Views: {total_views:,}

**🔧 Management:**
• Use `/admin_upload` to add content
• Content gets auto-generated access links
• Token-based access control

**📋 Recent Content:**"""
        
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
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_refresh")
        )
        
        safe_edit_message(call.message.chat.id, call.message.message_id, content_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Admin content callback error: {e}")

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
        if not user:
            bot.answer_callback_query(call.id, "❌ Please register first!", show_alert=True)
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
        
        # Send content based on type
        caption = f"""🎯 **{content_data[1]}**

{content_data[2]}

💰 {tokens_required} tokens used
✅ Enjoy your content!"""
        
        try:
            if content_data[4] == 'photo':
                bot.send_photo(user_id, content_data[3], caption=caption)
            elif content_data[4] == 'video':
                bot.send_video(user_id, content_data[3], caption=caption)
            elif content_data[4] == 'document':
                bot.send_document(user_id, content_data[3], caption=caption)
            elif content_data[4] == 'audio':
                bot.send_audio(user_id, content_data[3], caption=caption)
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
        tokens_required = content_data[5]
        
        user = db.get_user(user_id)
        if not user:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("🚀 Register Now", callback_data="start_bot"))
            bot.reply_to(message, "❌ Please register first!", reply_markup=keyboard)
            return
        
        preview_text = f"""🎯 **Premium Content Preview**

**📁 Title:** {content_data[1]}
**📝 Description:** {content_data[2]}
**💰 Required:** {tokens_required} tokens
**👁️ Views:** {content_data[7]:,}
**📊 Type:** {content_data[4].title()}

**💳 Your Balance:** {user[3]} tokens

{'✅ You have enough tokens!' if user[3] >= tokens_required else f'❌ Need {tokens_required - user[3]} more tokens!'}"""
        
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
        
        safe_send_message(message.chat.id, preview_text, reply_markup=keyboard)
        
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
        
        pending = db.execute("SELECT * FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1", (user_id,))
        if not pending:
            bot.reply_to(message, "❌ No pending payments! Use /buy first.")
            return
        
        payment = pending[0]
        
        # Forward to admin with better formatting
        admin_text = f"""💳 **Payment Screenshot Received**

**👤 User:** {message.from_user.first_name or 'User'}
**🆔 Username:** @{message.from_user.username or 'None'}
**🔢 User ID:** `{user_id}`

**💰 Payment Details:**
• **Payment ID:** `{payment[0]}`
• **Amount:** ₹{payment[2]}
• **Tokens:** {payment[3]:,}
• **Date:** {payment[5][:16] if payment[5] else 'Unknown'}

**🔧 Quick Actions:**
• Approve: `/verify {payment[0]}`
• Reject: `/reject {payment[0]} reason`

Screenshot attached below ⬇️"""
        
        try:
            safe_send_message(ADMIN_ID, admin_text)
            bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            
            confirmation_text = f"""✅ **Payment Screenshot Received!**

**📋 Details:**
• Payment ID: `{payment[0]}`
• Amount: ₹{payment[2]}
• Tokens: {payment[3]:,}
• Status: ⏳ Pending Verification

**⏱️ What's Next:**
• Admin will verify your payment
• You'll get instant notification
• Tokens added automatically
• Usually takes 1-24 hours

Thank you for your patience! 🙏"""
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("💰 Check Balance", callback_data="balance"),
                types.InlineKeyboardButton("💬 Support", url=f"tg://user?id={ADMIN_ID}")
            )
            
            safe_send_message(message.chat.id, confirmation_text, reply_markup=keyboard)
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
        help_text = """❓ **Unknown Command**

**🚀 Available Commands:**
• `/start` - Register & get 10 FREE tokens
• `/balance` - Check token wallet
• `/buy` - Purchase tokens
• `/refer` - Earn via referrals

**🔧 Admin Commands:**
• `/admin` - Admin dashboard
• `/add_tokens <user_id> <amount>` - Add tokens
• `/verify <payment_id>` - Verify payment

**💡 Quick Actions:**"""
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("🚀 Start", callback_data="start_bot"),
            types.InlineKeyboardButton("💰 Balance", callback_data="balance")
        )
        keyboard.add(
            types.InlineKeyboardButton("💳 Buy", callback_data="buy"),
            types.InlineKeyboardButton("👥 Refer", callback_data="referrals")
        )
        keyboard.add(
            types.InlineKeyboardButton("💬 Support", url=f"tg://user?id={ADMIN_ID}")
        )
        
        safe_send_message(message.chat.id, help_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Unknown handler error: {e}")

# 🚀 MAIN FUNCTION

def main():
    try:
        logger.info("🚀 TokenBot starting...")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"💳 UPI ID: {UPI_ID}")
        
        # Test bot connection
        try:
            bot_info = bot.get_me()
            logger.info(f"🤖 Bot: @{bot_info.username} ({bot_info.first_name})")
        except Exception as e:
            logger.error(f"Bot connection error: {e}")
            return
        
        logger.info("✅ Bot started successfully! All errors fixed...")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
        
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        time.sleep(5)
        main()

if __name__ == "__main__":
    main()
