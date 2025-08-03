import os
import requests
from datetime import datetime, timezone

# Microsoft Graph API credentials
TENANT_ID = "156671da-d690-441e-85de-74d6054004b7"
CLIENT_ID = "fe24957b-9d06-496b-a87b-352ce963964d"
CLIENT_SECRET = "Sj68Q~ebA5gAB5s5Nac5ik--ACGZCAFyFSjW8cVb"

# File to monitor
TARGET_FILENAME = "Inventory + Suppy named manual int.xlsx"

# Telegram credentials
TELEGRAM_BOT_TOKEN = "8499565597:AAGTTWSVHB21QlmpF2-iyvjPgY1YMs5x_m8"
TELEGRAM_CHAT_ID = "8294437796"

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
    # Use user-specific endpoint instead of /me/
    url = "https://graph.microsoft.com/v1.0/users/houjairydata@outlook.com/drive/root/children"
    print(f"🔍 Checking OneDrive URL: {url}")
    
    while url:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        items = r.json().get("value", [])
        for item in items:
            print(f"📁 Found: {item['name']}")
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

def main():
    try:
        print("🔐 Getting Microsoft Graph token...")
        token = get_graph_token()

        print("📂 Checking for file modification...")
        modified_time_str = find_file_and_modified_time(token, TARGET_FILENAME)

        if not modified_time_str:
            print("❌ File not found.")
            return

        # Convert to datetime
        last_modified = datetime.strptime(modified_time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        last_modified = last_modified.replace(tzinfo=timezone.utc)
        now = datetime.utcnow().replace(tzinfo=timezone.utc)

        print(f"🕒 Last modified: {last_modified} | Now: {now}")

        # Compare time
        if (now - last_modified).total_seconds() < 3600:
            message = f"📄 OneDrive Excel file '{TARGET_FILENAME}' was modified at:\n{modified_time_str}"
            send_telegram_alert(message)
            print("✅ Telegram alert sent.")
        else:
            print("✅ No recent modification in last hour.")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
