from flask import Flask, request, jsonify, render_template, send_from_directory
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
import pytz

# Load environment variables
load_dotenv()

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
DASHBOARD_URL = os.getenv('DASHBOARD_URL')

application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Time in Lebanon
def now_lebanon():
    return datetime.now(pytz.timezone("Asia/Beirut"))

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('🚀 Suppy Automation Bot is running!')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open('logs/integration-log.txt', 'r') as f:
            last_line = f.readlines()[-1]
        await update.message.reply_text(f"📊 Last log entry:\n{last_line}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open("logs/integration-log.txt", "r") as f:
            last_lines = f.readlines()[-50:]
        await update.message.reply_text("📄 Last 50 log lines:\n" + ''.join(last_lines[-10:]))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("status", status))
application.add_handler(CommandHandler("logs", logs))

# Dashboard homepage
@app.route('/')
def dashboard():
    try:
        with open("logs/integration-log.txt", "r") as f:
            logs = f.readlines()[-50:]
    except:
        logs = []

    try:
        csvs = sorted(
            [f for f in os.listdir("logs") if f.endswith(".csv")],
            reverse=True
        )
    except:
        csvs = []

    return render_template(
        "index.html",
        logs=logs,
        csvs=csvs,
        last_updated=now_lebanon().strftime("%Y-%m-%d %H:%M:%S")
    )

# Download route for CSVs
@app.route('/logs/<path:filename>')
def download(filename):
    return send_from_directory('logs', filename, as_attachment=True)

# ✅ Fix: only one /upload-log route
@app.route('/upload-log', methods=['POST'])
def upload_log():
    file = request.files.get('file')
    log_entry = request.form.get('log')

    os.makedirs("logs", exist_ok=True)

    if file:
        file_path = os.path.join("logs", file.filename)
        file.save(file_path)

    if log_entry:
        with open("logs/integration-log.txt", "a") as log_file:
            log_file.write(log_entry + "\n")

    return jsonify(success=True)

@app.post('/telegram-webhook')
async def webhook():
    update = Update.de_json(await request.get_json(), application.bot)
    await application.process_update(update)
    return jsonify(success=True)

if __name__ == '__main__':
    async def post_init(app):
        await application.bot.set_webhook(f"{DASHBOARD_URL}/telegram-webhook")

    application.post_init = post_init
    application.initialize()
    app.run(host='0.0.0.0', port=5000)
