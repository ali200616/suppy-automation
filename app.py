from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
import os
import logging
from dotenv import load_dotenv
load_dotenv()

# Initialize Flask
app = Flask(__name__)

# Telegram config
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DASHBOARD_URL = os.getenv('DASHBOARD_URL')

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Initialize Telegram bot
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    await update.message.reply_text('🚀 Suppy Automation Bot is running!')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send system status"""
    try:
        with open('logs/integration-log.txt', 'r') as f:
            logs = f.readlines()[-1]
        await update.message.reply_text(f"📊 Last log entry:\n{logs}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ===== FLASK ROUTES =====
@app.route('/')
def dashboard():
    return "Suppy Automation Dashboard"

@app.post('/telegram-webhook')
async def webhook():
    """Handle Telegram updates"""
    update = Update.de_json(await request.get_json(), application.bot)
    await application.process_update(update)
    return jsonify(success=True)

# ===== MAIN SETUP =====
def setup_handlers():
    """Register Telegram command handlers"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))

if __name__ == '__main__':
    # Set up Telegram handlers
    setup_handlers()
    
    # Configure webhook
    async def post_init(app):
        await application.bot.set_webhook(f"{DASHBOARD_URL}/telegram-webhook")
    
    # Start Flask app
    app.run(host='0.0.0.0', port=5000)
