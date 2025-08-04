import requests
import os
from datetime import datetime

def send_telegram_notification(message):
    """Send notification to Telegram."""
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not bot_token or not chat_id:
        return
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send Telegram notification: {e}")

def log_and_notify(message, level="info"):
    """Log message and send Telegram notification if important."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    
    # Write to log file
    with open('logs/integration-log.txt', 'a') as f:
        f.write(log_entry)
    
    # Send notification for errors or important events
    if level.lower() in ["error", "critical", "warning"]:
        send_telegram_notification(f"⚠️ {message}")
    elif level.lower() == "success":
        send_telegram_notification(f"✅ {message}")
    
    print(log_entry.strip())
