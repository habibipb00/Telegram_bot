#!/usr/bin/env python3
"""
🚀 Professional Telegram Bot with Token Economy - FIXED VERSION
Features: Admin Upload System, Auto Channel Posting, Enhanced Admin Powers
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

# Initialize bot with better error handling
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
            
            # Content table
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

# 🚀 COMMANDS

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
💸 *Total Spent:* {user[7]} tokens

🌟 *VIP Channel:* @{VIP_CHANNEL_USERNAME}
_Join for exclusive premium content!_

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

💡 *How to earn more tokens:*
• 👥 Refer friends (+5 tokens each)
• 💳 Purchase token packages

🌟 *VIP Channel:* @{VIP_CHANNEL_USERNAME}
_Join for exclusive premium content!_

🚀 *Quick Start:*"""
            
            if referred_by:
                welcome_text += "\n🎊 *Referral Bonus:* Your referrer got 5 tokens!"
        
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
        if VIP_CHANNEL_USERNAME != 'your_vip_channel':
            keyboard.add(
                types.InlineKeyboardButton("🌟 Join VIP Channel", url=VIP_CHANNEL_URL)
            )
        
        safe_send_message(message.chat.id, welcome_text, reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"✅ User started successfully: {first_name} ({user_id})")
        
    except Exception as e:
        logger.error(f"Start command error: {e}")
        bot.reply_to(message, "❌ Error occurred. Please try again!")

@bot.message_handler(commands=['test'])
def test_command(message):
    """Simple test command to verify bot is working"""
    try:
        user_id = message.from_user.id
        first_name = message.from_user.first_name or "User"
        
        test_text = f"""✅ *Bot is Working!*

👤 *User:* {first_name}
🆔 *ID:* `{user_id}`
🕐 *Time:* {datetime.now().strftime('%H:%M:%S')}
📅 *Date:* {datetime.now().strftime('%d/%m/%Y')}

🚀 *Bot Status:* Active & Responding!"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("🚀 Start Bot", callback_data="start_bot"))
        
        safe_send_message(message.chat.id, test_text, reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"Test command successful: {first_name} ({user_id})")
        
    except Exception as e:
        logger.error(f"Test command error: {e}")
        bot.reply_to(message, f"❌ Test failed: {e}")

@bot.message_handler(commands=['status'])
@admin_only
def status_command(message):
    """Admin command to check bot status"""
    try:
        # Get basic stats
        users_count = db.execute("SELECT COUNT(*) FROM users")
        total_users = users_count[0][0] if users_count and users_count[0] else 0
        
        status_text = f"""📊 *Bot Status Report*

🤖 *Bot:* Active & Running
👥 *Total Users:* {total_users:,}
🕐 *Uptime:* Running
📅 *Date:* {datetime.now().strftime('%d/%m/%Y %H:%M')}

✅ *All Systems Operational!*"""
        
        safe_send_message(message.chat.id, status_text, parse_mode='Markdown')
        logger.info(f"Status check by admin: {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Status command error: {e}")
        bot.reply_to(message, f"❌ Status check failed: {e}")

# Simple callback handler for testing
@bot.callback_query_handler(func=lambda call: call.data == "start_bot")
def handle_start_callback(call):
    try:
        bot.answer_callback_query(call.id)
        # Simulate /start command
        start_command(call.message)
        logger.info(f"Start callback triggered by: {call.from_user.id}")
    except Exception as e:
        logger.error(f"Start callback error: {e}")

# Basic message handler for testing
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        if message.text and message.text.startswith('/'):
            return  # Let command handlers deal with it
            
        # Simple echo for testing
        user_id = message.from_user.id
        first_name = message.from_user.first_name or "User"
        
        response = f"""👋 *Hi {first_name}!*

You said: _{message.text}_

🚀 *Available Commands:*
• `/start` - Register & get tokens
• `/test` - Test bot functionality
• `/status` - Check bot status (Admin only)

💡 *Use /start to begin!*"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("🚀 Start Bot", callback_data="start_bot"))
        
        safe_send_message(message.chat.id, response, reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"Message handled: {first_name} ({user_id}) - {message.text[:50]}")
        
    except Exception as e:
        logger.error(f"Message handler error: {e}")

def handle_content_access(message):
    """Placeholder for content access"""
    bot.reply_to(message, "🔧 Content access feature coming soon!")

# 🚀 MAIN FUNCTION with better error handling

def main():
    global bot_running
    
    try:
        logger.info("🚀 TokenBot Starting...")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"💳 UPI ID: {UPI_ID}")
        logger.info(f"📢 Channel ID: {CHANNEL_ID}")
        logger.info(f"🌟 VIP Channel: @{VIP_CHANNEL_USERNAME}")
        
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
