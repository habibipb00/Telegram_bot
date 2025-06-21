#!/usr/bin/env python3
"""
Complete Telegram Bot with Admin Panel, Token Economy, and Payment System
Production-ready version with comprehensive error handling and optimizations
"""

import os
import sqlite3
import logging
import time
import hashlib
import json
import threading
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from functools import wraps
import telebot
from telebot import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration with validation
class Config:
    def __init__(self):
        self.BOT_TOKEN = os.getenv('BOT_TOKEN')
        self.ADMIN_ID = self._get_int_env('ADMIN_ID')
        self.UPI_ID = os.getenv('UPI_ID')
        self.CHANNEL_ID = os.getenv('CHANNEL_ID', '')
        self.DATABASE_PATH = os.getenv('DATABASE_PATH', 'bot.db')
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        self.RATE_LIMIT_SECONDS = self._get_int_env('RATE_LIMIT_SECONDS', 2)
        self.MAX_RETRIES = self._get_int_env('MAX_RETRIES', 3)
        
        self._validate_config()
    
    def _get_int_env(self, key: str, default: int = 0) -> int:
        try:
            return int(os.getenv(key, default))
        except (ValueError, TypeError):
            return default
    
    def _validate_config(self):
        """Validate required configuration"""
        errors = []
        
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN is required")
        
        if not self.ADMIN_ID:
            errors.append("ADMIN_ID is required")
        
        if not self.UPI_ID:
            errors.append("UPI_ID is required")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

# Initialize configuration
try:
    config = Config()
except ValueError as e:
    print(f"❌ Configuration Error: {e}")
    sys.exit(1)

# Logging setup
def setup_logging():
    """Setup comprehensive logging"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler('logs/bot.log'),
            logging.FileHandler('logs/error.log', level=logging.ERROR),
            logging.StreamHandler()
        ]
    )
    
    # Reduce telebot logging noise
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)

setup_logging()
logger = logging.getLogger(__name__)

# Global variables
bot = None
user_last_action: Dict[int, float] = {}
bot_info = None
shutdown_flag = threading.Event()

# Database class with improved error handling and connection pooling
class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_PATH
        self._lock = threading.Lock()
        self.init_database()
        logger.info(f"Database initialized at: {self.db_path}")
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with proper configuration"""
        conn = sqlite3.connect(
            self.db_path, 
            timeout=30.0,
            check_same_thread=False
        )
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn
    
    def init_database(self):
        """Initialize database tables with proper indexes"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            try:
                # Users table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        tokens INTEGER DEFAULT 0,
                        referral_code TEXT UNIQUE,
                        referred_by INTEGER,
                        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active INTEGER DEFAULT 1,
                        total_spent INTEGER DEFAULT 0,
                        total_earned INTEGER DEFAULT 0
                    )
                ''')
                
                # Payments table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        amount REAL NOT NULL,
                        tokens INTEGER NOT NULL,
                        upi_ref TEXT,
                        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'verified', 'rejected')),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        verified_at TIMESTAMP,
                        verified_by INTEGER,
                        rejection_reason TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (user_id),
                        FOREIGN KEY (verified_by) REFERENCES users (user_id)
                    )
                ''')
                
                # Content table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS content (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        description TEXT,
                        file_id TEXT NOT NULL,
                        file_type TEXT NOT NULL,
                        tokens_required INTEGER DEFAULT 10,
                        deeplink TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_by INTEGER,
                        views INTEGER DEFAULT 0,
                        is_active INTEGER DEFAULT 1,
                        FOREIGN KEY (created_by) REFERENCES users (user_id)
                    )
                ''')
                
                # Referrals table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS referrals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        referrer_id INTEGER NOT NULL,
                        referred_id INTEGER NOT NULL,
                        tokens_earned INTEGER DEFAULT 5,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                        FOREIGN KEY (referred_id) REFERENCES users (user_id),
                        UNIQUE(referrer_id, referred_id)
                    )
                ''')
                
                # Bot stats table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bot_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stat_name TEXT UNIQUE NOT NULL,
                        stat_value INTEGER DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Create indexes for better performance
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)",
                    "CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)",
                    "CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)",
                    "CREATE INDEX IF NOT EXISTS idx_content_deeplink ON content(deeplink)",
                    "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)",
                    "CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity)"
                ]
                
                for index_sql in indexes:
                    cursor.execute(index_sql)
                
                # Initialize bot stats
                initial_stats = [
                    ('total_users', 0),
                    ('total_payments', 0),
                    ('total_content', 0),
                    ('total_referrals', 0)
                ]
                
                for stat_name, stat_value in initial_stats:
                    cursor.execute(
                        "INSERT OR IGNORE INTO bot_stats (stat_name, stat_value) VALUES (?, ?)",
                        (stat_name, stat_value)
                    )
                
                conn.commit()
                logger.info("Database tables and indexes created successfully")
                
            except Exception as e:
                logger.error(f"Database initialization error: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def execute_query(self, query: str, params: tuple = (), fetch: bool = True) -> List[tuple]:
        """Execute query with proper error handling and connection management"""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute(query, params)
                
                if fetch and query.strip().upper().startswith('SELECT'):
                    results = cursor.fetchall()
                else:
                    results = []
                
                conn.commit()
                return results
                
            except sqlite3.Error as e:
                logger.error(f"Database error - Query: {query[:100]}..., Error: {e}")
                conn.rollback()
                return []
            except Exception as e:
                logger.error(f"Unexpected database error: {e}")
                conn.rollback()
                return []
            finally:
                conn.close()
    
    def get_user(self, user_id: int) -> Optional[tuple]:
        """Get user by ID with error handling"""
        try:
            result = self.execute_query(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    def create_user(self, user_id: int, username: str, first_name: str, referred_by: int = None) -> str:
        """Create new user with comprehensive error handling"""
        try:
            referral_code = self.generate_referral_code(user_id)
            
            # Insert user
            self.execute_query(
                """INSERT OR REPLACE INTO users 
                   (user_id, username, first_name, referral_code, referred_by, last_activity) 
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (user_id, username, first_name, referral_code, referred_by),
                fetch=False
            )
            
            # Handle referral bonus
            if referred_by:
                self.add_referral_bonus(referred_by, user_id)
            
            # Update stats
            self.update_stat('total_users', 1)
            
            logger.info(f"User created: {user_id} ({first_name}), referred by: {referred_by}")
            return referral_code
            
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return self.generate_referral_code(user_id)  # Return a code even if creation fails
    
    def generate_referral_code(self, user_id: int) -> str:
        """Generate unique referral code"""
        return hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8].upper()
    
    def add_referral_bonus(self, referrer_id: int, referred_id: int):
        """Add referral bonus with duplicate prevention"""
        try:
            bonus_tokens = 5
            
            # Check if referral already exists
            existing = self.execute_query(
                "SELECT id FROM referrals WHERE referrer_id = ? AND referred_id = ?",
                (referrer_id, referred_id)
            )
            
            if existing:
                logger.warning(f"Referral bonus already given: {referrer_id} -> {referred_id}")
                return
            
            # Add tokens to referrer
            self.execute_query(
                "UPDATE users SET tokens = tokens + ?, total_earned = total_earned + ? WHERE user_id = ?",
                (bonus_tokens, bonus_tokens, referrer_id),
                fetch=False
            )
            
            # Record referral
            self.execute_query(
                "INSERT INTO referrals (referrer_id, referred_id, tokens_earned) VALUES (?, ?, ?)",
                (referrer_id, referred_id, bonus_tokens),
                fetch=False
            )
            
            # Update stats
            self.update_stat('total_referrals', 1)
            
            logger.info(f"Referral bonus added: {referrer_id} got {bonus_tokens} tokens for referring {referred_id}")
            
        except Exception as e:
            logger.error(f"Error adding referral bonus: {e}")
    
    def update_tokens(self, user_id: int, tokens: int, reason: str = "manual"):
        """Update user tokens with logging"""
        try:
            # Update tokens
            self.execute_query(
                "UPDATE users SET tokens = tokens + ?, last_activity = CURRENT_TIMESTAMP WHERE user_id = ?",
                (tokens, user_id),
                fetch=False
            )
            
            # Update spending/earning stats
            if tokens > 0:
                self.execute_query(
                    "UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?",
                    (tokens, user_id),
                    fetch=False
                )
            else:
                self.execute_query(
                    "UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?",
                    (abs(tokens), user_id),
                    fetch=False
                )
            
            logger.info(f"Tokens updated for user {user_id}: {tokens:+d} ({reason})")
            
        except Exception as e:
            logger.error(f"Error updating tokens for user {user_id}: {e}")
    
    def get_user_by_referral(self, referral_code: str) -> Optional[tuple]:
        """Get user by referral code"""
        try:
            result = self.execute_query(
                "SELECT * FROM users WHERE referral_code = ?", (referral_code,)
            )
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting user by referral code {referral_code}: {e}")
            return None
    
    def update_stat(self, stat_name: str, increment: int = 1):
        """Update bot statistics"""
        try:
            self.execute_query(
                """INSERT OR REPLACE INTO bot_stats (stat_name, stat_value, updated_at)
                   VALUES (?, COALESCE((SELECT stat_value FROM bot_stats WHERE stat_name = ?), 0) + ?, CURRENT_TIMESTAMP)""",
                (stat_name, stat_name, increment),
                fetch=False
            )
        except Exception as e:
            logger.error(f"Error updating stat {stat_name}: {e}")
    
    def backup_database(self, backup_path: str = None):
        """Create database backup"""
        try:
            if not backup_path:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = f"backups/bot_backup_{timestamp}.db"
            
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            
            with self._lock:
                source = self.get_connection()
                backup = sqlite3.connect(backup_path)
                source.backup(backup)
                backup.close()
                source.close()
            
            logger.info(f"Database backup created: {backup_path}")
            return backup_path
            
        except Exception as e:
            logger.error(f"Error creating database backup: {e}")
            return None

