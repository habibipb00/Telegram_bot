#!/usr/bin/env python3
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

# Validate required environment variables
if not BOT_TOKEN or not ADMIN_ID or not UPI_ID:
    print("❌ Missing required environment variables!")
    print("Required: BOT_TOKEN, ADMIN_ID, UPI_ID")
    exit(1)

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Rate limiting
user_last_action = {}
RATE_LIMIT = 2

# Database setup
class Database:
    def __init__(self):
        self.db_path = 'bot.db'
        self.init_database()
    
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                tokens INTEGER DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                views INTEGER DEFAULT 0
            )
        ''')
        
        # Referrals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                tokens_earned INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized")
    
    def execute_query(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            results = cursor.fetchall()
            conn.commit()
            return results
        except Exception as e:
            logger.error(f"Database error: {e}")
            conn.rollback()
            return []
        finally:
            conn.close()
    
    def get_user(self, user_id):
        result = self.execute_query("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return result[0] if result else None
    
    def create_user(self, user_id, username, first_name, referred_by=None):
        referral_code = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8].upper()
        
        self.execute_query(
            "INSERT OR REPLACE INTO users (user_id, username, first_name, referral_code, referred_by) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, referral_code, referred_by)
        )
        
        if referred_by:
            self.add_referral_bonus(referred_by, user_id)
        
        return referral_code
    
    def add_referral_bonus(self, referrer_id, referred_id):
        bonus_tokens = 5
        self.execute_query("UPDATE users SET tokens = tokens + ? WHERE user_id = ?", (bonus_tokens, referrer_id))
        self.execute_query("INSERT INTO referrals (referrer_id, referred_id, tokens_earned) VALUES (?, ?, ?)", (referrer_id, referred_id, bonus_tokens))
    
    def update_tokens(self, user_id, tokens):
        self.execute_query("UPDATE users SET tokens = tokens + ? WHERE user_id = ?", (tokens, user_id))
    
    def get_user_by_referral(self, referral_code):
        result = self.execute_query("SELECT * FROM users WHERE referral_code = ?", (referral_code,))
        return result[0] if result else None

# Initialize database
db = Database()

# Decorators
def rate_limit(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        current_time = time.time()
        
        if user_id in user_last_action:
            if current_time - user_last_action[user_id] < RATE_LIMIT:
                bot.reply_to(message, "⚠️ Please wait before sending another command.")
                return
        
        user_last_action[user_id] = current_time
        return func(message)
    return wrapper

def admin_only(func):
    @wraps(func)
    def wrapper(message):
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "❌ Access denied. Admin only.")
            return
        return func(message)
    return wrapper

def registered_user_only(func):
    @wraps(func)
    def wrapper(message):
        user = db.get_user(message.from_user.id)
        if not user:
            bot.reply_to(message, "❌ Please start the bot first with /start")
            return
        return func(message)
    return wrapper

# Utility functions
def create_keyboard(buttons):
    keyboard = types.InlineKeyboardMarkup()
    for row in buttons:
        keyboard_row = []
        for button in row:
            keyboard_row.append(types.InlineKeyboardButton(button['text'], callback_data=button.get('callback_data'), url=button.get('url')))
        keyboard.row(*keyboard_row)
    return keyboard

# Bot Commands
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
        
        # Check for referral code
        referred_by = None
        if len(message.text.split()) > 1:
            referral_code = message.text.split()[1]
            referrer = db.get_user_by_referral(referral_code)
            if referrer and referrer[0] != user_id:
                referred_by = referrer[0]
        
        # Check if user exists
        existing_user = db.get_user(user_id)
        if existing_user:
            bot.reply_to(message, f"Welcome back, {first_name}! 🎉\nTokens: {existing_user[3]}")
            return
        
        # Create new user
        user_referral_code = db.create_user(user_id, username, first_name, referred_by)
        
        welcome_text = f"""🎉 Welcome {first_name}!

💰 Starting tokens: 0
🔗 Your referral code: `{user_referral_code}`

Commands:
/balance - Check balance
/buy - Purchase tokens
/refer - Referral info

Your referral link:
https://t.me/{bot.get_me().username}?start={user_referral_code}"""
        
        if referred_by:
            welcome_text += "\n\n🎁 You were referred! Your referrer got 5 tokens!"
        
        bot.reply_to(message, welcome_text, parse_mode='Markdown')
        logger.info(f"New user: {user_id} ({first_name})")
        
    except Exception as e:
        logger.error(f"Start command error: {e}")
        bot.reply_to(message, "❌ Error during registration. Please try again.")

@bot.message_handler(commands=['balance'])
@rate_limit
@registered_user_only
def balance_command(message):
    try:
        user = db.get_user(message.from_user.id)
        
        balance_text = f"""💰 Your Balance

Current Tokens: {user[3]}
User ID: `{user[0]}`
Referral Code: `{user[4]}`

Referral Link:
https://t.me/{bot.get_me().username}?start={user[4]}"""
        
        keyboard = create_keyboard([
            [{'text': '💳 Buy Tokens', 'callback_data': 'buy_tokens'}],
            [{'text': '👥 Referral Info', 'callback_data': 'referral_info'}]
        ])
        
        bot.reply_to(message, balance_text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Balance command error: {e}")
        bot.reply_to(message, "❌ Error getting balance.")

@bot.message_handler(commands=['buy'])
@rate_limit
@registered_user_only
def buy_command(message):
    try:
        buy_text = f"""💳 Purchase Tokens

Token Packages:
• 100 Tokens - ₹10
• 500 Tokens - ₹45 (10% OFF)
• 1000 Tokens - ₹80 (20% OFF)
• 2000 Tokens - ₹150 (25% OFF)

Payment: UPI Only
UPI ID: `{UPI_ID}`

Instructions:
1. Choose package below
2. Pay to UPI ID
3. Send payment screenshot
4. Wait for verification (1-24 hours)"""
        
        keyboard = create_keyboard([
            [{'text': '100 - ₹10', 'callback_data': 'buy_100'}, {'text': '500 - ₹45', 'callback_data': 'buy_500'}],
            [{'text': '1000 - ₹80', 'callback_data': 'buy_1000'}, {'text': '2000 - ₹150', 'callback_data': 'buy_2000'}]
        ])
        
        bot.reply_to(message, buy_text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Buy command error: {e}")
        bot.reply_to(message, "❌ Error loading packages.")

@bot.message_handler(commands=['refer'])
@rate_limit
@registered_user_only
def refer_command(message):
    try:
        user = db.get_user(message.from_user.id)
        
        referrals = db.execute_query("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user[0],))
        total_referrals = referrals[0][0] if referrals else 0
        
        refer_text = f"""👥 Referral Program

🔗 Your Code: `{user[4]}`
📊 Total Referrals: {total_referrals}
💰 Tokens Earned: {total_referrals * 5}

How it works:
• Share your link
• Get 5 tokens per referral
• No limit!

Your Link:
https://t.me/{bot.get_me().username}?start={user[4]}"""
        
        keyboard = create_keyboard([
            [{'text': '📱 Share Link', 'url': f'https://t.me/share/url?url=https://t.me/{bot.get_me().username}?start={user[4]}&text=Join this bot!'}]
        ])
        
        bot.reply_to(message, refer_text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Refer command error: {e}")
        bot.reply_to(message, "❌ Error getting referral info.")

# Admin Commands
@bot.message_handler(commands=['admin_stats'])
@admin_only
def admin_stats_command(message):
    try:
        total_users = db.execute_query("SELECT COUNT(*) FROM users")[0][0]
        total_tokens = db.execute_query("SELECT SUM(tokens) FROM users")[0][0] or 0
        total_payments = db.execute_query("SELECT COUNT(*) FROM payments")[0][0]
        pending_payments = db.execute_query("SELECT COUNT(*) FROM payments WHERE status = 'pending'")[0][0]
        
        stats_text = f"""📊 Bot Statistics

👥 Total Users: {total_users}
💰 Total Tokens: {total_tokens}
💳 Total Payments: {total_payments}
⏳ Pending Payments: {pending_payments}

Updated: {datetime.now().strftime('%H:%M:%S')}"""
        
        bot.reply_to(message, stats_text)
        
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['admin_tokens'])
@admin_only
def admin_tokens_command(message):
    try:
        args = message.text.split()
        if len(args) < 4:
            bot.reply_to(message, """Token Management

Usage: /admin_tokens <action> <user_id> <amount>

Actions: add, remove, set

Examples:
/admin_tokens add 123456789 100
/admin_tokens remove 123456789 50
/admin_tokens set 123456789 200""")
            return
        
        action = args[1].lower()
        user_id = int(args[2])
        amount = int(args[3])
        
        user = db.get_user(user_id)
        if not user:
            bot.reply_to(message, f"❌ User {user_id} not found!")
            return
        
        current_tokens = user[3]
        
        if action == 'add':
            db.update_tokens(user_id, amount)
            new_tokens = current_tokens + amount
            action_text = f"Added {amount} tokens"
        elif action == 'remove':
            if current_tokens < amount:
                bot.reply_to(message, f"❌ User only has {current_tokens} tokens!")
                return
            db.update_tokens(user_id, -amount)
            new_tokens = current_tokens - amount
            action_text = f"Removed {amount} tokens"
        elif action == 'set':
            difference = amount - current_tokens
            db.update_tokens(user_id, difference)
            new_tokens = amount
            action_text = f"Set tokens to {amount}"
        else:
            bot.reply_to(message, "❌ Invalid action! Use: add, remove, or set")
            return
        
        # Notify user
        try:
            bot.send_message(user_id, f"💰 Token update: {action_text}\nNew balance: {new_tokens}")
        except:
            pass
        
        bot.reply_to(message, f"✅ {action_text} for user {user_id}\nNew balance: {new_tokens}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID or amount!")
    except Exception as e:
        logger.error(f"Admin tokens error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['verify'])
@admin_only
def verify_payment_command(message):
    try:
        args = message.text.split()
        if len(args) != 2:
            bot.reply_to(message, "Usage: /verify <payment_id>")
            return
        
        payment_id = int(args[1])
        
        payment = db.execute_query("SELECT * FROM payments WHERE id = ? AND status = 'pending'", (payment_id,))
        if not payment:
            bot.reply_to(message, "❌ Payment not found!")
            return
        
        payment_data = payment[0]
        user_id = payment_data[1]
        tokens = payment_data[3]
        
        # Update payment and add tokens
        db.execute_query("UPDATE payments SET status = 'verified' WHERE id = ?", (payment_id,))
        db.update_tokens(user_id, tokens)
        
        # Notify user
        try:
            bot.send_message(user_id, f"✅ Payment verified! {tokens} tokens added to your account!")
        except:
            pass
        
        bot.reply_to(message, f"✅ Payment {payment_id} verified! {tokens} tokens added to user {user_id}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid payment ID!")
    except Exception as e:
        logger.error(f"Verify payment error: {e}")
        bot.reply_to(message, f"❌ Error: {e}")

# Callback handlers
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data
        user_id = call.from_user.id
        
        if data.startswith('buy_'):
            handle_buy_callback(call)
        elif data == 'referral_info':
            refer_command(call.message)
        
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "❌ Error!")

def handle_buy_callback(call):
    try:
        data = call.data
        user_id = call.from_user.id
        
        packages = {
            'buy_100': {'tokens': 100, 'price': 10},
            'buy_500': {'tokens': 500, 'price': 45},
            'buy_1000': {'tokens': 1000, 'price': 80},
            'buy_2000': {'tokens': 2000, 'price': 150}
        }
        
        if data not in packages:
            return
        
        package = packages[data]
        
        # Create payment record
        db.execute_query("INSERT INTO payments (user_id, amount, tokens, status) VALUES (?, ?, ?, 'pending')", (user_id, package['price'], package['tokens']))
        
        payment_text = f"""💳 Payment Details

Package: {package['tokens']} Tokens
Amount: ₹{package['price']}
UPI ID: `{UPI_ID}`

Instructions:
1. Pay ₹{package['price']} to UPI ID
2. Include User ID {user_id} in description
3. Send payment screenshot here
4. Wait for verification

⚠️ Verification: 1-24 hours"""
        
        keyboard = create_keyboard([
            [{'text': '📱 Open UPI', 'url': f'upi://pay?pa={UPI_ID}&am={package["price"]}&tn=Tokens_{user_id}'}]
        ])
        
        bot.edit_message_text(payment_text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Buy callback error: {e}")

def handle_content_access(message):
    try:
        deeplink = message.text.split('_')[1]
        user_id = message.from_user.id
        
        content = db.execute_query("SELECT * FROM content WHERE deeplink = ?", (deeplink,))
        if not content:
            bot.reply_to(message, "❌ Content not found!")
            return
        
        content_data = content[0]
        tokens_required = content_data[5]
        
        user = db.get_user(user_id)
        if not user:
            bot.reply_to(message, "❌ Please register first with /start")
            return
        
        if user[3] < tokens_required:
            bot.reply_to(message, f"❌ Need {tokens_required} tokens! You have {user[3]}")
            return
        
        # Deduct tokens and send content
        db.update_tokens(user_id, -tokens_required)
        db.execute_query("UPDATE content SET views = views + 1 WHERE deeplink = ?", (deeplink,))
        
        if content_data[4] == 'photo':
            bot.send_photo(user_id, content_data[3], caption=f"{content_data[1]}\n\n{content_data[2]}")
        elif content_data[4] == 'video':
            bot.send_video(user_id, content_data[3], caption=f"{content_data[1]}\n\n{content_data[2]}")
        elif content_data[4] == 'document':
            bot.send_document(user_id, content_data[3], caption=f"{content_data[1]}\n\n{content_data[2]}")
        
        bot.reply_to(message, f"✅ Content accessed! {tokens_required} tokens deducted.")
        
    except Exception as e:
        logger.error(f"Content access error: {e}")
        bot.reply_to(message, "❌ Error accessing content!")

# Payment screenshot handler
@bot.message_handler(content_types=['photo'])
@rate_limit
def handle_payment_screenshot(message):
    try:
        user_id = message.from_user.id
        
        pending_payments = db.execute_query("SELECT * FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1", (user_id,))
        
        if not pending_payments:
            bot.reply_to(message, "❌ No pending payments. Use /buy first.")
            return
        
        payment = pending_payments[0]
        
        # Forward to admin
        try:
            admin_text = f"""💳 Payment Verification

User: {message.from_user.first_name} ({user_id})
Amount: ₹{payment[2]}
Tokens: {payment[3]}
Payment ID: {payment[0]}

Use: /verify {payment[0]}"""
            
            bot.send_message(ADMIN_ID, admin_text)
            bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            
            bot.reply_to(message, f"""✅ Screenshot received!

Payment ID: {payment[0]}
Amount: ₹{payment[2]}
Tokens: {payment[3]}

Your payment is being verified.
You'll be notified once approved.

⏱️ Verification: 1-24 hours""")
            
        except Exception as e:
            logger.error(f"Forward error: {e}")
            bot.reply_to(message, "❌ Error forwarding screenshot. Contact admin.")
        
    except Exception as e:
        logger.error(f"Screenshot handler error: {e}")
        bot.reply_to(message, "❌ Error processing screenshot.")

# Unknown message handler
@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    try:
        help_text = """❓ Unknown command

Available commands:
• /start - Register
• /balance - Check balance
• /buy - Purchase tokens
• /refer - Referral info

Admin commands:
• /admin_stats - Statistics
• /admin_tokens - Manage tokens
• /verify - Verify payments"""
        
        bot.reply_to(message, help_text)
        
    except Exception as e:
        logger.error(f"Unknown handler error: {e}")

# Main function
def main():
    try:
        logger.info("Bot starting...")
        logger.info(f"Admin ID: {ADMIN_ID}")
        logger.info(f"UPI ID: {UPI_ID}")
        
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
        
    except Exception as e:
        logger.error(f"Bot error: {e}")
        time.sleep(5)
        main()

if __name__ == "__main__":
    main()
