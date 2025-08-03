import os
import pandas as pd
import requests
import gspread
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

# Timezone for Beirut
lebanon_tz = ZoneInfo("Asia/Beirut")

# Load environment variables
load_dotenv()

# Environment variables
SUPPY_LOGIN_URL = "https://portal-api.suppy.app/api/users/login"
SUPPY_UPLOAD_URL = "https://portal-api.suppy.app/api/manual-integration"
SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

def fetch_google_sheet(sheet_id, sheet_name=None):
    try:
        print("📥 Downloading Google Sheet...")
        gc = gspread.service_account(filename="credentials.json")
        sh = gc.open_by_key(sheet_id)
        worksheet_names = [w.title for w in sh.worksheets()]
        print("Available worksheet tabs:", worksheet_names)
        worksheet = None
        if sheet_name:
            try:
                worksheet = sh.worksheet(sheet_name)
            except Exception as e:
                print(f"❌ Could not find worksheet named '{sheet_name}'. Using the first worksheet instead.")
                worksheet = sh.get_worksheet(0)
        else:
            worksheet = sh.get_worksheet(0)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        print(f"✅ Sheet fetched: {len(df)} rows from tab '{worksheet.title}'")
        return df
    except Exception as e:
        print(f"❌ Google Sheets fetch error: {e}")
        raise

def get_suppy_token():
    print("🔑 Logging in to Suppy...")
    resp = requests.post(
        SUPPY_LOGIN_URL,
        json={
            "username": SUPPY_EMAIL,
            "password": SUPPY_PASSWORD,
            "partnerId": int(PARTNER_ID)
        }
    )
    print("Suppy login status:", resp.status_code)
    print("Suppy login text:", resp.text)
    if resp.status_code != 200:
        raise Exception(f"Suppy login failed: {resp.text}")
    data = resp.json()
    token = None
    if "accessToken" in data:
        token = data["accessToken"]
    elif "data" in data and "token" in data["data"]:
        token = data["data"]["token"]
    if not token:
        raise Exception(f"Suppy login response missing token: {resp.text}")
    print("✅ Suppy login: OK")
    return token

def save_csv(df, filename):
    path = os.path.join(LOGS_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig", line_terminator="\n")
    print(f"✅ Data saved to {path}")
    return path

def upload_to_dashboard(csv_path):
    print("⬆️ Uploading to dashboard...")
    filename = os.path.basename(csv_path)
    log_line = f"{datetime.now(lebanon_tz).strftime('%Y-%m-%d %H:%M:%S')} Uploaded {filename}"

    with open(csv_path, "rb") as f:
        files = {"file": (filename, f, "text/csv")}
        data = {"filename": filename, "log": log_line}
        r = requests.post(DASHBOARD_URL, files=files, data=data)

    print(f"✅ Dashboard upload: {r.status_code}")
    if r.status_code != 200:
        print("❌ Dashboard upload failed:", r.text)

    # Also log locally
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as logf:
        logf.write(log_line + "\n")

def upload_to_suppy(csv_path, token):
    print("📤 Uploading CSV to Suppy...")
    with open(csv_path, "rb") as f:
        files = {
            "file": (os.path.basename(csv_path), f, "text/csv")
        }
        data = {
            "partnerId": str(PARTNER_ID),
            "type": "0"
        }
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = requests.post(SUPPY_UPLOAD_URL, headers=headers, files=files, data=data)

    print(f"📡 Suppy upload status: {response.status_code}")
    print(f"📨 Suppy response: {response.text}")

    # Log the response to integration-log.txt
    log_line = f"[{datetime.now(lebanon_tz).strftime('%Y-%m-%d %H:%M:%S')}] Suppy upload response: {response.status_code} - {response.text}\n"
    with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as logf:
        logf.write(log_line)

def main():
    df = fetch_google_sheet(SHEET_ID, SHEET_NAME)
    timestamp = datetime.now(lebanon_tz).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.csv"
    csv_path = save_csv(df, filename)

    token = get_suppy_token()
    upload_to_suppy(csv_path, token)
    upload_to_dashboard(csv_path)

if __name__ == "__main__":
    main()
