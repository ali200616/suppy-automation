import os
import requests
import json
from datetime import datetime

# Microsoft Graph API credentials
TENANT_ID = "156671da-d690-441e-85de-74d6054004b7"
CLIENT_ID = "fe24957b-9d06-496b-a87b-352ce963964d"
CLIENT_SECRET = "Sj68Q~ebA5gAB5s5Nac5ik--ACGZCAFyFSjW8cVb"

# File to monitor
TARGET_FILENAME = "Inventory + Suppy named manual int.xlsx"

# Telegram credentials
TELEGRAM_BOT_TOKEN = "8499565597:AAGTTWSVHB21QlmpF2-iyvjPgY1YMs5x_m8"
TELEGRAM_CHAT_ID = "8294437796"

# Timestamp tracking file
TIMESTAMP_FILE = "last_modified_cache.txt"

def get_graph_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]

def find_file_and_modified_time(token, filename):
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
    while url:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        items = r.json().get("value", [])
        for item in items:
            if item["name"] == filename:
                return item["lastModifiedDateTime"]
        url = r.json().get("@odata.nextLink")
    return None

def send_telegram_alert(message):
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    requests.post(telegram_url, data=payload)

def load_last_timestamp():
    if not os.path.exists(TIMESTAMP_FILE):
        return None
    with open(TIMESTAMP_FILE, "r") as f:
        return f.read().strip()

def save_timestamp(timestamp):
    with open(TIMESTAMP_FILE, "w") as f:
        f.write(timestamp)

def main():
    try:
        print("🔐 Getting Microsoft Graph token...")
        token = get_graph_token()

        print("📂 Checking for file modification...")
        modified_time = find_file_and_modified_time(token, TARGET_FILENAME)

        if not modified_time:
            print("❌ File not found.")
            return

        last_known = load_last_timestamp()
        if modified_time != last_known:
            save_timestamp(modified_time)
            message = f"📄 Excel file '{TARGET_FILENAME}' was modified at:\n{modified_time}"
            send_telegram_alert(message)
            print("✅ Telegram alert sent.")
        else:
            print("✅ No change detected.")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
