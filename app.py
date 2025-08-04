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

load_dotenv()
lebanon_tz = ZoneInfo("Asia/Beirut")

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)
LAST_SHEET_EDIT_FILE = os.path.join(LOGS_DIR, "last_sheet_edit.txt")

SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = int(os.getenv("PARTNER_ID"))
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SUPPY_LOGIN_URL = "https://portal-api.suppy.app/api/users/login"
SUPPY_UPLOAD_URL = "https://portal-api.suppy.app/api/manual-integration"

app = Flask(__name__)

def send_telegram_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    except Exception as e:
        print("Telegram error:", e, flush=True)

def fetch_google_sheet():
    gc = gspread.service_account(filename="credentials.json")
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.worksheet(SHEET_NAME)
    df = pd.DataFrame(worksheet.get_all_records())
    if 'Product Name' in df.columns:
        df.drop(columns=['Product Name'], inplace=True)
    return df

def get_suppy_token():
    resp = requests.post(SUPPY_LOGIN_URL, json={
        "username": SUPPY_EMAIL,
        "password": SUPPY_PASSWORD,
        "partnerId": PARTNER_ID
    })
    try:
        token = resp.json().get("accessToken") or resp.json().get("data", {}).get("token")
        print("Token acquired:", token, flush=True)
        return token
    except Exception as e:
        print("Token error:", e, flush=True)
        return None

def upload_to_suppy(csv_path, token):
    with open(csv_path, "rb") as f:
        files = {"file": (os.path.basename(csv_path), f, "text/csv")}
        data = {"partnerId": str(PARTNER_ID), "type": "0"}
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(SUPPY_UPLOAD_URL, headers=headers, files=files, data=data)
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(lebanon_tz)}] Suppy upload: {r.status_code} - {r.text}\n")
    return r.status_code, r.text

def upload_to_dashboard(csv_path):
    filename = os.path.basename(csv_path)
    log = f"{datetime.now(lebanon_tz)} Uploaded {filename}"
    with open(csv_path, "rb") as f:
        requests.post(DASHBOARD_URL, files={"file": (filename, f, "text/csv")},
                      data={"filename": filename, "log": log})
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
        f.write(log + "\n")

def run_full_upload():
    try:
        send_telegram_message("▶️ Starting upload...")
        df = fetch_google_sheet()
        timestamp = datetime.now(lebanon_tz).strftime("%Y-%m-%d_%H-%M-%S")
        csv_path = os.path.join(LOGS_DIR, f"{timestamp}.csv")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig", lineterminator="\n")
        token = get_suppy_token()
        if not token:
            send_telegram_message("❌ Could not fetch Suppy token")
            return
        code, msg = upload_to_suppy(csv_path, token)
        upload_to_dashboard(csv_path)
        if code == 200:
            send_telegram_message(f"✅ Upload success: {timestamp}.csv")
        else:
            send_telegram_message(f"❌ Upload failed: {msg}")
    except Exception as e:
        send_telegram_message(f"❌ Upload error: {e}")

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
        print("Sheet edit check error:", e, flush=True)

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.json
    if "message" not in data:
        return "No message", 200
    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    print("Received command:", text, flush=True)
    if str(chat_id) != TELEGRAM_CHAT_ID:
        return "Unauthorized", 403
    if text == "/status":
        now = datetime.now(lebanon_tz).strftime("%Y-%m-%d %H:%M:%S")
        send_telegram_message(f"📡 System OK. Last check: {now}")
    elif text == "/logs":
        log_path = os.path.join(LOGS_DIR, "integration-log.txt")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                send_telegram_message("📜 Log preview:\n" + "".join(f.readlines()[-10:]))
        else:
            send_telegram_message("⚠️ No logs found.")
    elif text == "/upload":
        Thread(target=run_full_upload).start()
        send_telegram_message("⏳ Upload started.")
    return "OK", 200

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

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run-job":
        run_full_upload()
        check_google_sheet_edit()
    else:
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
