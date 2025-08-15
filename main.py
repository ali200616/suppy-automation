import os
import json
import csv
import requests
import pandas as pd
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone
import pytz
from pathlib import Path
import traceback

# ================== Setup & ENV ==================
load_dotenv()

# Google Sheet
SHEET_ID   = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")  # empty -> first sheet

# MI routing
BRANCH_ID  = os.getenv("BRANCH_ID")
PARTNER_ID = os.getenv("PARTNER_ID")
MI_TYPE    = os.getenv("MI_TYPE", "0")

# Suppy auth (auto-login; no fixed token)
SUPPY_AUTH_URL = os.getenv("SUPPY_AUTH_URL", "https://portal-api.suppy.app/api/users/login")
SUPPY_EMAIL    = os.getenv("SUPPY_EMAIL", "").strip()
SUPPY_PASSWORD = os.getenv("SUPPY_PASSWORD", "").strip()
SUPPY_MI_URL   = os.getenv("SUPPY_MI_URL", "https://portal-api.suppy.app/api/manual-integration")

# Dashboard + Telegram
DASHBOARD_URL      = os.getenv("DASHBOARD_URL", "").strip().rstrip("/")
DASH_API_KEY       = os.getenv("DASH_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# CSV knobs
MI_CSV_HEADER   = os.getenv("MI_CSV_HEADER", "1").strip()
MI_LINE_ENDING  = os.getenv("MI_LINE_ENDING", "CRLF").strip()
MI_QUOTING      = os.getenv("MI_QUOTING", "ALL").strip()
MI_SEP          = os.getenv("MI_SEP", ",").strip()

BASE_DIR = Path(os.path.dirname(__file__) or ".").resolve()
EXPORTS  = BASE_DIR / "exports"
LOGS     = BASE_DIR / "logs"
EXPORTS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

TOKEN_FILE = LOGS / "suppy_token.json"

# ================== Utils & Logging ==================
TZ = pytz.timezone("Asia/Beirut")

def now_lebanon() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def _append_log(line: str):
    p = LOGS / "integration-log.txt"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line)

def log_line(kind: str, msg: str):
    line = f"[{kind}] {now_lebanon()} {msg}\n"
    _append_log(line)
    print(line, end="")

