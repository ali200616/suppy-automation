import os
import json
import requests
import pandas as pd
import gspread
from flask import Flask, request, render_template, send_from_directory
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo
from threading import Thread

# Load env vars
load_dotenv()

# Timezone
lebanon_tz = ZoneInfo("Asia/Beirut")

# Constants
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)
LAST_SHEET_EDIT_FILE = os.path.join(LOGS_DIR, "last_sheet_edit.txt")

# ENV
SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# URLs
SUPPY_LOGIN_URL = "https://portal-api.suppy.app/api/users/login"
SUPPY_UPLOAD_URL = "https://portal-api.suppy.app/api/manual-integration"

app = Flask(__name__)

# ======================
# 🔁 Shared Functions
# ======================

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        requests.post(url, data=payload)
    except Exception as e:
        print(f"❌ Telegram error: {e}", flush=True)

def fetch_google_sheet():
    gc = gspread.service_account(filename="credentials.json")
    sh = gc.open_by_key(SHEET_ID)
    try:
        worksheet = sh.worksheet(SHEET_NAME)
    except:
        worksheet = sh.get_worksheet(0)
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    if 'Product Name' in df.columns:
        df = df.drop(columns=['Product Name'])
    return df

def get_suppy_token():
    resp = requests.post(
        SUPPY_LOGIN_URL,
        json={"username": SUPPY_EMAIL, "password": SUPPY_PASSWORD, "partnerId": int(PARTNER_ID)}
    )
    print(f"DEBUG: Suppy login response {resp.status_code} - {resp.text}", flush=True)
    data = resp.json()
    return data.get("accessToken") or data.get("data", {}).get("token")

def save_csv(df, filename):
    path = os.path.join(LOGS_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return path

def upload_to_suppy(csv_path, token):
    with open(csv_path, "rb") as f:
        files = {"file": (os.path.basename(csv_path), f, "text/csv")}
        data = {"partnerId": str(PARTNER_ID), "type": "0"}
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(SUPPY_UPLOAD_URL, headers=headers, files=files, data=data)
        print(f"DEBUG: Suppy upload response {r.status_code} - {r.text}", flush=True)
    log_line = f"[{datetime.now(lebanon_tz)}] Suppy upload: {r.status_code} - {r.text}\n"
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
        f.write(log_line)
    return r.status_code, r.text

def upload_to_dashboard(csv_path):
    filename = os.path.basename(csv_path)
    log_line = f"{datetime.now(lebanon_tz).strftime('%Y-%m-%d %H:%M:%S')} Uploaded {filename}"
    with open(csv_path, "rb") as f:
        files = {"file": (filename, f, "text/csv")}
        data = {"filename": filename, "log": log_line}
        requests.post(DASHBOARD_URL, files=files, data=data)
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
        f.write(log_line + "\n")

def run_full_upload():
    try:
        print("▶️ Starting upload process...", flush=True)
        df = fetch_google_sheet()
        timestamp = datetime.now(lebanon_tz).strftime("%Y-%m-%d_%H-%M-%S")
        csv_path = save_csv(df, f"{timestamp}.csv")
        token = get_suppy_token()
        code, response = upload_to_suppy(csv_path, token)
        upload_to_dashboard(csv_path)
        if code == 200:
            send_telegram_message(f"✅ Upload successful.\n{timestamp}.csv")
        else:
            send_telegram_message(f"❌ Suppy upload failed:\n{response}")
    except Exception as e:
        print(f"❌ Upload exception: {e}", flush=True)
        send_telegram_message(f"❌ Upload error: {e}")

# ======================
# 📦 Telegram Webhook
# ======================

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.json
    if not data or "message" not in data:
        return "No message", 200

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")

    print(f"📨 Message received: {text} from {chat_id}", flush=True)

    if str(chat_id) != TELEGRAM_CHAT_ID:
        return "Unauthorized", 403

    if text == "/status":
        now = datetime.now(lebanon_tz).strftime("%Y-%m-%d %H:%M:%S")
        send_telegram_message(f"📡 System is online\nLast check: {now}")
    elif text == "/logs":
        log_path = os.path.join(LOGS_DIR, "integration-log.txt")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-50:]
            send_telegram_message("📜 Last 50 log lines:\n" + "".join(lines[-10:]))
        else:
            send_telegram_message("⚠️ No logs found.")
    elif text == "/upload":
        Thread(target=run_full_upload).start()
        send_telegram_message("⏳ Uploading now...")
    return "OK", 200

# ======================
# 🖥️ Dashboard Routes
# ======================

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

# ======================
# 🔁 Google Sheet Edit Detection
# ======================

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

# ======================
# ▶️ App Runner
# ======================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
