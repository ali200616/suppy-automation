import os
import requests
import pandas as pd
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

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

# Create logs dir if missing
os.makedirs("logs", exist_ok=True)

def send_telegram_message(text):
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", params={
        "chat_id": CHAT_ID,
        "text": text
    })

try:
    # Load Google Sheet
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    data = sheet.get_all_values()
    headers, rows = data[0], data[1:]

    # Remove column C (index 2)
    cleaned_data = [row[:2] + row[3:] for row in rows]
    cleaned_headers = headers[:2] + headers[3:]
    df = pd.DataFrame(cleaned_data, columns=cleaned_headers)

    # Save CSV
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_name = f"logs/upload_{now}.csv"
    df.to_csv(csv_name, index=False)

    # Suppy login
    login = requests.post("https://portal-api.suppy.app/api/users/login", json={
        "username": SUPPY_EMAIL,
        "password": SUPPY_PASSWORD
    })

    if login.status_code != 200:
        raise Exception(f"Suppy login failed: {login.text}")

    token = login.json().get('data', {}).get('token')
    if not token:
        raise Exception(f"Login response missing token: {login.text}")

    # Upload to Suppy
    with open(csv_name, 'rb') as f:
        upload = requests.post("https://portal-api.suppy.app/api/manual-integration",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (csv_name, f)},
            data={"partner_id": PARTNER_ID}
        )

    if upload.status_code != 200:
        raise Exception(f"Suppy upload failed: {upload.text}")

    # Upload to dashboard
    dashboard_upload = requests.post(f"{DASHBOARD_URL}/upload-log",
        files={"file": open(csv_name, 'rb')},
        data={"log": f"[SUCCESS] {now} File uploaded: {csv_name}"}
    )

    if dashboard_upload.status_code != 200:
        raise Exception("Dashboard upload failed.")

    msg = f"✅ Upload succeeded at {now}\nFile: {os.path.basename(csv_name)}"
    send_telegram_message(msg)

    with open("logs/integration-log.txt", "a") as log:
        log.write(f"[SUCCESS] {now} File uploaded: {csv_name}\n")

except Exception as e:
    err = f"❌ Upload failed: {str(e)}"
    send_telegram_message(err)
    with open("logs/integration-log.txt", "a") as log:
        log.write(f"[ERROR] {datetime.now()} {str(e)}\n")
