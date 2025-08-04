import os
import logging
import requests
import gspread
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from flask import Flask, render_template, request, send_from_directory, jsonify
import subprocess
import threading
import time

# Load environment variables
load_dotenv()

# Timezone
lebanon_tz = ZoneInfo("Asia/Beirut")

# Constants and environment
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)
LAST_SHEET_EDIT_FILE = os.path.join(LOGS_DIR, "last_sheet_edit.txt")

SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Telegram bot
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# ---------------------
# Shared Functions
# ---------------------

def send_telegram_message(text):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)  # Use the initialized bot
        print(f"✅ Telegram message sent: {text}", flush=True)
    except Exception as e:
        print(f"❌ Telegram error: {e}", flush=True)
        logger.error(f"Telegram message failed: {e}")

def fetch_google_sheet():
    gc = gspread.service_account(filename="credentials.json")
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.worksheet(SHEET_NAME)
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    if 'Product Name' in df.columns:
        df = df.drop(columns=['Product Name'])
    return df

def save_csv(df, filename):
    path = os.path.join(LOGS_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return path

def upload_to_dashboard(csv_path):
    filename = os.path.basename(csv_path)
    log_line = f"{datetime.now(lebanon_tz).strftime('%Y-%m-%d %H:%M:%S')} Uploaded {filename}"
    with open(csv_path, "rb") as f:
        files = {"file": (filename, f, "text/csv")}
        data = {"filename": filename, "log": log_line}
        resp = requests.post(DASHBOARD_URL, files=files, data=data)
        print(f"DEBUG: Dashboard upload response {resp.status_code} - {resp.text}", flush=True)
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
        f.write(log_line + "\n")

def check_google_sheet_edit():
    try:
        gc = gspread.service_account(filename="credentials.json")
        sh = gc.open_by_key(SHEET_ID)
        meta = sh.fetch_sheet_metadata()
        modified_time = meta["modifiedTime"]
        if os.path.exists(LAST_SHEET_EDIT_FILE):
            with open(LAST_SHEET_EDIT_FILE, "r") as f:
                last_time = f.read().strip()
            if modified_time != last_time:
                send_telegram_message("📝 Google Sheet was edited.")
        with open(LAST_SHEET_EDIT_FILE, "w") as f:
            f.write(modified_time)
    except Exception as e:
        print(f"❌ Edit check error: {e}", flush=True)
        logger.error(f"Edit check failed: {e}")

# ---------------------
# Telegram Bot Handlers
# ---------------------

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Hello! I am your automation bot.')

def status(update: Update, context: CallbackContext) -> None:
    # Read the last upload time from the log file (or a dedicated status file)
    try:
        with open("logs/integration-log.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            last_upload_line = next((line for line in reversed(lines) if "Uploaded" in line), "No uploads found.")
            update.message.reply_text(f"System Status:\nLast Upload: {last_upload_line}")
    except FileNotFoundError:
        update.message.reply_text("System Status:\nNo logs found.")
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        update.message.reply_text("Error getting status. Check logs.")

def logs(update: Update, context: CallbackContext) -> None:
    try:
        with open("logs/integration-log.txt", "r", encoding="utf-8") as f:
            last_50_lines = f.readlines()[-50:]
            log_text = "".join(last_50_lines)
            update.message.reply_text(log_text)
    except FileNotFoundError:
        update.message.reply_text("Log file not found.")
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        update.message.reply_text("Error getting logs. Check logs.")

def upload(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Manually triggering upload...")
    # Run main.py in a separate thread to avoid blocking the bot
    threading.Thread(target=run_main_py).start()
    update.message.reply_text("Upload triggered in the background.")

def run_main_py():
    try:
        # Use subprocess.run to execute main.py
        result = subprocess.run(["python", "main.py"], capture_output=True, text=True, check=True)
        # Log the output of main.py
        logger.info(f"main.py output: {result.stdout}")
        send_telegram_message(f"✅ Manual upload completed successfully.\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        error_message = f"❌ Error running main.py: {e.stderr}"
        logger.error(error_message)
        send_telegram_message(error_message)
    except Exception as e:
        error_message = f"❌ Unexpected error running main.py: {e}"
        logger.error(error_message)
        send_telegram_message(error_message)

# ---------------------
# Telegram Bot Setup
# ---------------------

def setup_telegram_handlers(dispatcher):
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("status", status))
    dispatcher.add_handler(CommandHandler("logs", logs))
    dispatcher.add_handler(CommandHandler("upload", upload))

def start_telegram_bot():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    setup_telegram_handlers(dispatcher)

    # Start the Bot
    updater.start_polling()
    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be changed if you use e.g. webhooks
    # updater.idle() # Remove this line for Render deployment

# Start the Telegram bot in a separate thread
threading.Thread(target=start_telegram_bot).start()

# ---------------------
# Flask Routes
# ---------------------

@app.route("/")
def index():
    log_file = os.path.join(LOGS_DIR, "integration-log.txt")
    logs = ""
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            logs = "".join(f.readlines()[-50:])
    files = sorted(os.listdir(LOGS_DIR), reverse=True)
    csv_files = [f for f in files if f.endswith(".csv")]
    return render_template("index.html", logs=logs, csv_files=csv_files)

@app.route("/logs/<path:filename>")
def download_file(filename):
    return send_from_directory(LOGS_DIR, filename, as_attachment=True)

@app.route("/upload-log", methods=["POST"])
def receive_dashboard_upload():
    file = request.files["file"]
    log = request.form["log"]
    file.save(os.path.join(LOGS_DIR, file.filename))
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
        f.write(log + "\n")
    return "OK", 200

# Remove the webhook route.  We're using polling for now.
# @app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
# def telegram_webhook():
#     data = request.json
#     if not data or "message" not in data:
#         return "No message", 200
#
#     msg = data["message"]
#     chat_id = msg["chat"]["id"]
#     text = msg.get("text", "")
#
#     print(f"📨 Message received: {text} from {chat_id}", flush=True)
#
#     if str(chat_id) != TELEGRAM_CHAT_ID:
#         return "Unauthorized", 403
#
#     if text == "/status":
#         now = datetime.now(lebanon_tz).strftime("%Y-%m-%d %H:%M:%S")
#         send_telegram_message(f"📡 System is online\nLast check: {now}")
#     elif text == "/logs":
#         log_path = os.path.join(LOGS_DIR, "integration-log.txt")
#         if os.path.exists(log_path):
#             with open(log_path, "r", encoding="utf-8") as f:
#                 lines = f.readlines()[-50:]
#             send_telegram_message("📜 Last 50 log lines:\n" + "".join(lines[-10:]))
#         else:
#             send_telegram_message("⚠️ No logs found.")
#     return "OK", 200

# ---------------------
# Main Execution
# ---------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run-job":
        df = fetch_google_sheet()
        timestamp = datetime.now(lebanon_tz).strftime("%Y-%m-%d_%H-%M-%S")
        csv_path = save_csv(df, f"{timestamp}.csv")
        upload_to_dashboard(csv_path)
        check_google_sheet_edit()
    else:
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
