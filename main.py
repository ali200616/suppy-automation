import os
import requests
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")

def get_bearer_token():
    res = requests.post("https://portal-api.suppy.app/api/users/login", json={
        "email": USERNAME,
        "password": PASSWORD
    })
    res.raise_for_status()
    return res.json()["token"]

def download_google_sheet():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"
    df = pd.read_csv(url)
    filename = f"integration_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    df.to_csv(filename, index=False)
    return filename

def upload_to_suppy(token, filepath):
    with open(filepath, 'rb') as f:
        response = requests.post("https://portal-api.suppy.app/api/manual-integration",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "file": (os.path.basename(filepath), f),
                "partnerId": (None, PARTNER_ID),
                "type": (None, "0")
            }
        )
    response.raise_for_status()
    return "✅ Upload successful - " + datetime.now().strftime('%Y-%m-%d %H:%M')

def push_to_dashboard(log_text, filepath):
    try:
        with open(filepath, 'rb') as f:
            res = requests.post("https://suppy-automation.onrender.com/upload-log",
                data={"log": log_text, "filename": os.path.basename(filepath)},
                files={"file": f})
        res.raise_for_status()
        print("✅ Sent to dashboard")
    except Exception as e:
        print("❌ Failed to send to dashboard:", e)

def main():
    try:
        token = get_bearer_token()
        filepath = download_google_sheet()
        result = upload_to_suppy(token, filepath)
        push_to_dashboard(result, filepath)
    except Exception as e:
        fail_msg = f"❌ Upload failed - {datetime.now().strftime('%Y-%m-%d %H:%M')} - {str(e)}"
        push_to_dashboard(fail_msg, "empty.csv")  # you can leave this empty if no file

if __name__ == "__main__":
    main()
