# 🚀 Advanced Telegram Bot with Token Economy

A production-ready Telegram bot with comprehensive admin panel, token economy, referral system, and UPI payment integration.

## ✨ Features

### 🔥 Core Features
- **Complete User Management System**
- **Advanced Token Economy**
- **Referral Program with Bonuses**
- **UPI Payment Integration**
- **Content Management System**
- **Admin Panel with Analytics**

### 🛡️ Security & Performance
- **Rate Limiting & Spam Protection**
- **Comprehensive Error Handling**
- **Database Connection Pooling**
- **Graceful Shutdown Handling**
- **Health Check Monitoring**
- **Automatic Database Backups**

### 📊 Advanced Analytics
- **Real-time Statistics**
- **User Activity Tracking**
- **Payment Analytics**
- **Content Performance Metrics**
- **Referral Analytics**

## 🚀 Quick Setup

### 1. Create Telegram Bot
\`\`\`bash
# Message @BotFather on Telegram
/newbot
# Follow instructions and get your bot token
\`\`\`

### 2. Get Your Admin ID
\`\`\`bash
# Message @userinfobot to get your user ID
\`\`\`

### 3. Configure Environment
\`\`\`bash
# Copy and edit .env file
cp .env.example .env
# Edit with your details:
# BOT_TOKEN=your_bot_token
# ADMIN_ID=your_user_id
# UPI_ID=your_upi_id
\`\`\`

### 4. Install & Run
\`\`\`bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py
\`\`\`

## 💳 Token Packages

| Package | Tokens | Price | Per Token | Discount |
|---------|--------|-------|-----------|----------|
| Starter | 100 | ₹10 | ₹0.100 | - |
| Popular | 500 | ₹45 | ₹0.090 | 10% 🔥 |
| Premium | 1000 | ₹80 | ₹0.080 | 20% 🔥 |
| Ultimate | 2000 | ₹150 | ₹0.075 | 25% 🔥 |

## 🎯 User Commands

| Command | Description |
|---------|-------------|
| `/start [referral_code]` | Register and start using the bot |
| `/balance` | Check token balance and stats |
| `/buy` | Purchase token packages |
| `/refer` | Get referral information and link |

## 🔧 Admin Commands

| Command | Description |
|---------|-------------|
| `/admin_stats` | Comprehensive bot statistics |
| `/admin_tokens <action> <user_id> <amount>` | Manage user tokens |
| `/admin_upload` | Upload premium content |
| `/verify <payment_id>` | Verify user payment |
| `/reject <payment_id> [reason]` | Reject user payment |

### Token Management Examples
\`\`\`bash
# Add tokens
/admin_tokens add 123456789 100 Welcome bonus

# Remove tokens  
/admin_tokens remove 123456789 50 Refund

# Set exact amount
/admin_tokens set 123456789 200 Reset balance

# Get user info
/admin_tokens info 123456789

# Show top holders
/admin_tokens top 10
\`\`\`

## 📁 Content Management

### Upload Content
1. Use `/admin_upload`
2. Send file with caption: `TITLE | DESCRIPTION | TOKENS_REQUIRED`
3. Example: `Premium Course | Advanced Python Tutorial | 50`

### Supported File Types
- 📷 Photos (JPG, PNG, GIF)
- 🎥 Videos (MP4, AVI, MOV)
- 📄 Documents (PDF, DOC, ZIP)
- 🎵 Audio (MP3, WAV, OGG)

## 💰 Payment Process

### For Users
1. Select token package with `/buy`
2. Make UPI payment to provided ID
3. Send payment screenshot
4. Wait for admin verification (1-24 hours)
5. Tokens added automatically after verification

### For Admins
1. Receive payment notification with screenshot
2. Verify payment details
3. Use `/verify <payment_id>` to approve
4. Use `/reject <payment_id> [reason]` to reject
5. User gets automatic notification

## 🔒 Security Features

- **Rate Limiting**: Prevents spam (configurable)
- **Admin Protection**: Secure admin-only commands
- **Input Validation**: Comprehensive data validation
- **Error Recovery**: Automatic retry mechanisms
- **Database Security**: SQL injection prevention
- **Graceful Shutdown**: Clean shutdown handling

## 📊 Database Schema

### Tables
- `users` - User information and balances
- `payments` - Payment records and verification
- `content` - Premium content management
- `referrals` - Referral tracking and bonuses
- `bot_stats` - Bot usage statistics

### Indexes
- Optimized for fast queries
- Referral code lookups
- Payment status filtering
- User activity tracking

## 🔧 Configuration Options

\`\`\`env
# Core Settings
BOT_TOKEN=your_bot_token
ADMIN_ID=your_admin_id
UPI_ID=your_upi_id

# Optional Settings
CHANNEL_ID=@your_channel
DATABASE_PATH=bot.db
LOG_LEVEL=INFO
RATE_LIMIT_SECONDS=2
MAX_RETRIES=3
\`\`\`

## 📝 Logging

- **Comprehensive Logging**: All actions logged
- **Error Tracking**: Detailed error information
- **Performance Monitoring**: Response time tracking
- **Security Logging**: Unauthorized access attempts
- **File Rotation**: Automatic log file management

### Log Files
- `logs/bot.log` - General bot activity
- `logs/error.log` - Error-specific logs

## 🔄 Backup System

- **Automatic Backups**: On startup and shutdown
- **Manual Backups**: Admin command available
- **Backup Location**: `backups/` directory
- **Timestamp Format**: `bot_backup_YYYYMMDD_HHMMSS.db`

## 🚨 Error Handling

- **Database Errors**: Connection retry with exponential backoff
- **API Errors**: Rate limit handling and retry logic
- **User Errors**: Friendly error messages with guidance
- **System Errors**: Graceful degradation and recovery

## 📈 Monitoring

### Health Checks
- Database connectivity
- Bot API connectivity
- System resource usage

### Performance Metrics
- Response times
- Error rates
- User activity patterns
- Payment success rates

## 🛠️ Troubleshooting

### Common Issues

**Bot not responding:**
- Check BOT_TOKEN in .env
- Verify bot is not stopped by BotFather
- Check internet connectivity

**Database errors:**
- Ensure write permissions for database file
- Check disk space
- Verify database file integrity

**Payment issues:**
- Verify UPI_ID is correct
- Check admin ID configuration
- Ensure payment screenshots are clear

### Debug Mode
\`\`\`bash
# Enable debug logging
LOG_LEVEL=DEBUG python main.py
\`\`\`

## 🔮 Advanced Features

### Bulk Operations
- Bulk token distribution
- Mass user notifications
- Batch content uploads

### Analytics Dashboard
- User growth metrics
- Revenue analytics
- Content performance
- Referral effectiveness

### API Integration
- Webhook support
- External payment gateways
- Third-party analytics

## 📞 Support

### Getting Help
1. Check logs in `logs/` directory
2. Verify configuration in `.env`
3. Test with debug mode enabled
4. Contact developer for technical support

### Contributing
- Report bugs via GitHub issues
- Submit feature requests
- Contribute code improvements
- Help with documentation

## 📄 License

This project is for educational purposes. Modify as needed for your use case.

---

**Made with ❤️ for the Telegram Bot community**
