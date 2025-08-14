import os
from pathlib import Path
from datetime import datetime
import pytz
from flask import Flask, request, render_template, send_from_directory, abort, jsonify

# --- Paths ---
BASE = Path(os.path.dirname(__file__) or ".").resolve()
STATIC = BASE / "static"
TEMPLATES = BASE  # index.html in project root (same as before)
UPLOADS = BASE / "uploads"
LOGS = BASE / "logs"
UPLOADS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
STATIC.mkdir(parents=True, exist_ok=True)

STATUS_LOG = LOGS / "status.log"

# --- App ---
app = Flask(__name__, static_folder=str(STATIC), template_folder=str(TEMPLATES))

def now_beirut():
    return datetime.now(pytz.timezone("Asia/Beirut")).strftime("%Y-%m-%d %H:%M:%S")

def append_status(status: str, msg: str):
    """
    EXACTLY one line:
    [SUCCESS|FAILED] yyyy-mm-dd HH:MM:SS - message
    """
    line = f"[{status.upper()}] {now_beirut()} - {msg}\n"
    prev = STATUS_LOG.read_text(encoding="utf-8") if STATUS_LOG.exists() else ""
    STATUS_LOG.write_text(prev + line, encoding="utf-8")

def get_status_lines(n=100):
    if not STATUS_LOG.exists():
        return []
    lines = STATUS_LOG.read_text(encoding="utf-8").splitlines()
    return lines[-n:]

def list_csvs():
    items = []
    for p in sorted(UPLOADS.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = p.stat()
        size_kb = max(1, stat.st_size // 1024)
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        items.append({"name": p.name, "size_kb": size_kb, "mtime": mtime})
    return items

@app.get("/")
def index():
    return render_template(
        "index.html",
        lines=get_status_lines(100),
        csvs=list_csvs(),
        last_updated=now_beirut()
    )

@app.post("/upload")
def upload_csv():
    """
    Saves CSV file; status is NOT written here (script posts to /log).
    """
    if "file" not in request.files:
        abort(400, "No file")
    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        abort(400, "Only .csv allowed")
    dest = UPLOADS / f.filename
    f.save(dest)
    return "OK", 200

@app.post("/log")
def post_log():
    """
    Accepts a single-line status from your script.
    JSON: {"status":"success"|"failed","message":"...","filename":"..."}
    """
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).lower()
    message = str(data.get("message", "")).strip()
    filename = str(data.get("filename", "")).strip()
    if status not in ("success", "failed"):
        abort(400, "status must be success or failed")
    suffix = f" file={filename}" if filename else ""
    append_status(status, f"{message}{suffix}")
    return jsonify({"ok": True})

@app.get("/download/<path:filename>")
def download(filename):
    p = UPLOADS / filename
    if not p.exists():
        abort(404)
    return send_from_directory(str(UPLOADS), filename, as_attachment=True)

@app.get("/health")
def health():
    return {"ok": True, "time": now_beirut()}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
