import os
import pandas as pd
import requests
import gspread
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+
lebanon_tz = ZoneInfo("Asia/Beirut")

# Load environment variables
load_dotenv()

SUPPY_LOGIN_URL = "https://portal-api.suppy.app/api/users/login"
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
    # CHANGE: Look for token in the correct place
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
    df.to_csv(path, index=False)
    print(f"✅ Data saved to {path}")
    return path

def upload_to_dashboard(csv_path):
    print("⬆️ Uploading to dashboard...")
    with open(csv_path, "rb") as f:
        files = {"file": (os.path.basename(csv_path), f, "text/csv")}
        r = requests.post(DASHBOARD_URL, files=files)
    print(f"✅ Dashboard upload: {r.status_code}")
    if r.status_code != 200:
        print("⚠️ Dashboard returned:", r.text)
    return r.status_code

def main():
    try:
        # Fetch the Google Sheet with better error handling and worksheet listing
        df = fetch_google_sheet(SHEET_ID, SHEET_NAME)
        csv_name = f"export_{datetime.now(lebanon_tz).strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = save_csv(df, csv_name)
        upload_to_dashboard(csv_path)
        token = get_suppy_token()
        # You can now use the token for further Suppy API actions here
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