# Initialize database
try:
    db = Database()
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
    sys.exit(1)

# Bot initialization with error handling
def initialize_bot():
    """Initialize bot with proper error handling"""
    global bot, bot_info
    
    try:
        bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode='Markdown')
        
        # Test bot connection
        bot_info = bot.get_me()
        logger.info(f"Bot initialized successfully: @{bot_info.username} ({bot_info.first_name})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize bot: {e}")
        return False

# Decorators with improved error handling
def rate_limit(func):
    """Rate limiting decorator with user-friendly messages"""
    @wraps(func)
    def wrapper(message):
        try:
            user_id = message.from_user.id
            current_time = time.time()
            
            if user_id in user_last_action:
                time_diff = current_time - user_last_action[user_id]
                if time_diff < config.RATE_LIMIT_SECONDS:
                    remaining = config.RATE_LIMIT_SECONDS - time_diff
                    bot.reply_to(
                        message, 
                        f"⚠️ Please wait {remaining:.1f} seconds before sending another command."
                    )
                    return
            
            user_last_action[user_id] = current_time
            return func(message)
            
        except Exception as e:
            logger.error(f"Rate limit error: {e}")
            return func(message)  # Continue execution if rate limiting fails
    
    return wrapper

def admin_only(func):
    """Admin only decorator with logging"""
    @wraps(func)
    def wrapper(message):
        try:
            if message.from_user.id != config.ADMIN_ID:
                logger.warning(f"Unauthorized admin access attempt by user {message.from_user.id}")
                bot.reply_to(message, "❌ Access denied. Admin only command.")
                return
            
            logger.info(f"Admin command executed: {func.__name__} by {message.from_user.id}")
            return func(message)
            
        except Exception as e:
            logger.error(f"Admin decorator error: {e}")
            bot.reply_to(message, "❌ An error occurred processing admin command.")
    
    return wrapper

def registered_user_only(func):
    """Registered user only decorator with auto-registration prompt"""
    @wraps(func)
    def wrapper(message):
        try:
            user = db.get_user(message.from_user.id)
            if not user:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(
                    types.InlineKeyboardButton("🚀 Start Bot", callback_data="start_registration")
                )
                
                bot.reply_to(
                    message, 
                    "❌ Please register first by clicking the button below:",
                    reply_markup=keyboard
                )
                return
            
            # Update last activity
            db.execute_query(
                "UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?",
                (message.from_user.id,),
                fetch=False
            )
            
            return func(message)
            
        except Exception as e:
            logger.error(f"User registration check error: {e}")
            bot.reply_to(message, "❌ An error occurred. Please try again.")
    
    return wrapper

def safe_bot_action(func):
    """Decorator for safe bot actions with retry logic"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(config.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except telebot.apihelper.ApiTelegramException as e:
                if e.error_code == 429:  # Rate limited
                    retry_after = int(e.result_json.get('parameters', {}).get('retry_after', 1))
                    logger.warning(f"Rate limited, waiting {retry_after} seconds")
                    time.sleep(retry_after)
                    continue
                elif e.error_code in [403, 400]:  # User blocked bot or bad request
                    logger.warning(f"Bot action failed: {e}")
                    break
                else:
                    logger.error(f"Telegram API error: {e}")
                    if attempt == config.MAX_RETRIES - 1:
                        raise
            except Exception as e:
                logger.error(f"Bot action error (attempt {attempt + 1}): {e}")
                if attempt == config.MAX_RETRIES - 1:
                    raise
                time.sleep(1)
        
        return None
    
    return wrapper

# Utility functions
def create_inline_keyboard(buttons: List[List[Dict]]) -> types.InlineKeyboardMarkup:
    """Create inline keyboard with error handling"""
    try:
        keyboard = types.InlineKeyboardMarkup()
        for row in buttons:
            keyboard_row = []
            for button in row:
                keyboard_row.append(
                    types.InlineKeyboardButton(
                        button['text'], 
                        callback_data=button.get('callback_data'),
                        url=button.get('url')
                    )
                )
            keyboard.row(*keyboard_row)
        return keyboard
    except Exception as e:
        logger.error(f"Error creating keyboard: {e}")
        return types.InlineKeyboardMarkup()

def format_user_info(user_data: tuple) -> str:
    """Format user information with safe handling"""
    try:
        user_id, username, first_name, tokens, referral_code, referred_by, join_date, last_activity, is_active, total_spent, total_earned = user_data
        
        return f"""
