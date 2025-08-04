import os
import pandas as pd
import requests
import gspread
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo

# Timezone
lebanon_tz = ZoneInfo("Asia/Beirut")

# Load environment variables
load_dotenv()
SUPPY_LOGIN_URL = "https://portal-api.suppy.app/api/users/login"
SUPPY_UPLOAD_URL = "https://portal-api.suppy.app/api/manual-integration"
SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LOGS_DIR = "logs"
EDIT_TRACK_FILE = os.path.join(LOGS_DIR, "last_edit.txt")
os.makedirs(LOGS_DIR, exist_ok=True)

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

def fetch_google_sheet(sheet_id, sheet_name=None):
    try:
        gc = gspread.service_account(filename="credentials.json")
        sh = gc.open_by_key(sheet_id)
        worksheet = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        df.drop(columns=["Product Name"], inplace=True, errors="ignore")
        df = df[["BranchIdentifier", "Barcodes", "Quantity", "Price", "CurrencyCode", "MaxOrder", "IsActive"]]
        return df, worksheet.updated
    except Exception as e:
        raise Exception(f"Google Sheets fetch error: {e}")

def check_google_sheet_edit(current_edit_time):
    try:
        last_time = None
        if os.path.exists(EDIT_TRACK_FILE):
            with open(EDIT_TRACK_FILE, "r") as f:
                last_time = f.read().strip()
        if current_edit_time != last_time:
            with open(EDIT_TRACK_FILE, "w") as f:
                f.write(current_edit_time)
            send_telegram(f"📄 Google Sheet was edited at: {current_edit_time}")
    except Exception as e:
        print(f"Edit check failed: {e}")

def get_suppy_token():
    resp = requests.post(SUPPY_LOGIN_URL, json={
        "username": SUPPY_EMAIL,
        "password": SUPPY_PASSWORD,
        "partnerId": int(PARTNER_ID)
    })
    if resp.status_code != 200:
        raise Exception(f"Suppy login failed: {resp.text}")
    data = resp.json()
    return data.get("accessToken") or data.get("data", {}).get("token")

def save_csv(df, filename):
    path = os.path.join(LOGS_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return path

def upload_to_dashboard(csv_path):
    filename = os.path.basename(csv_path)
    log_line = f"{datetime.now(lebanon_tz).strftime('%Y-%m-%d %H:%M:%S')} Uploaded {filename}"
    with open(csv_path, "rb") as f:
        r = requests.post(DASHBOARD_URL, files={"file": (filename, f, "text/csv")},
                          data={"filename": filename, "log": log_line})
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as logf:
        logf.write(log_line + "\n")

def upload_to_suppy(csv_path, token):
    with open(csv_path, "rb") as f:
        response = requests.post(SUPPY_UPLOAD_URL,
                                 headers={"Authorization": f"Bearer {token}"},
                                 files={"file": (os.path.basename(csv_path), f, "text/csv")},
                                 data={"partnerId": str(PARTNER_ID), "type": "0"})
    status = response.status_code
    text = response.text
    log_line = f"[{datetime.now(lebanon_tz).strftime('%Y-%m-%d %H:%M:%S')}] Suppy upload response: {status} - {text}\n"
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as logf:
        logf.write(log_line)
    return status, text

def main():
    try:
        df, updated_time = fetch_google_sheet(SHEET_ID, SHEET_NAME)
        check_google_sheet_edit(updated_time)

        filename = f"{datetime.now(lebanon_tz).strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        csv_path = save_csv(df, filename)

        token = get_suppy_token()
        status, text = upload_to_suppy(csv_path, token)
        upload_to_dashboard(csv_path)

        if status == 200:
            send_telegram(f"✅ Upload success: {filename}")
        else:
            send_telegram(f"❌ Upload failed: {status}\n{text}")
    except Exception as e:
        send_telegram(f"❌ Script error: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
