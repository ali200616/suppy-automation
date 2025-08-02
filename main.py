import os
import requests
import pandas as pd
import gspread
from dotenv import load_dotenv
from datetime import datetime
import traceback

# Load .env
load_dotenv()

USERNAME = os.environ.get('USERNAME')
PASSWORD = os.environ.get('PASSWORD')
PARTNER_ID = os.environ.get('PARTNER_ID')
SHEET_ID = os.environ.get('SHEET_ID')
SHEET_NAME = os.environ.get('SHEET_NAME')
DASHBOARD_URL = os.environ.get('DASHBOARD_URL', 'https://suppy-automation.onrender.com/upload-log')

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

def log_and_save(log_text, filename=None, df=None):
    # Append to integration log
    with open('logs/integration-log.txt', 'a', encoding='utf-8') as flog:
        flog.write(log_text + "\n")
    # Save CSV if provided
    if filename and df is not None:
        df.to_csv(f'logs/{filename}', index=False)
    elif filename and df is None:
        with open(f'logs/{filename}', 'w', encoding='utf-8') as f:
            f.write("Error\n")

def fetch_sheet():
    try:
        print("📥 Downloading Google Sheet...")
        gc = gspread.service_account(filename='credentials.json')
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet(SHEET_NAME)
        records = ws.get_all_records()
        df = pd.DataFrame(records)
        print(f"✅ Sheet fetched: {len(df)} rows")
        return df
    except Exception as e:
        print("❌ Error fetching sheet:", e)
        traceback.print_exc()
        raise

def login_suppy():
    print("🔑 Logging in to Suppy...")
    resp = requests.post(
        "https://portal-api.suppy.app/api/users/login",
        json={"email": USERNAME, "password": PASSWORD}
    )
    if resp.status_code != 200 or "accessToken" not in resp.json():
        raise Exception(f"Suppy login failed: {resp.text}")
    token = resp.json()["accessToken"]
    print("✅ Suppy login: OK")
    return token

def upload_csv_to_suppy(token, csv_path):
    print("⬆️ Uploading CSV to Suppy...")
    with open(csv_path, 'rb') as f:
        files = {'file': (os.path.basename(csv_path), f, 'text/csv')}
        data = {'partnerId': PARTNER_ID}
        headers = {'Authorization': f'Bearer {token}'}
        resp = requests.post(
            "https://portal-api.suppy.app/api/manual-integration",
            files=files,
            data=data,
            headers=headers
        )
    print("Suppy upload status:", resp.status_code, resp.text)
    if resp.status_code == 200:
        return "Success"
    else:
        raise Exception(f"Suppy upload failed: {resp.text}")

def post_to_dashboard(log_text, filename):
    try:
        with open(f'logs/{filename}', 'rb') as file:
            files = {'file': (filename, file, 'text/csv')}
            data = {'log': log_text, 'filename': filename}
            resp = requests.post(DASHBOARD_URL, files=files, data=data)
            print(f"✅ Dashboard upload: {resp.status_code}")
            if resp.status_code != 200:
                print("Warning: Dashboard POST did not return 200.")
    except Exception as e:
        print("❌ Dashboard upload failed:", e)
        traceback.print_exc()

def main():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    log_entry = f"{now} | "  # Will append result
    filename = f"upload_{now}.csv"
    try:
        df = fetch_sheet()
        if df.empty:
            raise Exception("Google Sheet is empty or could not be loaded.")
        df.to_csv(f"logs/{filename}", index=False)
        token = login_suppy()
        result = upload_csv_to_suppy(token, f"logs/{filename}")
        log_entry += f"Upload OK | Rows: {len(df)}"
        log_and_save(log_entry, filename=filename, df=df)
        post_to_dashboard(log_entry, filename)
    except Exception as e:
        error_fname = f"error_{now}.csv"
        error_text = f"{log_entry} ERROR: {e}"
        log_and_save(error_text, filename=error_fname, df=None)
        post_to_dashboard(error_text, error_fname)
        print("❌ Error:", e)

if __name__ == "__main__":
    main()
