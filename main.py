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

# Optional: dashboard + Telegram
DASHBOARD_URL      = os.getenv("DASHBOARD_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# CSV knobs (defaults chosen to KEEP HEADERS)
MI_CSV_HEADER   = os.getenv("MI_CSV_HEADER", "1").strip()     # "1" -> include header, "0" -> no header
MI_LINE_ENDING  = os.getenv("MI_LINE_ENDING", "CRLF").strip() # "CRLF" or "LF"
MI_QUOTING      = os.getenv("MI_QUOTING", "ALL").strip()      # "ALL"|"MINIMAL"|"NONNUMERIC"|"NONE"
MI_SEP          = os.getenv("MI_SEP", ",").strip()            # "," or ";" etc.

BASE_DIR = Path(os.path.dirname(__file__) or ".").resolve()
EXPORTS  = BASE_DIR / "exports"
LOGS     = BASE_DIR / "logs"
EXPORTS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

TOKEN_FILE = LOGS / "suppy_token.json"

# ================== Utils & Logging ==================
def now_lebanon() -> str:
    tz = pytz.timezone("Asia/Beirut")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

def _append_log(line: str):
    p = LOGS / "integration-log.txt"
    prev = p.read_text(encoding="utf-8") if p.exists() else ""
    p.write_text(prev + line, encoding="utf-8")

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

    # Robustly drop column C (zero-based index 2) and keep ALL others in the SAME order
    c_idx = 2
    if len(headers) <= c_idx:
        raise RuntimeError(f"Sheet has no column C. Headers: {headers}")

    # Normalize each row to header length (pad/truncate)
    norm_rows = []
    for r in rows:
        if len(r) < len(headers):
            r = r + [""] * (len(headers) - len(r))
        elif len(r) > len(headers):
            r = r[:len(headers)]
        norm_rows.append(r)

    # Remove C from headers and each row
    out_headers  = headers[:c_idx] + headers[c_idx+1:]
    out_rows     = [r[:c_idx] + r[c_idx+1:] for r in norm_rows]

    df = pd.DataFrame(out_rows, columns=out_headers)

    if df.empty:
        raise RuntimeError("After dropping column C, dataframe is empty.")

    # Only minimal safety casts to avoid breaking formats:
    # Keep Barcodes as string to preserve leading zeros; leave every other column AS-IS.
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
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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

    # Log head & tail to prove ALL rows included
    head = df.head(5).to_csv(index=False)
    tail = df.tail(5).to_csv(index=False)
    log_line("DEBUG", f"Preview (head 5):\n{head}")
    log_line("DEBUG", f"Preview (tail 5):\n{tail}")
    log_line("INFO",  f"CSV rows sent: {len(df)} | First barcode: {df.iloc[0].get('Barcodes','N/A')} | Last barcode: {df.iloc[-1].get('Barcodes','N/A')}")

    # Also show first two lines as actually written
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            first = f.readline().rstrip("\r\n")
            second = f.readline().rstrip("\r\n")
        log_line("DEBUG", f"CSV first line (file): {first}")
        log_line("DEBUG", f"CSV second line (file): {second}")
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
        json={"username": SUPPY_EMAIL, "password": SUPPY_PASSWORD},  # NOTE: username, not email
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

# ================== Weird MI response helpers ==================
def _parse_possibly_concatenated_json(text: str):
    """
    MI sometimes returns two JSON blobs concatenated.
    Split and parse all; return list of dicts.
    """
    chunks = []
    buf = (text or "").strip()
    if not buf:
        return chunks
    # try direct
    try:
        chunks.append(json.loads(buf))
        return chunks
    except Exception:
        pass
    # split on '}{'
    parts, start = [], 0
    for i in range(len(buf) - 1):
        if buf[i] == '}' and buf[i+1] == '{':
            parts.append(buf[start:i+1])
            start = i+1
    parts.append(buf[start:])
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            chunks.append(json.loads(p))
        except Exception:
            # give up on bad fragments silently
            pass
    return chunks

def _any_success(chunks):
    for c in chunks:
        if not isinstance(c, dict):
            continue
        if c.get("success") is True:
            return True
        if c.get("status") in (True, "ok", "success", "SUCCESS"):
            return True
        data = c.get("data")
        if isinstance(data, dict) and data.get("success") in (True, "ok", "success", "SUCCESS"):
            return True
    return False

# ================== Uploads ==================
def upload_to_suppy_mi(csv_path: Path) -> dict:
    def do_post(token: str):
        files = {"file": (csv_path.name, open(csv_path, "rb"), "text/csv")}
        data  = {
            "branchId": str(BRANCH_ID or ""),
            "partnerId": str(PARTNER_ID or ""),
            "type":     str(MI_TYPE),
        }
        headers = {"Accept": "application/json", "portal-v2": "true"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return requests.post(SUPPY_MI_URL, headers=headers, data=data, files=files, timeout=120)

    token = get_suppy_token()
    resp = do_post(token)
    if resp.status_code == 401:
        log_line("WARN", "MI returned 401. Re-authenticating and retrying once.")
        token = _login_and_get_token()
        resp = do_post(token)

    if resp.status_code != 200:
        raise RuntimeError(f"Suppy MI HTTP {resp.status_code}: {resp.text[:800]}")

    # Parse response robustly
    try:
        body = resp.json()
        chunks = [body]
    except Exception:
        raw = resp.text or ""
        log_line("WARN", f"Suppy MI returned non-JSON body: {raw[:800]}")
        chunks = _parse_possibly_concatenated_json(raw)

    if not chunks:
        raise RuntimeError("MI returned empty/unknown response body.")

    if not _any_success(chunks):
        raise RuntimeError(f"MI returned no success chunk: {json.dumps(chunks)[:1200]}")

    return {"chunks": chunks}

def upload_to_dashboard(csv_path: Path):
    if not DASHBOARD_URL:
        return
    try:
        resp = requests.post(
            f"{DASHBOARD_URL.rstrip('/')}/upload",
            files={"file": (csv_path.name, open(csv_path, "rb"), "text/csv")},
            data={"log": f"[SUCCESS] {now_lebanon()} File uploaded: {csv_path.name}"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Dashboard upload HTTP {resp.status_code}: {resp.text[:500]}")
        log_line("INFO", f"Dashboard accepted {csv_path.name}")
    except Exception as e:
        log_line("WARN", f"Dashboard upload failed: {e}")

# ================== Main ==================
if __name__ == "__main__":
    try:
        log_line("INFO", "Job started.")

        df = download_sheet_as_dataframe()
        log_line("INFO", f"Columns after drop-C: {list(df.columns)} | Total rows: {len(df)}")

        csv_path = write_csv(df)
        log_line("INFO", f"CSV written: {csv_path.name}")

        mi_body = upload_to_suppy_mi(csv_path)
        log_line("INFO", f"Suppy MI response chunks: {json.dumps(mi_body)[:1200]}")

        upload_to_dashboard(csv_path)

        msg = f"✅ Upload completed\nFile: {csv_path.name}\nRows: {len(df)}\nTime: {now_lebanon()}"
        send_telegram_message(msg)
        log_line("SUCCESS", msg)

    except Exception as e:
        err = f"❌ Upload failed: {e}"
        send_telegram_message(err)
        log_line("ERROR", str(e))
        raise
