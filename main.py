import os
import requests
import pandas as pd
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

load_dotenv()

# Load env vars
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Create logs dir
os.makedirs("logs", exist_ok=True)

# Send Telegram message
def send_telegram_message(text):
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", params={"chat_id": CHAT_ID, "text": text})

def now_lebanon():
    return datetime.now(pytz.timezone("Asia/Beirut"))

try:
    # Load Google Sheet
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    CREDENTIALS_PATH = 'credentials.json'

    # ✅ Create credentials.json from env var
    import json
    credentials_content = os.getenv("CREDENTIALS_JSON")
    if not credentials_content:
        raise Exception("Missing CREDENTIALS_JSON environment variable.")
    with open(CREDENTIALS_PATH, "w") as f:
        f.write(credentials_content)

    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_PATH, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    data = sheet.get_all_values()
    headers, rows = data[0], data[1:]

    # Remove column C
    cleaned_data = [row[:2] + row[3:] for row in rows]
    cleaned_headers = headers[:2] + headers[3:]
    df = pd.DataFrame(cleaned_data, columns=cleaned_headers)

    # Save CSV
    now_str = now_lebanon().strftime("%Y%m%d_%H%M%S")
    csv_name = f"logs/upload_{now_str}.csv"
    df.to_csv(csv_name, index=False)

    # Login to Suppy
    login = requests.post("https://portal-api.suppy.app/api/users/login", json={"username": SUPPY_EMAIL, "password": SUPPY_PASSWORD})
    if login.status_code != 200:
        raise Exception(f"Suppy login failed: {login.text}")
    token = login.json().get('data', {}).get('token')
    if not token:
        raise Exception(f"Login response missing token: {login.text}")

    # Upload to Suppy
    with open(csv_name, 'rb') as f:
        upload = requests.post(
            "https://portal-api.suppy.app/api/manual-integration",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (csv_name, f)},
            data={"partner_id": PARTNER_ID}
        )
    if upload.status_code != 200:
        raise Exception(f"Suppy upload failed: {upload.text}")

    # Upload to dashboard
    with open(csv_name, 'rb') as f:
        dashboard_upload = requests.post(
            f"{DASHBOARD_URL}/upload-log",
            files={"file": (os.path.basename(csv_name), f, 'text/csv')},
            data={"log": f"[SUCCESS] {now_str} File uploaded: {csv_name}"}
        )
    print("📤 Dashboard upload status:", dashboard_upload.status_code)
    print("📤 Dashboard response:", dashboard_upload.text)
    if dashboard_upload.status_code != 200:
        raise Exception(f"Dashboard upload failed: {dashboard_upload.status_code} - {dashboard_upload.text}")

    # Success
    send_telegram_message(f"✅ Upload succeeded at {now_str}\nFile: {os.path.basename(csv_name)}")
    with open("logs/integration-log.txt", "a") as log:
        log.write(f"[SUCCESS] {now_str} File uploaded: {csv_name}\n")

except Exception as e:
    err = f"❌ Upload failed: {str(e)}"
    send_telegram_message(err)
    with open("logs/integration-log.txt", "a") as log:
        log.write(f"[ERROR] {now_lebanon()} {str(e)}\n")