👤 **User Information**
🆔 ID: `{user_id}`
👤 Name: {first_name or 'Unknown'}
📱 Username: @{username or 'None'}
💰 Current Tokens: {tokens}
💸 Total Spent: {total_spent}
💎 Total Earned: {total_earned}
🔗 Referral Code: `{referral_code}`
📅 Joined: {join_date}
🕐 Last Active: {last_activity}
"""
    except Exception as e:
        logger.error(f"Error formatting user info: {e}")
        return "❌ Error displaying user information"

def safe_send_message(chat_id: int, text: str, **kwargs):
    """Safely send message with error handling"""
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")
        return None

# Bot Commands with comprehensive error handling

@bot.message_handler(commands=['start'])
@rate_limit
def start_command(message):
    """Handle /start command with comprehensive error handling"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name or "User"
        
        # Handle content deeplink
        if len(message.text.split()) > 1 and message.text.split()[1].startswith('content_'):
            handle_content_deeplink(message)
            return
        
        # Check for referral code
        referred_by = None
        if len(message.text.split()) > 1:
            referral_code = message.text.split()[1]
            referrer = db.get_user_by_referral(referral_code)
            if referrer and referrer[0] != user_id:  # Can't refer yourself
                referred_by = referrer[0]
        
        # Check if user exists
        existing_user = db.get_user(user_id)
        if existing_user:
            welcome_back_text = f"""
🎉 **Welcome back, {first_name}!**

Current Balance: {existing_user[3]} tokens
Last Activity: {existing_user[7]}

**Quick Actions:**
"""
            
            keyboard = create_inline_keyboard([
                [
                    {'text': '💰 Check Balance', 'callback_data': 'check_balance'},
                    {'text': '💳 Buy Tokens', 'callback_data': 'buy_tokens'}
                ],
                [
                    {'text': '👥 Referral Info', 'callback_data': 'referral_info'},
                    {'text': '📊 My Stats', 'callback_data': 'user_stats'}
                ]
            ])
            
            bot.reply_to(message, welcome_back_text, reply_markup=keyboard)
            return
        
        # Create new user
        user_referral_code = db.create_user(user_id, username, first_name, referred_by)
        
        welcome_text = f"""
🎉 **Welcome to the Bot, {first_name}!**

You've been registered successfully!
💰 Starting tokens: 0
🔗 Your referral code: `{user_referral_code}`

**Available Commands:**
• /balance - Check your token balance
• /buy - Purchase tokens
• /refer - Get referral information

**How to earn tokens:**
• Refer friends (+5 tokens per referral)
• Purchase tokens via UPI

**Your referral link:**
`https://t.me/{bot_info.username}?start={user_referral_code}`
"""
        
        if referred_by:
            welcome_text += f"\n🎁 You were referred! Your referrer got 5 bonus tokens!"
        
        keyboard = create_inline_keyboard([
            [
                {'text': '💳 Buy Tokens', 'callback_data': 'buy_tokens'},
                {'text': '👥 Refer Friends', 'callback_data': 'referral_info'}
            ],
            [
                {'text': '📋 How it Works', 'callback_data': 'how_it_works'}
            ]
        ])
        
        bot.reply_to(message, welcome_text, reply_markup=keyboard)
        logger.info(f"New user registered: {user_id} ({first_name}), referred by: {referred_by}")
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        bot.reply_to(message, "❌ An error occurred during registration. Please try again.")

