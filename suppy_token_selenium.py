import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json

SUPPY_EMAIL = "alihoujairytw@gmail.com"
SUPPY_PASSWORD = "4480fHtkqQ8R1iVC"

def get_suppy_token():
    options = uc.ChromeOptions()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = uc.Chrome(options=options, headless=False)

    try:
        print("🔄 Opening portal...")
        driver.get("https://portal.suppy.app")

        wait = WebDriverWait(driver, 30)

        print("⏳ Waiting for input fields...")
        inputs = wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, "v-field__input")))
        if len(inputs) < 2:
            print("❌ Could not locate both input fields.")
            return None

        print("⌨️ Typing email and password...")
        inputs[0].send_keys(SUPPY_EMAIL)
        inputs[1].send_keys(SUPPY_PASSWORD)

        # Blur input to trigger validation (required for button to activate)
        driver.execute_script("arguments[0].blur();", inputs[1])
        time.sleep(1)

        print("🖱️ Waiting for Sign In button...")
        sign_in_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[.//span[text()="Sign In"]]')))
        sign_in_btn.click()

        print("⏳ Waiting for login to complete...")
        time.sleep(5)

        print("🔍 Checking network logs for token...")
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                message = json.loads(entry["message"])["message"]
                if message["method"] == "Network.requestWillBeSent":
                    headers = message["params"]["request"].get("headers", {})
                    auth_header = headers.get("Authorization") or headers.get("authorization")
                    if auth_header:
                        print(f"✅ Token found in request headers: {auth_header}")
                        return auth_header
            except:
                continue

        print("❌ Token not found in network logs.")
        return None

    finally:
        driver.quit()

if __name__ == "__main__":
    token = get_suppy_token()
    print("🔐 Final Result:", token or "Token not found")
