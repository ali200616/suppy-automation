import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load .env variables
load_dotenv()

USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")


# Get data from Google Sheet
def get_google_sheet():
    creds = Credentials.from_service_account_file("credentials.json", scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    return sheet.get_all_records()


# Save sheet data to CSV
def save_to_csv(data, filename):
    df = pd.DataFrame(data)
    path = os.path.join("logs", filename)
    df.to_csv(path, index=False)
    return path


# Login to Suppy API and get token
def login_to_suppy():
    response = requests.post("https://portal-api.suppy.app/api/users/login", json={
        "email": USERNAME,
        "password": PASSWORD
    })
    return response.json().get("accessToken")


# Upload the CSV file to Suppy
def upload_csv_to_suppy(csv_file_path, token):
    with open(csv_file_path, 'rb') as f:
        files = {'file': f}
        data = {'partnerId': PARTNER_ID, 'type': '0'}
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.post("https://portal-api.suppy.app/api/manual-integration",
                                 headers=headers, data=data, files=files)
        return response.status_code, response.text


# Push log and CSV to the dashboard
def push_to_dashboard(filepath, log_text):
    try:
        with open(filepath, 'rb') as f:
            res = requests.post("https://suppy-automation.onrender.com/upload-log", data={
                "log": log_text,
                "filename": os.path.basename(filepath)
            }, files={"file": f})
            print("✅ Dashboard upload:", res.status_code)
    except Exception as e:
        print("❌ Dashboard error:", e)


# Main job
def main():
    if not os.path.exists("logs"):
        os.makedirs("logs")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    csv_filename = f"upload_{timestamp}.csv"
    csv_path = os.path.join("logs", csv_filename)

    try:
        print("📥 Downloading Google Sheet...")
        records = get_google_sheet()

        print("📄 Saving to CSV...")
        csv_path = save_to_csv(records, csv_filename)

        print("🔐 Logging in to Suppy...")
        token = login_to_suppy()
        if not token:
            raise Exception("Login failed: No token")

        print("📤 Uploading CSV to Suppy...")
        status, message = upload_csv_to_suppy(csv_path, token)

        log_text = f"{timestamp} | Status: {status} | Message: {message}"
        print("📝", log_text)
        push_to_dashboard(csv_path, log_text)

    except Exception as e:
        print("❌ Error:", e)
        log_text = f"{timestamp} | ERROR: {e}"

        # Create an error CSV for the dashboard
        empty_path = os.path.join("logs", f"error_{timestamp}.csv")
        with open(empty_path, "w") as f:
            f.write("Error")

        push_to_dashboard(empty_path, log_text)


# Run
if __name__ == "__main__":
    main()
