import os
import traceback
from pathlib import Path
from datetime import datetime
import pytz
from flask import Flask, request, render_template, send_from_directory, abort, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
import markdown as md
import secrets
from flask import session
import bleach

tz = pytz.timezone("Asia/Beirut")

# --- Paths ---
BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
TEMPLATES = BASE / "templates"
UPLOADS = BASE / "uploads"
LOGS = BASE / "logs"
EXPORTS = BASE / "exports"
UPLOADS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
STATIC.mkdir(parents=True, exist_ok=True)
EXPORTS.mkdir(parents=True, exist_ok=True)

STATUS_LOG = LOGS / "status.log"
ERROR_LOG = LOGS / "error.log"

# --- App ---
app = Flask(__name__, static_folder=str(STATIC), template_folder=str(TEMPLATES))
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-" + os.getenv("DASHBOARD_URL","alforno"))
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB","10")) * 1024 * 1024

# --- Auth/DB setup ---
login_manager = LoginManager(app)
login_manager.login_view = "login"

DB_URL = f"sqlite:///{(BASE/'app.db').as_posix()}"
engine = create_engine(DB_URL, echo=False, future=True)

def db_init():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            position TEXT,
            role TEXT NOT NULL DEFAULT 'viewer',
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body_md TEXT NOT NULL,
            html TEXT NOT NULL,
            published INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            author_id INTEGER
        );
        """))

db_init()

class User(UserMixin):
    def __init__(self, id, username, email, position, role, password_hash, created_at):
        self.id = id
        self.username = username
        self.email = email
        self.position = position
        self.role = role
        self.password_hash = password_hash
        self.created_at = created_at

def now_beirut_str() -> str:
    return datetime.now(pytz.timezone("Asia/Beirut")).strftime("%Y-%m-%d %H:%M:%S")

def append_status_line(status: str, msg: str):
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
        mtime_dt = datetime.fromtimestamp(stat.st_mtime, tz=pytz.UTC).astimezone(tz)
        items.append({
            "name": p.name,
            "size_kb": max(1, stat.st_size // 1024),
            "mtime": mtime_dt.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return items

# --- User helpers ---
@login_manager.user_loader
def load_user(user_id):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        if not row: return None
        return User(*row)

def get_user_by_username(username):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE username=:u"), {"u": username}).fetchone()
        return User(*row) if row else None

def create_default_admin():
    import secrets
    with engine.begin() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        if cnt == 0:
            admin_pass = os.getenv("ADMIN_PASSWORD", secrets.token_urlsafe(10))
            admin_email = os.getenv("ADMIN_EMAIL", "admin@alforno.app")
            conn.execute(text("""INSERT INTO users (username,email,position,role,password_hash,created_at)
                                VALUES (:u,:e,:p,:r,:h,:c)"""),
                         {"u":"admin","e":admin_email,"p":"Owner","r":"admin",
                          "h":generate_password_hash(admin_pass),"c":now_beirut_str()})
            print(f"[INIT] Created default admin 'admin' with password: {admin_pass}")

create_default_admin()

ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union({"p","h1","h2","h3","h4","h5","h6","pre","code","ul","ol","li","table","thead","tbody","tr","th","td","blockquote","hr"})
ALLOWED_ATTRS = {"a": ["href","title","rel","target"], "img": ["src","alt","title"]}

def render_md(md_text:str)->str:
    raw = md.markdown(md_text or "", extensions=["extra","sane_lists","codehilite"])
    safe = bleach.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    return safe

# --- Errors ---
@app.errorhandler(Exception)
def handle_exception(e):
    # Let HTTP errors pass through with their original status codes
    if isinstance(e, HTTPException):
        return e
    tb = "".join(traceback.format_exception(e))
    prev = ERROR_LOG.read_text(encoding="utf-8") if ERROR_LOG.exists() else ""
    ERROR_LOG.write_text(prev + f"[{now_beirut_str()}] {e}\n{tb}\n", encoding="utf-8")
    return ("Internal Server Error", 500)

# handle big uploads clearly
@app.errorhandler(RequestEntityTooLarge)
def handle_413(e):
    return ("File too large", 413)

# --- Pages ---
@app.get("/")
def home():
    return render_template("home.html",
        active="home",
        lines=read_status_lines(100),
        csvs=list_csvs(),
        last_updated=now_beirut_str(),
        year=datetime.now().year,
    )

@app.get("/files")
def files_page():
    return render_template("files.html",
        active="files",
        csvs=list_csvs(),
        year=datetime.now().year,
    )

@app.get("/contact")
def contact():
    contact_info = {
        "phone": os.getenv("CONTACT_PHONE","+961-00-00-00"),
        "email": os.getenv("CONTACT_EMAIL","support@alforno.app"),
        "ig": os.getenv("CONTACT_IG","#"),
        "fb": os.getenv("CONTACT_FB","#"),
        "tt": os.getenv("CONTACT_TT","#"),
    }
    return render_template("contact.html", active="contact", contact=contact_info, year=datetime.now().year)

# --- News ---
def render_md(md_text:str)->str:
    return md.markdown(md_text or "", extensions=["extra","sane_lists"])

@app.get("/news")
def news_list():
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id,title,body_md,html,published,created_at,updated_at FROM news WHERE published=1 ORDER BY id DESC")).fetchall()
    posts = [{"id":r[0],"title":r[1],"body_md":r[2],"html":r[3],"published":bool(r[4]),"created_at":r[5],"updated_at":r[6]} for r in rows]
    # show drafts to editors/admins too
    if current_user.is_authenticated and current_user.role in ("admin","editor"):
        with engine.begin() as conn:
            rows2 = conn.execute(text("SELECT id,title,body_md,html,published,created_at,updated_at FROM news WHERE published=0 ORDER BY id DESC")).fetchall()
        posts = posts + [{"id":r[0],"title":r[1],"body_md":r[2],"html":r[3],"published":bool(r[4]),"created_at":r[5],"updated_at":r[6]} for r in rows2]
    return render_template("news_list.html", active="news", posts=posts, year=datetime.now().year)

@app.route("/news/new", methods=["GET","POST"])
@login_required
def news_new():
    if current_user.role not in ("admin","editor"): abort(403)
    if request.method == "POST":
        title = request.form.get("title","").strip()
        body_md = request.form.get("body","")
        published = 1 if request.form.get("published","1")=="1" else 0
        html = render_md(body_md)
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO news (title,body_md,html,published,created_at,updated_at,author_id)
                                VALUES (:t,:b,:h,:p,:c,:u,:a)"""),
                         {"t":title,"b":body_md,"h":html,"p":published,"c":now_beirut_str(),"u":now_beirut_str(),"a":current_user.id})
        return redirect(url_for("news_list"))
    return render_template("news_edit.html", post=None, year=datetime.now().year)

