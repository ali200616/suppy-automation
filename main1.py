
from suppy_token_selenium import get_suppy_token
import requests
import os
from dotenv import load_dotenv

load_dotenv()

SUPPY_TOKEN = get_suppy_token()

if not SUPPY_TOKEN:
    print("❌ Failed to get token. Exiting.")
    exit(1)

headers = {
    "Authorization": SUPPY_TOKEN,
    "portal-v2": "true",
    "Content-Type": "application/json"
}

# Your existing logic here (from original main.py):
import os
import pandas as pd
import requests
from datetime import datetime
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CSV_DIR = "logs"
LOG_FILE = os.path.join(CSV_DIR, "integration-log.txt")
os.makedirs(CSV_DIR, exist_ok=True)

def send_telegram_notification(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

def log_and_notify(message, level="info"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}\n"
    with open(LOG_FILE, "a") as f:
        f.write(entry)
    if level in ["error", "critical", "warning", "success"]:
        prefix = "✅" if level == "success" else "⚠️"
        send_telegram_notification(f"{prefix} {message}")
    print(entry.strip())

def get_suppy_token():
    try:
        headers = {
            "Content-Type": "application/json",
            "portal-v2": "true"
        }
        res = requests.post("https://portal-api.suppy.app/api/users/login", json={
            "email": SUPPY_EMAIL,
            "password": SUPPY_PASSWORD
        }, headers=headers)
        res.raise_for_status()
        return res.json().get("token")
    except Exception as e:
        log_and_notify(f"Failed to get Suppy token: {e}", "error")
        if res is not None:
            log_and_notify(f"Status Code: {res.status_code}", "error")
            log_and_notify(f"Response Body: {res.text}", "error")
        return None

def download_and_prepare_csv():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ])
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        data = sheet.get_all_values()
        df = pd.DataFrame(data[1:], columns=data[0])
        df.drop(columns=["Product Name"], inplace=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        csv_path = os.path.join(CSV_DIR, f"suppy_upload_{timestamp}.csv")
        df.to_csv(csv_path, index=False)
        return csv_path
    except Exception as e:
        log_and_notify(f"Failed to download/prepare CSV: {e}", "error")
        return None

def upload_to_suppy(token, csv_path):
    try:
        with open(csv_path, "rb") as f:
            files = {"file": (os.path.basename(csv_path), f)}
            res = requests.post(
                "https://portal-api.suppy.app/api/manual-integration",
                headers=headers,
                files=files,
                data={"partnerId": PARTNER_ID}
            )
        res.raise_for_status()
        log_and_notify(f"CSV successfully uploaded to Suppy: {os.path.basename(csv_path)}", "success")
    except Exception as e:
        log_and_notify(f"Failed to upload to Suppy: {e}", "error")

def upload_to_dashboard(csv_path):
    try:
        with open(csv_path, "rb") as f:
            files = {"file": f}
            res = requests.post(DASHBOARD_URL, files=files)
            res.raise_for_status()
            log_and_notify(f"CSV uploaded to dashboard: {os.path.basename(csv_path)}")
    except Exception as e:
        log_and_notify(f"Failed to upload to dashboard: {e}", "warning")

def run():
    csv_path = download_and_prepare_csv()
    if not csv_path:
        return
    token = get_suppy_token()
    if not token:
        return
    upload_to_suppy(token, csv_path)
    upload_to_dashboard(csv_path)

run()