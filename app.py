import os
import traceback
from pathlib import Path
from datetime import datetime
import pytz
from flask import Flask, request, render_template, send_from_directory, abort, jsonify

# --- Paths ---
BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
TEMPLATES = BASE              # index.html sits next to this file
UPLOADS = BASE / "uploads"
LOGS = BASE / "logs"
UPLOADS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
STATIC.mkdir(parents=True, exist_ok=True)

STATUS_LOG = LOGS / "status.log"
ERROR_LOG = LOGS / "error.log"

# --- App ---
app = Flask(__name__, static_folder=str(STATIC), template_folder=str(TEMPLATES))

def now_beirut_str() -> str:
    return datetime.now(pytz.timezone("Asia/Beirut")).strftime("%Y-%m-%d %H:%M:%S")

def append_status_line(status: str, msg: str):
    """ONE line only: [SUCCESS|FAILED] yyyy-mm-dd HH:MM:SS - message"""
    line = f"[{status.upper()}] {now_beirut_str()} - {msg}\n"
    prev = STATUS_LOG.read_text(encoding="utf-8") if STATUS_LOG.exists() else ""
    STATUS_LOG.write_text(prev + line, encoding="utf-8")

def read_status_lines(n=100):
    if not STATUS_LOG.exists():
        return []
    lines = STATUS_LOG.read_text(encoding="utf-8").splitlines()
    return lines[-n:]

def list_csvs():
    items = []
    for p in sorted(UPLOADS.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = p.stat()
        items.append({
            "name": p.name,
            "size_kb": max(1, stat.st_size // 1024),
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return items

@app.errorhandler(Exception)
def handle_exception(e):
    # Log full traceback so 500s aren’t blind
    tb = "".join(traceback.format_exception(e))
    prev = ERROR_LOG.read_text(encoding="utf-8") if ERROR_LOG.exists() else ""
    ERROR_LOG.write_text(prev + f"[{now_beirut_str()}] {e}\n{tb}\n", encoding="utf-8")
    return ("Internal Server Error", 500)

@app.get("/")
def index():
    return render_template(
        "index.html",
        lines=read_status_lines(100),
        csvs=list_csvs(),
        last_updated=now_beirut_str(),
        year=datetime.now().year,
        has_logo=(STATIC / "logo.png").exists()
    )

@app.post("/upload")
def upload_csv():
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
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).lower()
    message = str(data.get("message", "")).strip()
    filename = str(data.get("filename", "")).strip()
    if status not in ("success", "failed"):
        abort(400, "status must be success or failed")
    suffix = f" file={filename}" if filename else ""
    append_status_line(status, f"{message}{suffix}")
    return jsonify({"ok": True})

@app.get("/download/<path:filename>")
def download(filename):
    p = UPLOADS / filename
    if not p.exists():
        abort(404)
    return send_from_directory(str(UPLOADS), filename, as_attachment=True)

@app.get("/health")
def health():
    return {"ok": True, "time": now_beirut_str()}

@app.get("/debug/errors")
def debug_errors():
    if not ERROR_LOG.exists():
        return {"errors": []}
    return {"errors": ERROR_LOG.read_text(encoding="utf-8").splitlines()[-200:]}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