@app.route("/news/<int:post_id>/edit", methods=["GET","POST"])
@login_required
def news_edit(post_id):
    if current_user.role not in ("admin","editor"): abort(403)
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id,title,body_md,html,published,created_at,updated_at FROM news WHERE id=:id"), {"id":post_id}).fetchone()
    if not row: abort(404)
    post = type("P",(object,), dict(id=row[0], title=row[1], body_md=row[2], html=row[3], published=bool(row[4]), created_at=row[5], updated_at=row[6]))()
    if request.method == "POST":
        title = request.form.get("title","").strip()
        body_md = request.form.get("body","")
        published = 1 if request.form.get("published","1")=="1" else 0
        html = render_md(body_md)
        with engine.begin() as conn:
            conn.execute(text("""UPDATE news SET title=:t, body_md=:b, html=:h, published=:p, updated_at=:u WHERE id=:id"""),
                         {"t":title,"b":body_md,"h":html,"p":published,"u":now_beirut_str(),"id":post_id})
        return redirect(url_for("news_list"))
    return render_template("news_edit.html", post=post, year=datetime.now().year)

# --- Auth pages ---
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        with engine.begin() as conn:
            row = conn.execute(text("SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE username=:u"), {"u":username}).fetchone()
        if not row or not check_password_hash(row[5], password):
            return render_template("login.html", title="Login", error="Invalid credentials"), 401
        user = User(*row)
        login_user(user)
        return redirect(url_for("home"))
    return render_template("login.html", title="Login", year=datetime.now().year)

