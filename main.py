import os
import requests
import pandas as pd
import gspread
import logging
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo
import telegram  # Import the telegram library

# ======================
# 🔧 Configuration
# ======================

load_dotenv()

TZ = ZoneInfo("Asia/Beirut")
LOGS_DIR = "logs"
EDIT_TRACK_FILE = os.path.join(LOGS_DIR, "last_edit.txt")
os.makedirs(LOGS_DIR, exist_ok=True)

SUPPY_EMAIL = os.getenv("SUPPY_EMAIL")
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD")
PARTNER_ID = os.getenv("PARTNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
DASHBOARD_URL = os.getenv("DASHBOARD_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SUPPY_LOGIN_URL = "https://portal-api.suppy.app/api/users/login"
SUPPY_UPLOAD_URL = "https://portal-api.suppy.app/api/manual-integration"

# ======================
# 🪵 Logging
# ======================

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ======================
# 🤖 Telegram Bot
# ======================

bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)  # Initialize the bot

def send_telegram(message: str):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)  # Use the initialized bot
        logger.info(f"Telegram message sent: {message}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")

# ======================
# 📥 Google Sheet
# ======================

def fetch_google_sheet(sheet_id: str, sheet_name: str):
    try:
        gc = gspread.service_account(filename="credentials.json")
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        df.drop(columns=["Product Name"], inplace=True, errors="ignore")
        df = df[
            [
                "BranchIdentifier",
                "Barcodes",
                "Quantity",
                "Price",
                "CurrencyCode",
                "MaxOrder",
                "IsActive",
            ]
        ]
        return df, ws.updated
    except Exception as e:
        logger.error(f"Google Sheet fetch error: {e}")
        raise Exception(f"Google Sheet fetch error: {e}")

def check_google_sheet_edit(current_time: str):
    try:
        if os.path.exists(EDIT_TRACK_FILE):
            with open(EDIT_TRACK_FILE, "r") as f:
                last_time = f.read().strip()
            if last_time == current_time:
                return
        with open(EDIT_TRACK_FILE, "w") as f:
            f.write(current_time)
        send_telegram(f"📄 Google Sheet was edited at: {current_time}")
    except Exception as e:
        logger.error(f"Edit check failed: {e}")
        print(f"Edit check failed: {e}")

# ======================
# 🔐 Suppy API
# ======================

def get_suppy_token() -> str:
    try:
        resp = requests.post(
            SUPPY_LOGIN_URL,
            json={"username": SUPPY_EMAIL, "password": SUPPY_PASSWORD, "partnerId": int(PARTNER_ID)},
        )
        resp.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        data = resp.json()
        token = data.get("accessToken") or data.get("data", {}).get("token")
        if not token:
            raise ValueError("Token not found in response")
        return token
    except requests.exceptions.RequestException as e:
        logger.error(f"Suppy login failed: {e}")
        raise Exception(f"Suppy login failed: {e}")
    except (ValueError, KeyError) as e:
        logger.error(f"Error parsing Suppy login response: {e}")
        raise Exception(f"Error parsing Suppy login response: {e}")

def upload_to_suppy(csv_path: str, token: str):
    try:
        with open(csv_path, "rb") as f:
            response = requests.post(
                SUPPY_UPLOAD_URL,
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (os.path.basename(csv_path), f, "text/csv")},
                data={"partnerId": str(PARTNER_ID), "type": "0"},
            )
            response.raise_for_status()  # Raise HTTPError for bad responses
        log_line = f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}] Suppy upload: {response.status_code} - {response.text}\n"
        with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
            f.write(log_line)
        return response.status_code, response.text
    except requests.exceptions.RequestException as e:
        logger.error(f"Suppy upload failed: {e}")
        raise Exception(f"Suppy upload failed: {e}")

# ======================
# ☁️ Dashboard Upload
# ======================

def upload_to_dashboard(csv_path: str):
    try:
        filename = os.path.basename(csv_path)
        log_line = f"{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} Uploaded {filename}"
        with open(csv_path, "rb") as f:
            response = requests.post(
                DASHBOARD_URL,
                files={"file": (filename, f, "text/csv")},
                data={"filename": filename, "log": log_line},
            )
            response.raise_for_status()
        with open(os.path.join(LOGS_DIR, "integration-log.txt"), "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except requests.exceptions.RequestException as e:
        logger.error(f"Dashboard upload failed: {e}")
        raise Exception(f"Dashboard upload failed: {e}")

# ======================
# 🎯 Main Process
# ======================

def save_csv(df, filename: str) -> str:
    path = os.path.join(LOGS_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return path

def main():
    try:
        df, updated_time = fetch_google_sheet(SHEET_ID, SHEET_NAME)
        check_google_sheet_edit(updated_time)

        timestamp = datetime.now(TZ).strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}.csv"
        csv_path = save_csv(df, filename)

        token = get_suppy_token()
        status, response = upload_to_suppy(csv_path, token)
        upload_to_dashboard(csv_path)

        if status == 200:
            send_telegram(f"✅ Upload success: {filename}")
        else:
            send_telegram(f"❌ Upload failed: {status}\n{response}")
    except Exception as e:
        send_telegram(f"❌ Script error: {e}")
        logger.exception("An error occurred during script execution")  # Log the full exception

# ======================
# ▶️ Entry Point
# ======================

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        send_telegram(f"❌ Fatal script error: {e}")