def send_telegram_message(text: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
    except Exception:
        pass

# -------- Dashboard helpers --------
def post_dashboard_status(status: str, message: str, filename: str = ""):
    if not DASHBOARD_URL:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if DASH_API_KEY:
            headers["X-API-Key"] = DASH_API_KEY
        r = requests.post(
            f"{DASHBOARD_URL}/log",
            data=json.dumps({"status": status, "message": message, "filename": filename}),
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            log_line("WARN", f"/log HTTP {r.status_code}: {r.text[:400]}")
    except Exception as e:
        log_line("WARN", f"/log exception: {e}")

def upload_to_dashboard(csv_path: Path) -> bool:
    if not DASHBOARD_URL:
        log_line("WARN", "DASHBOARD_URL not set; skipping dashboard upload.")
        return False
    try:
        headers = {}
        if DASH_API_KEY:
            headers["X-API-Key"] = DASH_API_KEY
        with open(csv_path, "rb") as f:
            r = requests.post(
                f"{DASHBOARD_URL}/upload",
                files={"file": (csv_path.name, f, "text/csv")},
                headers=headers,
                timeout=120,
            )
        if r.status_code == 200:
            post_dashboard_status("success", f"Uploaded CSV to dashboard: {csv_path.name}", csv_path.name)
            return True
        else:
            post_dashboard_status("failed", f"Dashboard upload HTTP {r.status_code}: {r.text[:800]}", csv_path.name)
            return False
    except Exception as e:
        post_dashboard_status("failed", f"Dashboard upload exception: {e}", csv_path.name)
        return False

# ================== Google Sheet -> DataFrame ==================
def download_sheet_as_dataframe() -> pd.DataFrame:
    scope = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    cred_path = BASE_DIR / "credentials.json"
    if not cred_path.exists():
        raise FileNotFoundError("credentials.json not found in project directory.")
    credentials = ServiceAccountCredentials.from_json_keyfile_name(str(cred_path), scope)
    gc = gspread.authorize(credentials)

    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(SHEET_NAME) if SHEET_NAME else sh.sheet1
    values = ws.get_all_values()
    if not values:
        raise RuntimeError("Google Sheet is empty.")

    headers = values[0]
    rows    = values[1:]
    c_idx = 2
    if len(headers) <= c_idx:
        raise RuntimeError(f"Sheet has no column C. Headers: {headers}")

    norm_rows = []
    for r in rows:
        if len(r) < len(headers):
            r = r + [""] * (len(headers) - len(r))
        elif len(r) > len(headers):
            r = r[:len(headers)]
        norm_rows.append(r)

    out_headers  = headers[:c_idx] + headers[c_idx+1:]
    out_rows     = [r[:c_idx] + r[c_idx+1:] for r in norm_rows]

    df = pd.DataFrame(out_rows, columns=out_headers)
    if df.empty:
        raise RuntimeError("After dropping column C, dataframe is empty.")

    if "Barcodes" in df.columns:
        df["Barcodes"] = df["Barcodes"].astype(str).str.strip()

    return df

def _quoting_mode():
    return {
        "ALL": csv.QUOTE_ALL,
        "MINIMAL": csv.QUOTE_MINIMAL,
        "NONNUMERIC": csv.QUOTE_NONNUMERIC,
        "NONE": csv.QUOTE_NONE,
    }.get(MI_QUOTING.upper(), csv.QUOTE_ALL)

def write_csv(df: pd.DataFrame) -> Path:
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    name  = f"{(SHEET_NAME or 'Local').replace(' ','_')}_{stamp}.csv"
    path  = EXPORTS / name

    include_header = MI_CSV_HEADER == "1"
    lineterm = "\r\n" if MI_LINE_ENDING.upper() == "CRLF" else "\n"
    quoting = _quoting_mode()

    df.to_csv(
        path,
        index=False,
        header=include_header,
        encoding="utf-8",
        lineterminator=lineterm,
        quoting=quoting,
        sep=MI_SEP,
    )

    log_line("INFO",  f"CSV rows: {len(df)}")
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            first = f.readline().rstrip("\r\n")
            second = f.readline().rstrip("\r\n")
        log_line("DEBUG", f"CSV first line: {first}")
        log_line("DEBUG", f"CSV second line: {second}")
    except Exception:
        pass

    return path

# ================== Suppy Auth (auto; self-healing) ==================
def _load_cached_token() -> str:
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            token = data.get("token", "")
            exp   = data.get("expires_at")
            if token and exp and datetime.fromisoformat(exp) > datetime.now(timezone.utc):
                return token
        except Exception:
            pass
    return ""

def _save_cached_token(token: str, ttl_hours: int = 12):
    exp = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    TOKEN_FILE.write_text(json.dumps({"token": token, "expires_at": exp.isoformat()}), encoding="utf-8")

def _login_and_get_token() -> str:
    if not (SUPPY_EMAIL and SUPPY_PASSWORD):
        raise RuntimeError("Suppy credentials missing. Set SUPPY_EMAIL and SUPPY_PASSWORD in .env.")
    resp = requests.post(
        SUPPY_AUTH_URL,
        json={"username": SUPPY_EMAIL, "password": SUPPY_PASSWORD},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Auth HTTP {resp.status_code}: {resp.text[:800]}")
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"Auth returned non-JSON body: {resp.text[:800]}")

    token = (
        data.get("token") or data.get("access_token") or
        (isinstance(data.get("data"), dict) and (data["data"].get("token") or data["data"].get("access_token"))) or
        (isinstance(data.get("result"), dict) and (data["result"].get("token") or data["result"].get("access_token"))) or
        data.get("accessToken") or
        (isinstance(data.get("data"), dict) and data["data"].get("accessToken")) or
        (isinstance(data.get("result"), dict) and data["result"].get("accessToken"))
    )
    if not token:
        raise RuntimeError(f"No token found in auth response: {json.dumps(data)[:800]}")
    _save_cached_token(token)
    return token

def get_suppy_token() -> str:
    cached = _load_cached_token()
    if cached:
        return cached
    return _login_and_get_token()

# ================== MI Upload ==================
def upload_to_suppy_mi(csv_path: Path) -> dict:
    if not (BRANCH_ID and PARTNER_ID):
        raise RuntimeError("BRANCH_ID or PARTNER_ID missing; cannot upload to Suppy MI.")
    def do_post(token: str):
        data  = {"branchId": str(BRANCH_ID), "partnerId": str(PARTNER_ID), "type": str(MI_TYPE)}
        headers = {"Accept": "application/json", "portal-v2": "true"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with open(csv_path, "rb") as f:
            files = {"file": (csv_path.name, f, "text/csv")}
            return requests.post(SUPPY_MI_URL, headers=headers, data=data, files=files, timeout=120)

    token = get_suppy_token()
    resp = do_post(token)
    if resp.status_code == 401:
        log_line("WARN", "MI returned 401. Re-authenticating and retrying once.")
        token = _login_and_get_token()
        resp = do_post(token)

    # surface non-200s
    if resp.status_code != 200:
        raise RuntimeError(f"Suppy MI HTTP {resp.status_code}: {resp.text[:800]}")

    try:
        body = resp.json()
        return {"chunks": [body]}
    except Exception:
        raw = resp.text or ""
        log_line("WARN", f"Suppy MI returned non-JSON body: {raw[:800]}")
        return {"chunks": [raw]}

# ================== Main ==================
if __name__ == "__main__":
    try:
        log_line("INFO", "Job started.")
        post_dashboard_status("info", "Job started")

        # 1) Fetch data
        df = download_sheet_as_dataframe()
        log_line("INFO", f"Columns after drop-C: {list(df.columns)} | Rows: {len(df)}")

        # 2) Write CSV
        csv_path = write_csv(df)
        log_line("INFO", f"CSV written: {csv_path.name}")

        # 3) Upload to DASHBOARD FIRST (so Files shows even if Suppy fails)
        uploaded = upload_to_dashboard(csv_path)
        if not uploaded:
            log_line("WARN", "Dashboard upload did not return 200. Check DASHBOARD_URL / DASH_API_KEY.")

        # 4) Upload to Suppy MI (best effort)
        try:
            if not BRANCH_ID:
                raise RuntimeError("BRANCH_ID is empty; Suppy MI will reject. Set BRANCH_ID.")
            mi_body = upload_to_suppy_mi(csv_path)
            log_line("INFO", f"Suppy MI response: {json.dumps(mi_body)[:1200]}")
            post_dashboard_status("success", "Suppy MI upload OK", csv_path.name)
        except Exception as e:
            msg = f"Suppy MI upload failed: {e}"
            log_line("ERROR", msg)
            post_dashboard_status("failed", msg, csv_path.name)

        # 5) Done
        msg = f"✅ Completed. File: {csv_path.name} • Rows: {len(df)}"
        send_telegram_message(msg)
        log_line("SUCCESS", msg)
        post_dashboard_status("success", msg, csv_path.name)

    except Exception as e:
        err = f"❌ Upload failed: {e}"
        send_telegram_message(err)
        log_line("ERROR", f"{e}\n{traceback.format_exc()}")
        post_dashboard_status("failed", str(e))
        raise