@app.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route("/users", methods=["GET","POST"])
@login_required
def users_admin():
    if current_user.role != "admin": abort(403)
    if request.method == "POST":
        import secrets
        username = request.form.get("username","").strip()
        email = request.form.get("email","").strip()
        position = request.form.get("position","").strip() or None
        role = request.form.get("role","viewer").strip()
        pwd = secrets.token_urlsafe(10)
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO users (username,email,position,role,password_hash,created_at)
                                VALUES (:u,:e,:p,:r,:h,:c)"""),
                         {"u":username,"e":email,"p":position,"r":role,"h":generate_password_hash(pwd),"c":now_beirut_str()})
        flash(f"User {username} created with password: {pwd}", "info")
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, username, email, position, role, password_hash, created_at FROM users ORDER BY id DESC")).fetchall()
    users = [User(*r) for r in rows]
    return render_template("users.html", users=users, year=datetime.now().year, active="users")

@app.route("/users/<int:user_id>/edit", methods=["GET","POST"])
@login_required
def user_edit(user_id):
    if current_user.role != "admin": abort(403)
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE id=:id"), {"id":user_id}).fetchone()
    if not row: abort(404)
    u = User(*row)
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email = request.form.get("email","").strip()
        position = request.form.get("position","").strip() or None
        role = request.form.get("role","viewer").strip()
        pwd = request.form.get("password","").strip()
        with engine.begin() as conn:
            if pwd:
                conn.execute(text("UPDATE users SET username=:u,email=:e,position=:p,role=:r,password_hash=:h WHERE id=:id"),
                             {"u":username,"e":email,"p":position,"r":role,"h":generate_password_hash(pwd),"id":user_id})
            else:
                conn.execute(text("UPDATE users SET username=:u,email=:e,position=:p,role=:r WHERE id=:id"),
                             {"u":username,"e":email,"p":position,"r":role,"id":user_id})
        return redirect(url_for("users_admin"))
    return render_template("user_edit.html", user=u, year=datetime.now().year)

@app.post("/users/<int:user_id>/delete")
@login_required
def user_delete(user_id):
    if current_user.role != "admin": abort(403)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id=:id"), {"id":user_id})
    return redirect(url_for("users_admin"))

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE id=:id"), {"id":current_user.id}).fetchone()
    u = User(*row)
    if request.method == "POST":
        username = request.form.get("username","").strip()
        position = request.form.get("position","").strip() or None
        pwd = request.form.get("password","").strip()
        with engine.begin() as conn:
            if pwd:
                conn.execute(text("UPDATE users SET username=:u,position=:p,password_hash=:h WHERE id=:id"),
                             {"u":username,"p":position,"h":generate_password_hash(pwd),"id":u.id})
            else:
                conn.execute(text("UPDATE users SET username=:u,position=:p WHERE id=:id"),
                             {"u":username,"p":position,"id":u.id})
    return render_template("profile.html", user=u, year=datetime.now().year)

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(16)
    return session["csrf"]

app.jinja_env.globals["csrf_token"] = csrf_token

# --- JSON APIs for light refresh ---
@app.get("/api/status")
def api_status():
    return {"lines": read_status_lines(100)}

@app.get("/api/csvs")
def api_csvs():
    return {"items": list_csvs()}

# --- Existing integration endpoints (kept) ---
@app.post("/upload")
def upload_csv():
    # Allow either logged-in editor/admin OR API key
    api_key = os.getenv("DASH_API_KEY","")
    header_key = request.headers.get("X-API-Key","")
    user_ok = current_user.is_authenticated and current_user.role in ("admin","editor")
    key_ok = api_key and (header_key == api_key)
    if not (user_ok or key_ok):
        abort(403, "Forbidden")
    if "file" not in request.files:
        abort(400, "No file")
    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        abort(400, "Only .csv allowed")
    dest = UPLOADS / secure_filename(f.filename)
    f.save(dest)
    return "OK", 200

@app.post("/log")
def post_log():
    api_key = os.getenv("DASH_API_KEY","")
    header_key = request.headers.get("X-API-Key","")
    user_ok = current_user.is_authenticated and current_user.role in ("admin","editor")
    key_ok = api_key and (header_key == api_key)
    if not (user_ok or key_ok):
        abort(403, "Forbidden")
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