@bot.message_handler(commands=['balance'])
@rate_limit
@registered_user_only
def balance_command(message):
    """Handle /balance command with enhanced information"""
    try:
        user = db.get_user(message.from_user.id)
        
        # Get referral stats
        referral_stats = db.execute_query(
            "SELECT COUNT(*), COALESCE(SUM(tokens_earned), 0) FROM referrals WHERE referrer_id = ?",
            (user[0],)
        )
        
        total_referrals = referral_stats[0][0] if referral_stats else 0
        referral_earnings = referral_stats[0][1] if referral_stats else 0
        
        balance_text = f"""
💰 **Your Balance & Stats**

**Current Balance:** {user[3]} tokens
**Total Earned:** {user[10]} tokens
**Total Spent:** {user[9]} tokens

**Referral Stats:**
👥 Total Referrals: {total_referrals}
💎 Referral Earnings: {referral_earnings} tokens

🆔 **User ID:** `{user[0]}`
🔗 **Referral Code:** `{user[4]}`

**Your Referral Link:**
`https://t.me/{bot_info.username}?start={user[4]}`
"""
        
        keyboard = create_inline_keyboard([
            [
                {'text': '💳 Buy Tokens', 'callback_data': 'buy_tokens'},
                {'text': '👥 Referral Info', 'callback_data': 'referral_info'}
            ],
            [
                {'text': '📊 Detailed Stats', 'callback_data': 'user_stats'},
                {'text': '🔄 Refresh', 'callback_data': 'check_balance'}
            ]
        ])
        
        bot.reply_to(message, balance_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in balance command: {e}")
        bot.reply_to(message, "❌ Error retrieving balance. Please try again.")

@bot.message_handler(commands=['buy'])
@rate_limit
@registered_user_only
def buy_command(message):
    """Handle /buy command with enhanced package information"""
    try:
        buy_text = f"""
💳 **Purchase Tokens**

**Token Packages:**
• 100 Tokens - ₹10 (₹0.10 per token)
• 500 Tokens - ₹45 (₹0.09 per token) 🔥 **10% OFF**
• 1000 Tokens - ₹80 (₹0.08 per token) 🔥 **20% OFF**
• 2000 Tokens - ₹150 (₹0.075 per token) 🔥 **25% OFF**

**Payment Method:** UPI Only
**UPI ID:** `{config.UPI_ID}`

**How to purchase:**
1. Choose a package below
2. Make payment to UPI ID
3. Send payment screenshot for verification
4. Tokens will be added after verification

⚠️ **Important Notes:**
• Manual verification (1-24 hours)
• Include your User ID in payment description
• Keep payment screenshot ready
• Contact admin if issues occur
"""
        
        keyboard = create_inline_keyboard([
            [
                {'text': '100 Tokens - ₹10', 'callback_data': 'buy_100'},
                {'text': '500 Tokens - ₹45', 'callback_data': 'buy_500'}
            ],
            [
                {'text': '1000 Tokens - ₹80', 'callback_data': 'buy_1000'},
                {'text': '2000 Tokens - ₹150', 'callback_data': 'buy_2000'}
            ],
            [
                {'text': '📋 Payment Instructions', 'callback_data': 'payment_help'},
                {'text': '💬 Contact Admin', 'url': f'tg://user?id={config.ADMIN_ID}'}
            ]
        ])
        
        bot.reply_to(message, buy_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in buy command: {e}")
        bot.reply_to(message, "❌ Error loading purchase options. Please try again.")

@bot.message_handler(commands=['refer'])
@rate_limit
@registered_user_only
def refer_command(message):
    """Handle /refer command with detailed referral information"""
    try:
        user = db.get_user(message.from_user.id)
        
        # Get detailed referral stats
        referral_data = db.execute_query(
            """SELECT u.first_name, u.join_date, r.tokens_earned, r.created_at
               FROM referrals r 
               JOIN users u ON r.referred_id = u.user_id 
               WHERE r.referrer_id = ? 
               ORDER BY r.created_at DESC LIMIT 10""",
            (user[0],)
        )
        
        total_referrals = len(referral_data)
        total_earned = sum(r[2] for r in referral_data)
        
        refer_text = f"""
👥 **Referral Program**

🔗 **Your Referral Code:** `{user[4]}`
📊 **Total Referrals:** {total_referrals}
💰 **Tokens Earned:** {total_earned}
🎯 **Bonus per Referral:** 5 tokens

**How it works:**
1. Share your referral link
2. New users join using your link
3. You get 5 tokens per referral
4. No limit on referrals!

**Your Referral Link:**
`https://t.me/{bot_info.username}?start={user[4]}`
"""
        
        if referral_data:
            refer_text += "\n**Recent Referrals:**\n"
            for ref in referral_data[:5]:
                refer_text += f"• {ref[0]} - {ref[2]} tokens\n"
        
        keyboard = create_inline_keyboard([
            [
                {'text': '📱 Share on Telegram', 'url': f'https://t.me/share/url?url=https://t.me/{bot_info.username}?start={user[4]}&text=🚀 Join this amazing bot and earn tokens!'},
                {'text': '📋 Copy Link', 'callback_data': f'copy_link_{user[4]}'}
            ],
            [
                {'text': '📊 Referral Stats', 'callback_data': 'referral_stats'},
                {'text': '💡 Referral Tips', 'callback_data': 'referral_tips'}
            ]
        ])
        
        bot.reply_to(message, refer_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in refer command: {e}")
        bot.reply_to(message, "❌ Error loading referral information. Please try again.")

# Admin Commands with enhanced functionality

@bot.message_handler(commands=['admin_stats'])
@admin_only
def admin_stats_command(message):
    """Handle /admin_stats command with comprehensive statistics"""
    try:
        # Get comprehensive statistics
        stats_queries = {
            'total_users': "SELECT COUNT(*) FROM users",
            'active_users_24h': "SELECT COUNT(*) FROM users WHERE last_activity > datetime('now', '-1 day')",
            'active_users_7d': "SELECT COUNT(*) FROM users WHERE last_activity > datetime('now', '-7 days')",
            'total_tokens_distributed': "SELECT COALESCE(SUM(tokens), 0) FROM users",
            'total_tokens_earned': "SELECT COALESCE(SUM(total_earned), 0) FROM users",
            'total_tokens_spent': "SELECT COALESCE(SUM(total_spent), 0) FROM users",
            'total_payments': "SELECT COUNT(*) FROM payments",
            'pending_payments': "SELECT COUNT(*) FROM payments WHERE status = 'pending'",
</cut_off_point>
<correct_response>
payments",
            'pending_payments': "SELECT COUNT(*) FROM payments WHERE status = 'pending'",
            'verified_payments': "SELECT COUNT(*) FROM payments WHERE status = 'verified'",
            'total_revenue': "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'verified'",
            'total_referrals': "SELECT COUNT(*) FROM referrals",
            'total_content': "SELECT COUNT(*) FROM content WHERE is_active = 1",
            'total_content_views': "SELECT COALESCE(SUM(views), 0) FROM content"
        }
        
        stats = {}
        for key, query in stats_queries.items():
            result = db.execute_query(query)
            stats[key] = result[0][0] if result else 0
        
        # Get top referrers
        top_referrers = db.execute_query(
            """SELECT u.first_name, u.user_id, COUNT(r.id) as referral_count, SUM(r.tokens_earned) as tokens_earned
               FROM users u 
               JOIN referrals r ON u.user_id = r.referrer_id 
               GROUP BY u.user_id 
               ORDER BY referral_count DESC 
               LIMIT 5"""
        )
        
        stats_text = f"""
📊 **Comprehensive Bot Statistics**

👥 **Users:**
• Total Users: {stats['total_users']:,}
• Active (24h): {stats['active_users_24h']:,}
• Active (7d): {stats['active_users_7d']:,}

💰 **Tokens:**
• Total in Circulation: {stats['total_tokens_distributed']:,}
• Total Earned: {stats['total_tokens_earned']:,}
• Total Spent: {stats['total_tokens_spent']:,}

💳 **Payments:**
• Total Payments: {stats['total_payments']:,}
• Pending: {stats['pending_payments']:,}
• Verified: {stats['verified_payments']:,}
• Total Revenue: ₹{stats['total_revenue']:,.2f}

👥 **Referrals:**
• Total Referrals: {stats['total_referrals']:,}

📁 **Content:**
• Active Content: {stats['total_content']:,}
• Total Views: {stats['total_content_views']:,}
"""
        
        if top_referrers:
            stats_text += "\n🏆 **Top Referrers:**\n"
            for ref in top_referrers:
                stats_text += f"• {ref[0]} (`{ref[1]}`) - {ref[2]} referrals\n"
        
        stats_text += f"\n🕐 **Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        keyboard = create_inline_keyboard([
            [
                {'text': '👥 User Management', 'callback_data': 'admin_users'},
                {'text': '💳 Payment Management', 'callback_data': 'admin_payments'}
            ],
            [
                {'text': '📁 Content Management', 'callback_data': 'admin_content'},
                {'text': '📊 Export Data', 'callback_data': 'admin_export'}
            ],
            [
                {'text': '🔄 Refresh Stats', 'callback_data': 'admin_refresh_stats'},
                {'text': '💾 Backup Database', 'callback_data': 'admin_backup'}
            ]
        ])
        
        bot.reply_to(message, stats_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")
        bot.reply_to(message, f"❌ Error getting statistics: {str(e)}")

@bot.message_handler(commands=['admin_tokens'])
@admin_only
def admin_tokens_command(message):
    """Handle /admin_tokens command with enhanced token management"""
    try:
        args = message.text.split()
        if len(args) < 4:
            help_text = """
💰 **Token Management System**

**Usage:** `/admin_tokens <action> <user_id> <amount> [reason]`

**Actions:**
• `add` - Add tokens to user
• `remove` - Remove tokens from user  
• `set` - Set exact token amount

**Examples:**
• `/admin_tokens add 123456789 100 Purchase bonus`
• `/admin_tokens remove 123456789 50 Refund`
• `/admin_tokens set 123456789 200 Reset balance`

**Bulk Operations:**
• `/admin_tokens bulk_add <amount> [reason]` - Add to all users
• `/admin_tokens bulk_bonus <referral_count> <amount>` - Bonus for top referrers

**Query Operations:**
• `/admin_tokens info <user_id>` - Get user token info
• `/admin_tokens top [limit]` - Show top token holders
"""
            
            bot.reply_to(message, help_text)
            return
        
        action = args[1].lower()
        
        # Handle special actions
        if action == 'info':
            user_id = int(args[2])
            user = db.get_user(user_id)
            if not user:
                bot.reply_to(message, f"❌ User {user_id} not found!")
                return
            
            info_text = format_user_info(user)
            bot.reply_to(message, info_text)
            return
        
        elif action == 'top':
            limit = int(args[2]) if len(args) > 2 else 10
            top_users = db.execute_query(
                "SELECT first_name, user_id, tokens FROM users ORDER BY tokens DESC LIMIT ?",
                (limit,)
            )
            
            top_text = f"🏆 **Top {limit} Token Holders:**\n\n"
            for i, user in enumerate(top_users, 1):
                top_text += f"{i}. {user[0]} (`{user[1]}`) - {user[2]} tokens\n"
            
            bot.reply_to(message, top_text)
            return
        
        # Regular token operations
        user_id = int(args[2])
        amount = int(args[3])
        reason = " ".join(args[4:]) if len(args) > 4 else "Admin action"
        
        # Check if user exists
        user = db.get_user(user_id)
        if not user:
            bot.reply_to(message, f"❌ User {user_id} not found!")
            return
        
        current_tokens = user[3]
        
        if action == 'add':
            db.update_tokens(user_id, amount, reason)
            new_tokens = current_tokens + amount
            action_text = f"Added {amount} tokens"
            
        elif action == 'remove':
            if current_tokens < amount:
                bot.reply_to(message, f"❌ User only has {current_tokens} tokens!")
                return
            db.update_tokens(user_id, -amount, reason)
            new_tokens = current_tokens - amount
            action_text = f"Removed {amount} tokens"
            
        elif action == 'set':
            difference = amount - current_tokens
            db.update_tokens(user_id, difference, reason)
            new_tokens = amount
            action_text = f"Set tokens to {amount}"
            
        else:
            bot.reply_to(message, "❌ Invalid action! Use: add, remove, set, info, or top")
            return
        
        # Notify user
        try:
            notification_text = f"""
💰 **Token Balance Updated**

{action_text}
**Reason:** {reason}
**New Balance:** {new_tokens} tokens

Thank you! 🎉
"""
            safe_send_message(user_id, notification_text)
        except:
            pass  # User might have blocked the bot
        
        success_text = f"""
✅ **Token Operation Successful**

**User:** {user[2]} (`{user_id}`)
**Action:** {action_text}
**Reason:** {reason}
**Previous Balance:** {current_tokens}
**New Balance:** {new_tokens}
"""
        
        bot.reply_to(message, success_text)
        logger.info(f"Admin {message.from_user.id} {action_text} for user {user_id}: {reason}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID or amount! Use numbers only.")
    except Exception as e:
        logger.error(f"Error in admin_tokens: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['admin_upload'])
@admin_only
def admin_upload_command(message):
    """Handle /admin_upload command with enhanced content management"""
    try:
        upload_text = """
📁 **Content Upload System**

**Instructions:**
1. Send a file (photo, video, document, audio)
2. Add a caption with format:
   `TITLE | DESCRIPTION | TOKENS_REQUIRED`

**Example Caption:**
`Premium Python Course | Complete tutorial with examples | 50`

**Supported Formats:**
• 📷 Photos (JPG, PNG, GIF)
• 🎥 Videos (MP4, AVI, MOV)
• 📄 Documents (PDF, DOC, ZIP)
• 🎵 Audio (MP3, WAV, OGG)

**Features:**
• Auto-generated deeplinks
• View tracking
• Channel auto-posting (if configured)
• Access control via tokens

**Tips:**
• Use descriptive titles
• Set appropriate token prices
• Include detailed descriptions
• Test content before sharing
"""
        
        keyboard = create_inline_keyboard([
            [
                {'text': '📊 Content Stats', 'callback_data': 'admin_content_stats'},
                {'text': '📋 Content List', 'callback_data': 'admin_content_list'}
            ],
            [
                {'text': '❌ Cancel Upload', 'callback_data': 'admin_cancel_upload'}
            ]
        ])
        
        bot.reply_to(message, upload_text, reply_markup=keyboard)
        
        # Set user state for next message
        bot.register_next_step_handler(message, handle_admin_upload)
        
    except Exception as e:
        logger.error(f"Error in admin_upload: {e}")
        bot.reply_to(message, "❌ Error initializing upload. Please try again.")

def handle_admin_upload(message):
    """Handle file upload from admin with comprehensive validation"""
    try:
        # Check if upload was cancelled
        if message.text and message.text.lower() in ['/cancel', 'cancel']:
            bot.reply_to(message, "❌ Upload cancelled.")
            return
        
        # Validate file type
        if not message.content_type in ['photo', 'video', 'document', 'audio']:
            bot.reply_to(message, """
❌ **Invalid File Type**

Please send a valid file:
• 📷 Photo
• 🎥 Video  
• 📄 Document
• 🎵 Audio

Or send 'cancel' to abort upload.
""")
            bot.register_next_step_handler(message, handle_admin_upload)
            return
        
        # Validate caption
        if not message.caption:
            bot.reply_to(message, """
❌ **Missing Caption**

Please add a caption with format:
`TITLE | DESCRIPTION | TOKENS_REQUIRED`

Example:
`Premium Course | Advanced Python Tutorial | 50`

Or send 'cancel' to abort upload.
""")
            bot.register_next_step_handler(message, handle_admin_upload)
            return
        
        # Parse caption
        caption_parts = [part.strip() for part in message.caption.split(' | ')]
        if len(caption_parts) != 3:
            bot.reply_to(message, """
❌ **Invalid Caption Format**

Use exactly this format:
`TITLE | DESCRIPTION | TOKENS_REQUIRED`

Make sure to use ` | ` (space-pipe-space) as separator.

Or send 'cancel' to abort upload.
""")
            bot.register_next_step_handler(message, handle_admin_upload)
            return
        
        title, description, tokens_str = caption_parts
        
        # Validate tokens
        try:
            tokens_required = int(tokens_str)
            if tokens_required < 0:
                raise ValueError("Negative tokens not allowed")
        except ValueError:
            bot.reply_to(message, """
❌ **Invalid Token Amount**

Tokens required must be a positive number.

Examples: 10, 50, 100

Or send 'cancel' to abort upload.
""")
            bot.register_next_step_handler(message, handle_admin_upload)
            return
        
        # Get file info
        file_info = None
        file_size = 0
        
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
            file_info = bot.get_file(file_id)
            file_size = message.photo[-1].file_size or 0
        elif message.content_type == 'video':
            file_id = message.video.file_id
            file_info = bot.get_file(file_id)
            file_size = message.video.file_size or 0
        elif message.content_type == 'document':
            file_id = message.document.file_id
            file_info = bot.get_file(file_id)
            file_size = message.document.file_size or 0
        elif message.content_type == 'audio':
            file_id = message.audio.file_id
            file_info = bot.get_file(file_id)
            file_size = message.audio.file_size or 0
        
        # Generate unique deeplink
        deeplink = hashlib.md5(f"{file_id}{time.time()}{title}".encode()).hexdigest()[:12]
        
        # Save to database
        db.execute_query(
            """INSERT INTO content (title, description, file_id, file_type, tokens_required, deeplink, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title, description, file_id, message.content_type, tokens_required, deeplink, config.ADMIN_ID),
            fetch=False
        )
        
        # Update content stats
        db.update_stat('total_content', 1)
        
        # Create access link
        access_link = f"https://t.me/{bot_info.username}?start=content_{deeplink}"
        
        success_text = f"""
✅ **Content Uploaded Successfully!**

📁 **Title:** {title}
📝 **Description:** {description}
💰 **Tokens Required:** {tokens_required}
📊 **File Size:** {file_size / 1024 / 1024:.2f} MB
🔗 **Access Link:** `{access_link}`
🆔 **Deeplink ID:** `{deeplink}`

**Content Details:**
• File Type: {message.content_type.title()}
• Upload Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Status: Active

Content is now available for users!
"""
        
        keyboard = create_inline_keyboard([
            [
                {'text': '📤 Post to Channel', 'callback_data': f'post_channel_{deeplink}'},
                {'text': '👁️ Preview Content', 'callback_data': f'preview_content_{deeplink}'}
            ],
            [
                {'text': '📊 Content Stats', 'callback_data': 'admin_content_stats'},
                {'text': '📋 Manage Content', 'callback_data': 'admin_content_list'}
            ],
            [
                {'text': '📁 Upload More', 'callback_data': 'admin_upload_more'}
            ]
        ])
        
        bot.reply_to(message, success_text, reply_markup=keyboard)
        logger.info(f"Admin uploaded content: {title} ({deeplink}) - {tokens_required} tokens")
        
    except Exception as e:
        logger.error(f"Error in handle_admin_upload: {e}")
        bot.reply_to(message, f"❌ Error uploading content: {str(e)}")

# Enhanced callback handlers

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    """Handle all callback queries with comprehensive error handling"""
    try:
        data = call.data
        user_id = call.from_user.id
        
        # Answer callback query immediately to prevent timeout
        bot.answer_callback_query(call.id)
        
        # Route callbacks to appropriate handlers
        if data.startswith('buy_'):
            handle_buy_callback(call)
        elif data.startswith('admin_'):
            if user_id != config.ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            handle_admin_callback(call)
        elif data.startswith('content_'):
            handle_content_callback(call)
        elif data == 'referral_info':
            handle_referral_info_callback(call)
        elif data == 'check_balance':
            handle_balance_callback(call)
        elif data == 'user_stats':
            handle_user_stats_callback(call)
        elif data.startswith('copy_link_'):
            handle_copy_link_callback(call)
        elif data == 'how_it_works':
            handle_how_it_works_callback(call)
        elif data == 'payment_help':
            handle_payment_help_callback(call)
        elif data == 'start_registration':
            handle_start_registration_callback(call)
        else:
            logger.warning(f"Unhandled callback: {data}")
            bot.answer_callback_query(call.id, "❌ Unknown action!")
        
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred!")

def handle_buy_callback(call):
    """Handle buy token callbacks with enhanced UPI integration"""
    try:
        data = call.data
        user_id = call.from_user.id
        
        # Token packages with enhanced information
        packages = {
            'buy_100': {'tokens': 100, 'price': 10, 'discount': 0, 'popular': False},
            'buy_500': {'tokens': 500, 'price': 45, 'discount': 10, 'popular': True},
            'buy_1000': {'tokens': 1000, 'price': 80, 'discount': 20, 'popular': False},
            'buy_2000': {'tokens': 2000, 'price': 150, 'discount': 25, 'popular': False}
        }
        
        if data not in packages:
            bot.answer_callback_query(call.id, "❌ Invalid package!", show_alert=True)
            return
        
        package = packages[data]
        
        # Create payment record with additional details
        payment_id = db.execute_query(
            """INSERT INTO payments (user_id, amount, tokens, status) 
               VALUES (?, ?, ?, 'pending') RETURNING id""",
            (user_id, package['price'], package['tokens']),
            fetch=True
        )
        
        if not payment_id:
            # Fallback for databases that don't support RETURNING
            payment_id = db.execute_query(
                "SELECT id FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
        
        payment_ref = payment_id[0][0] if payment_id else "Unknown"
        
        # Enhanced payment instructions
        payment_text = f"""
💳 **Payment Instructions**

**Package Details:**
• Tokens: {package['tokens']:,}
• Price: ₹{package['price']}
• Per Token: ₹{package['price']/package['tokens']:.3f}
{f"• Discount: {package['discount']}% OFF 🔥" if package['discount'] > 0 else ""}

**UPI Payment Details:**
• UPI ID: `{config.UPI_ID}`
• Amount: ₹{package['price']}
• Reference: `TOKEN_{payment_ref}_{user_id}`

**Step-by-Step Instructions:**
1. Open any UPI app (GPay, PhonePe, Paytm, etc.)
2. Pay ₹{package['price']} to UPI ID: `{config.UPI_ID}`
3. Add reference: `TOKEN_{payment_ref}_{user_id}`
4. Complete the payment
5. Take a screenshot of successful payment
6. Send the screenshot here for verification

⚠️ **Important Notes:**
• Include the reference number in payment description
• Keep payment screenshot ready
• Verification takes 1-24 hours
• Contact admin if payment not verified within 24 hours
• Do not make duplicate payments

**Payment ID:** `{payment_ref}`
"""
        
        # Create UPI deep link
        upi_link = f"upi://pay?pa={config.UPI_ID}&pn=TokenBot&am={package['price']}&cu=INR&tn=TOKEN_{payment_ref}_{user_id}"
        
        keyboard = create_inline_keyboard([
            [
                {'text': '📱 Pay with UPI App', 'url': upi_link},
                {'text': '📋 Copy UPI ID', 'callback_data': f'copy_upi_{config.UPI_ID}'}
            ],
            [
                {'text': '💬 Contact Admin', 'url': f'tg://user?id={config.ADMIN_ID}'},
                {'text': '❌ Cancel Payment', 'callback_data': f'cancel_payment_{payment_ref}'}
            ],
            [
                {'text': '🔙 Back to Packages', 'callback_data': 'buy_tokens'}
            ]
        ])
        
        bot.edit_message_text(
            payment_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )
        
        logger.info(f"User {user_id} initiated payment {payment_ref} for {package['tokens']} tokens (₹{package['price']})")
        
    except Exception as e:
        logger.error(f"Error in buy callback: {e}")
        bot.answer_callback_query(call.id, "❌ Error processing purchase!", show_alert=True)

def handle_content_deeplink(message):
    """Handle content access via deeplink with enhanced user experience"""
    try:
        deeplink = message.text.split('_')[1]
        user_id = message.from_user.id
        
        # Get content info
        content = db.execute_query(
            "SELECT * FROM content WHERE deeplink = ? AND is_active = 1", (deeplink,)
        )
        
        if not content:
            error_text = """
❌ **Content Not Found**

This content may have been:
• Removed or expired
• Made private
• Invalid link

**What you can do:**
• Check if the link is correct
• Contact the person who shared it
• Browse available content
"""
            
            keyboard = create_inline_keyboard([
                [
                    {'text': '🏠 Go to Main Menu', 'callback_data': 'main_menu'},
                    {'text': '💬 Contact Support', 'url': f'tg://user?id={config.ADMIN_ID}'}
                ]
            ])
            
            bot.reply_to(message, error_text, reply_markup=keyboard)
            return
        
        content_data = content[0]
        title = content_data[1]
        description = content_data[2]
        tokens_required = content_data[5]
        views = content_data[8]
        
        # Check if user is registered
        user = db.get_user(user_id)
        if not user:
            register_text = f"""
📁 **{title}**

{description}

💰 **Required:** {tokens_required} tokens
👁️ **Views:** {views:,}

❌ **You need to register first to access this content.**
"""
            
            keyboard = create_inline_keyboard([
                [{'text': '🚀 Register Now', 'callback_data': 'start_registration'}],
                [{'text': '💡 Learn More', 'callback_data': 'how_it_works'}]
            ])
            
            bot.reply_to(message, register_text, reply_markup=keyboard)
            return
        
        user_tokens = user[3]
        
        # Enhanced content preview
        content_text = f"""
📁 **{title}**

📝 **Description:**
{description}

💰 **Required Tokens:** {tokens_required}
💳 **Your Balance:** {user_tokens}
👁️ **Total Views:** {views:,}
📊 **File Type:** {content_data[4].title()}

**Status:** {'✅ You have enough tokens!' if user_tokens >= tokens_required else '❌ Insufficient tokens!'}
"""
        
        if user_tokens >= tokens_required:
            keyboard = create_inline_keyboard([
                [{'text': f'🔓 Access Content ({tokens_required} tokens)', 'callback_data': f'content_{deeplink}'}],
                [
                    {'text': '💰 Check Balance', 'callback_data': 'check_balance'},
                    {'text': '🔙 Main Menu', 'callback_data': 'main_menu'}
                ]
            ])
        else:
            needed_tokens = tokens_required - user_tokens
            keyboard = create_inline_keyboard([
                [{'text': f'💳 Buy {needed_tokens}+ Tokens', 'callback_data': 'buy_tokens'}],
                [
                    {'text': '👥 Earn via Referrals', 'callback_data': 'referral_info'},
                    {'text': '💰 Check Balance', 'callback_data': 'check_balance'}
                ]
            ])
        
        bot.reply_to(message, content_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in content deeplink: {e}")
        bot.reply_to(message, "❌ Error accessing content!")

# Payment verification with enhanced screenshot handling
@bot.message_handler(content_types=['photo'])
@rate_limit
def handle_payment_screenshot(message):
    """Handle payment screenshot with enhanced verification process"""
    try:
        user_id = message.from_user.id
        
        # Check if user has pending payments
        pending_payments = db.execute_query(
            """SELECT p.*, u.first_name FROM payments p 
               JOIN users u ON p.user_id = u.user_id 
               WHERE p.user_id = ? AND p.status = 'pending' 
               ORDER BY p.created_at DESC LIMIT 1""",
            (user_id,)
        )
        
        if not pending_payments:
            help_text = """
❌ **No Pending Payments Found**

**If you want to purchase tokens:**
1. Use /buy command
2. Select a package
3. Make payment
4. Then send screenshot

**If you already made payment:**
• Make sure you selected a package first
• Check if payment was already verified
• Contact admin if you need help
"""
            
            keyboard = create_inline_keyboard([
                [
                    {'text': '💳 Buy Tokens', 'callback_data': 'buy_tokens'},
                    {'text': '💰 Check Balance', 'callback_data': 'check_balance'}
                ],
                [
                    {'text': '💬 Contact Admin', 'url': f'tg://user?id={config.ADMIN_ID}'}
                ]
            ])
            
            bot.reply_to(message, help_text, reply_markup=keyboard)
            return
        
        payment = pending_payments[0]
        payment_id = payment[0]
        amount = payment[2]
        tokens = payment[3]
        user_name = payment[8]
        
        # Enhanced admin notification
        admin_text = f"""
💳 **Payment Verification Required**

**Payment Details:**
• Payment ID: `{payment_id}`
• User: {user_name} (`{user_id}`)
• Amount: ₹{amount}
• Tokens: {tokens:,}
• Date: {payment[5]}

**User Info:**
• Username: @{message.from_user.username or 'None'}
• First Name: {message.from_user.first_name}

**Quick Actions:**
• `/verify {payment_id}` - Approve payment
• `/reject {payment_id} [reason]` - Reject payment

**Screenshot forwarded below ⬇️**
"""
        
        try:
            # Send admin notification
            bot.send_message(config.ADMIN_ID, admin_text)
            
            # Forward screenshot to admin
            bot.forward_message(config.ADMIN_ID, message.chat.id, message.message_id)
            
            # Enhanced user confirmation
            confirmation_text = f"""
✅ **Payment Screenshot Received!**

**Payment Details:**
• Payment ID: `{payment_id}`
• Amount: ₹{amount}
• Tokens: {tokens:,}
• Status: Pending Verification

**What happens next:**
1. Admin team will verify your payment
2. You'll receive confirmation once verified
3. Tokens will be added automatically
4. You can check status with /balance

⏱️ **Verification Time:** Usually 1-24 hours
💬 **Need Help?** Contact admin if verification takes longer

Thank you for your patience! 🙏
"""
            
            keyboard = create_inline_keyboard([
                [
                    {'text': '💰 Check Balance', 'callback_data': 'check_balance'},
                    {'text': '📊 Payment Status', 'callback_data': f'payment_status_{payment_id}'}
                ],
                [
                    {'text': '💬 Contact Admin', 'url': f'tg://user?id={config.ADMIN_ID}'}
                ]
            ])
            
            bot.reply_to(message, confirmation_text, reply_markup=keyboard)
            
            logger.info(f"Payment screenshot received from user {user_id} for payment {payment_id} (₹{amount})")
            
        except Exception as e:
            logger.error(f"Error forwarding payment screenshot: {e}")
            bot.reply_to(message, """
❌ **Error Processing Screenshot**

There was an issue forwarding your payment screenshot to admin.

**Please try:**
1. Send the screenshot again
2. Contact admin directly
3. Include your Payment ID in message

**Your Payment ID:** `{}`
""".format(payment_id))
        
    except Exception as e:
        logger.error(f"Error handling payment screenshot: {e}")
        bot.reply_to(message, "❌ Error processing payment screenshot. Please try again or contact admin.")

# Enhanced admin payment verification
@bot.message_handler(commands=['verify'])
@admin_only
def verify_payment_command(message):
    """Enhanced payment verification with detailed logging"""
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, """
✅ **Payment Verification**

**Usage:** `/verify <payment_id> [bonus_tokens]`

**Examples:**
• `/verify 123` - Verify payment
• `/verify 123 10` - Verify with 10 bonus tokens

**Quick Commands:**
• `/verify_all` - Show all pending payments
• `/verify_recent` - Show recent payments
""")
            return
        
        payment_id = int(args[1])
        bonus_tokens = int(args[2]) if len(args) > 2 else 0
        
        # Get payment info with user details
        payment = db.execute_query(
            """SELECT p.*, u.first_name, u.username FROM payments p 
               JOIN users u ON p.user_id = u.user_id 
               WHERE p.id = ? AND p.status = 'pending'""", 
            (payment_id,)
        )
        
        if not payment:
            bot.reply_to(message, "❌ Payment not found or already processed!")
            return
        
        payment_data = payment[0]
        user_id = payment_data[1]
        amount = payment_data[2]
        tokens = payment_data[3]
        user_name = payment_data[8]
        username = payment_data[9]
        
        total_tokens = tokens + bonus_tokens
        
        # Update payment status
        db.execute_query(
            """UPDATE payments SET status = 'verified', verified_at = CURRENT_TIMESTAMP, verified_by = ? 
               WHERE id = ?""",
            (config.ADMIN_ID, payment_id),
            fetch=False
        )
        
        # Add tokens to user
        db.update_tokens(user_id, total_tokens, f"Payment verification (ID: {payment_id})")
        
        # Enhanced user notification
        user_notification = f"""
🎉 **Payment Verified Successfully!**

**Payment Details:**
• Payment ID: `{payment_id}`
• Amount Paid: ₹{amount}
• Tokens Received: {tokens:,}
{f"• Bonus Tokens: {bonus_tokens:,} 🎁" if bonus_tokens > 0 else ""}
• **Total Added: {total_tokens:,} tokens**

**Your account has been updated!**
Use /balance to check your new balance.

Thank you for your purchase! 🚀
"""
        
        try:
            safe_send_message(user_id, user_notification)
            notification_sent = "✅"
        except:
            notification_sent = "❌ (User may have blocked bot)"
        
        # Admin confirmation
        admin_confirmation = f"""
✅ **Payment Verified Successfully**

**Payment Details:**
• Payment ID: `{payment_id}`
• User: {user_name} (@{username or 'none'}) [`{user_id}`]
• Amount: ₹{amount}
• Tokens: {tokens:,}
{f"• Bonus: {bonus_tokens:,}" if bonus_tokens > 0 else ""}
• **Total: {total_tokens:,} tokens**

**Actions Completed:**
• Payment marked as verified
• Tokens added to user account
• User notification sent: {notification_sent}

**Verification Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        bot.reply_to(message, admin_confirmation)
        logger.info(f"Admin verified payment {payment_id} for user {user_id} - {total_tokens} tokens added")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid payment ID or bonus amount!")
    except Exception as e:
        logger.error(f"Error in verify_payment: {e}")
        bot.reply_to(message, f"❌ Error verifying payment: {str(e)}")

@bot.message_handler(commands=['reject'])
@admin_only
def reject_payment_command(message):
    """Enhanced payment rejection with detailed reasons"""
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, """
❌ **Payment Rejection**

**Usage:** `/reject <payment_id> [reason]`

**Common Reasons:**
• Invalid screenshot
• Amount mismatch
• Duplicate payment
• Fraudulent transaction
• Insufficient proof

**Example:**
`/reject 123 Amount does not match package price`
""")
            return
        
        payment_id = int(args[1])
        reason = " ".join(args[2:]) if len(args) > 2 else "Payment verification failed"
        
        # Get payment info
        payment = db.execute_query(
            """SELECT p.*, u.first_name, u.username FROM payments p 
               JOIN users u ON p.user_id = u.user_id 
               WHERE p.id = ? AND p.status = 'pending'""", 
            (payment_id,)
        )
        
        if not payment:
            bot.reply_to(message, "❌ Payment not found or already processed!")
            return
        
        payment_data = payment[0]
        user_id = payment_data[1]
        amount = payment_data[2]
        tokens = payment_data[3]
        user_name = payment_data[8]
        username = payment_data[9]
        
        # Update payment status
        db.execute_query(
            """UPDATE payments SET status = 'rejected', verified_at = CURRENT_TIMESTAMP, 
               verified_by = ?, rejection_reason = ? WHERE id = ?""",
            (config.ADMIN_ID, reason, payment_id),
            fetch=False
        )
        
        # Enhanced user notification
        user_notification = f"""
❌ **Payment Rejected**

**Payment Details:**
• Payment ID: `{payment_id}`
• Amount: ₹{amount}
• Tokens: {tokens:,}

**Rejection Reason:**
{reason}

**What you can do:**
• Check the reason above
• Make sure payment details are correct
• Contact admin if you believe this is an error
• Try making a new payment with correct details

**Need Help?** Contact admin for assistance.
"""
        
        keyboard = create_inline_keyboard([
            [
                {'text': '💳 Try Again', 'callback_data': 'buy_tokens'},
                {'text': '💬 Contact Admin', 'url': f'tg://user?id={config.ADMIN_ID}'}
            ]
        ])
        
        try:
            bot.send_message(user_id, user_notification, reply_markup=keyboard)
            notification_sent = "✅"
        except:
            notification_sent = "❌ (User may have blocked bot)"
        
        # Admin confirmation
        admin_confirmation = f"""
❌ **Payment Rejected**

**Payment Details:**
• Payment ID: `{payment_id}`
• User: {user_name} (@{username or 'none'}) [`{user_id}`]
• Amount: ₹{amount}
• Tokens: {tokens:,}

**Rejection Reason:** {reason}
**User Notification Sent:** {notification_sent}
**Rejection Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        bot.reply_to(message, admin_confirmation)
        logger.info(f"Admin rejected payment {payment_id} for user {user_id}: {reason}")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid payment ID!")
    except Exception as e:
        logger.error(f"Error in reject_payment: {e}")
        bot.reply_to(message, f"❌ Error rejecting payment: {str(e)}")

# Additional callback handlers for enhanced functionality
def handle_balance_callback(call):
    """Handle balance check callback"""
    try:
        user = db.get_user(call.from_user.id)
        if not user:
            bot.answer_callback_query(call.id, "❌ User not found!", show_alert=True)
            return
        
        balance_text = f"""
💰 **Current Balance**

**Tokens:** {user[3]:,}
**Total Earned:** {user[10]:,}
**Total Spent:** {user[9]:,}

**Last Updated:** {datetime.now().strftime('%H:%M:%S')}
"""
        
        keyboard = create_inline_keyboard([
            [
                {'text': '💳 Buy More', 'callback_data': 'buy_tokens'},
                {'text': '👥 Earn More', 'callback_data': 'referral_info'}
            ],
            [
                {'text': '📊 Detailed Stats', 'callback_data': 'user_stats'}
            ]
        ])
        
        bot.edit_message_text(
            balance_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in balance callback: {e}")
        bot.answer_callback_query(call.id, "❌ Error checking balance!")

# Error handler for unknown messages
@bot.message_handler(func=lambda message: True)
def handle_unknown_messages(message):
    """Handle unknown messages with helpful guidance"""
    try:
        if message.content_type == 'text':
            help_text = """
❓ **Unknown Command**

**Available Commands:**
• /start - Register and get started
• /balance - Check your token balance  
• /buy - Purchase tokens
• /refer - Referral program info

**Admin Commands:**
• /admin_stats - Bot statistics
• /admin_tokens - Manage user tokens
• /admin_upload - Upload content

**Need Help?**
• Type /start to begin
• Use the buttons in messages for easy navigation
• Contact admin for support

**Quick Actions:**
"""
            
            keyboard = create_inline_keyboard([
                [
                    {'text': '🚀 Start Bot', 'callback_data': 'start_registration'},
                    {'text': '💰 Check Balance', 'callback_data': 'check_balance'}
                ],
                [
                    {'text': '💳 Buy Tokens', 'callback_data': 'buy_tokens'},
                    {'text': '👥 Referrals', 'callback_data': 'referral_info'}
                ],
                [
                    {'text': '💬 Contact Admin', 'url': f'tg://user?id={config.ADMIN_ID}'}
                ]
            ])
            
            bot.reply_to(message, help_text, reply_markup=keyboard)
        else:
            # Handle non-text messages
            bot.reply_to(message, """
📎 **File Received**

If this is a payment screenshot, make sure you:
1. First use /buy to select a package
2. Make the payment
3. Then send the screenshot

For other files, please use the appropriate commands.
""")
    
    except Exception as e:
        logger.error(f"Error handling unknown message: {e}")

# Graceful shutdown handling
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_flag.set()
    
    # Create final database backup
    try:
        backup_path = db.backup_database()
        logger.info(f"Final backup created: {backup_path}")
    except Exception as e:
        logger.error(f"Error creating final backup: {e}")
    
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Health check and monitoring
def health_check():
    """Perform health check"""
    try:
        # Test database connection
        db.execute_query("SELECT 1")
        
        # Test bot connection
        bot.get_me()
        
        return True
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return False

# Main function with enhanced error handling and monitoring
def main():
    """Main function with comprehensive error handling and monitoring"""
    logger.info("=" * 50)
    logger.info("Starting Telegram Bot...")
    logger.info("=" * 50)
    
    # Initialize bot
    if not initialize_bot():
        logger.error("Failed to initialize bot. Exiting...")
        sys.exit(1)
    
    # Perform initial health check
    if not health_check():
        logger.error("Initial health check failed. Exiting...")
        sys.exit(1)
    
    # Create initial database backup
    try:
        backup_path = db.backup_database()
        logger.info(f"Initial backup created: {backup_path}")
    except Exception as e:
        logger.warning(f"Could not create initial backup: {e}")
    
    # Log configuration
    logger.info(f"Bot: @{bot_info.username} ({bot_info.first_name})")
    logger.info(f"Admin ID: {config.ADMIN_ID}")
    logger.info(f"UPI ID: {config.UPI_ID}")
    logger.info(f"Database: {config.DATABASE_PATH}")
    logger.info(f"Rate Limit: {config.RATE_LIMIT_SECONDS}s")
    logger.info(f"Max Retries: {config.MAX_RETRIES}")
    
    # Start bot with enhanced error handling
    retry_count = 0
    max_retries = 5
    
    while retry_count < max_retries and not shutdown_flag.is_set():
        try:
            logger.info("Bot started successfully! Listening for messages...")
            bot.infinity_polling(
                timeout=10, 
                long_polling_timeout=5,
                none_stop=True,
                interval=1
            )
            
        except Exception as e:
            retry_count += 1
            logger.error(f"Bot polling error (attempt {retry_count}/{max_retries}): {e}")
            
            if retry_count < max_retries:
                wait_time = min(60, 2 ** retry_count)  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                
                # Reinitialize bot if needed
                if not initialize_bot():
                    logger.error("Failed to reinitialize bot")
                    continue
            else:
                logger.error("Max retries reached. Exiting...")
                break
    
    logger.info("Bot stopped.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
