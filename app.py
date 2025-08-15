import os
from pathlib import Path
from datetime import datetime
import pytz
import secrets

from flask import (
    Flask, request, render_template, abort, jsonify,
    redirect, url_for, flash, send_from_directory
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from sqlalchemy import create_engine, text
import markdown as md

# ========== Paths & App ==========
BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
LOGS = BASE / "logs"
UPLOADS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

STATUS_LOG = LOGS / "status.log"
ERROR_LOG = LOGS / "error.log"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "devsecret")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024

# ========== Auth / DB ==========
login_manager = LoginManager(app)
login_manager.login_view = "login"

DB_PATH = BASE / "app.db"
engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}", echo=False, future=True)
TZ = pytz.timezone("Asia/Beirut")

def now_ts():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

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
    print(f"[INIT] Database initialized at {DB_PATH}")

def create_or_reset_admin():
    # Always ensure 'admin' user exists and matches .env on app start
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip()
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123").strip()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (username,email,position,role,password_hash,created_at)
            VALUES (:u,:e,:p,:r,:h,:c)
            ON CONFLICT(username) DO UPDATE SET
                email=excluded.email,
                position=excluded.position,
                role=excluded.role,
                password_hash=excluded.password_hash
        """), {
            "u": "admin",
            "e": admin_email,
            "p": "Owner",
            "r": "admin",
            "h": generate_password_hash(admin_pass),
            "c": now_ts()
        })
    print(f"[INIT] Admin user reset to 'admin' / {admin_pass}")

db_init()
create_or_reset_admin()

# ========== User model ==========
class User(UserMixin):
    def __init__(self, id, username, email, position, role, password_hash, created_at):
        self.id = id
        self.username = username
        self.email = email
        self.position = position
        self.role = role
        self.password_hash = password_hash
        self.created_at = created_at

@login_manager.user_loader
def load_user(user_id):
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE id=:id"
        ), {"id": user_id}).fetchone()
    return User(*row) if row else None

# ========== Helpers ==========
def append_status_line(status, msg):
    STATUS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{status.upper()}] {now_ts()} - {msg}\n")

def list_csvs():
    items = []
    for p in sorted(UPLOADS.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
        items.append({
            "name": p.name,
            "size_kb": max(1, p.stat().st_size // 1024),
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return items

def _read_status_lines(limit=200):
    if not STATUS_LOG.exists():
        return []
    return STATUS_LOG.read_text(encoding="utf-8").splitlines()[-limit:]

def _role_guard(roles):
    return current_user.is_authenticated and current_user.role in roles

# ========== Routes: Core ==========
@app.route("/")
def home():
    return render_template("home.html",
                           csvs=list_csvs(),
                           lines=_read_status_lines(),
                           year=datetime.now().year)

@app.route("/files")
@login_required
def files_page():
    return render_template("files.html",
                           csvs=list_csvs(),
                           year=datetime.now().year)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE username=:u"
            ), {"u": username}).fetchone()
        if not row or not check_password_hash(row[5], password):
            return render_template("login.html", error="Invalid credentials")
        login_user(User(*row))
        return redirect(url_for("home"))
    return render_template("login.html")

@app.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

# ========== Routes: Profile ==========
@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        position = request.form.get("position","").strip()
        new_pw   = request.form.get("password","")
        if not username:
            flash("Username is required")
            return redirect(url_for("profile"))
        with engine.begin() as conn:
            if new_pw:
                conn.execute(text("""
                    UPDATE users SET username=:u, position=:p, password_hash=:h WHERE id=:id
                """), {"u": username, "p": position, "h": generate_password_hash(new_pw), "id": current_user.id})
            else:
                conn.execute(text("""
                    UPDATE users SET username=:u, position=:p WHERE id=:id
                """), {"u": username, "p": position, "id": current_user.id})
        flash("Profile updated")
        return redirect(url_for("profile"))

    # Reload fresh data
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE id=:id"
        ), {"id": current_user.id}).fetchone()
    user = User(*row)
    return render_template("profile.html", user=user, year=datetime.now().year)

# ========== Routes: Users (Admin) ==========
@app.route("/users", methods=["GET","POST"])
@login_required
def users_admin():
    if not _role_guard(("admin",)):
        abort(403)
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email    = request.form.get("email","").strip()
        position = request.form.get("position","").strip()
        role     = request.form.get("role","viewer").strip()
        if role not in ("viewer","editor","admin"):
            role = "viewer"
        if not username or not email:
            flash("Username and email are required")
            return redirect(url_for("users_admin"))
        # Generate a password since the create form has no password field
        gen_pw = secrets.token_urlsafe(8)
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO users (username,email,position,role,password_hash,created_at)
                    VALUES (:u,:e,:p,:r,:h,:c)
                """), {"u": username, "e": email, "p": position, "r": role,
                       "h": generate_password_hash(gen_pw), "c": now_ts()})
            flash(f"User created. Temp password: {gen_pw}")
        except Exception as e:
            flash("Failed to create user (possibly duplicate username/email).")
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, username, email, position, role, created_at FROM users ORDER BY id"
        )).fetchall()
    users = [{"id": r[0], "username": r[1], "email": r[2], "position": r[3],
              "role": r[4], "created_at": r[5]} for r in rows]
    return render_template("users.html", users=users, year=datetime.now().year, active="users")

@app.route("/users/<int:user_id>/edit", methods=["GET","POST"])
@login_required
def user_edit(user_id):
    if not _role_guard(("admin",)):
        abort(403)
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT id, username, email, position, role, password_hash, created_at FROM users WHERE id=:id"
        ), {"id": user_id}).fetchone()
    if not row:
        abort(404)
    user = User(*row)

    if request.method == "POST":
        username = request.form.get("username","").strip()
        email    = request.form.get("email","").strip()
        position = request.form.get("position","").strip()
        role     = request.form.get("role","viewer").strip()
        new_pw   = request.form.get("password","")
        if role not in ("viewer","editor","admin"):
            role = "viewer"
        with engine.begin() as conn:
            if new_pw:
                conn.execute(text("""
                    UPDATE users SET username=:u,email=:e,position=:p,role=:r,password_hash=:h WHERE id=:id
                """), {"u": username, "e": email, "p": position, "r": role,
                       "h": generate_password_hash(new_pw), "id": user_id})
            else:
                conn.execute(text("""
                    UPDATE users SET username=:u,email=:e,position=:p,role=:r WHERE id=:id
                """), {"u": username, "e": email, "p": position, "r": role, "id": user_id})
        flash("User updated")
        return redirect(url_for("users_admin"))

    return render_template("user_edit.html", user=user, year=datetime.now().year)

@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id):
    if not _role_guard(("admin",)):
        abort(403)
    # Prevent deleting self (optional safeguard)
    if current_user.id == user_id:
        flash("You cannot delete your own account.")
        return redirect(url_for("users_admin"))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
    flash("User deleted")
    return redirect(url_for("users_admin"))

# ========== Routes: News ==========
@app.route("/news")
def news_list():
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, title, body_md, html, published, created_at, updated_at
            FROM news
            ORDER BY id DESC
        """)).fetchall()
    posts = [{"id": r[0], "title": r[1], "body_md": r[2], "html": r[3],
              "published": bool(r[4]), "created_at": r[5], "updated_at": r[6]} for r in rows]
    return render_template("news_list.html", posts=posts, year=datetime.now().year, active="news")

@app.route("/news/new", methods=["GET","POST"])
@login_required
def news_new():
    if not _role_guard(("admin","editor")):
        abort(403)
    if request.method == "POST":
        title = request.form.get("title","").strip()
        body_md = request.form.get("body","")
        published = 1 if request.form.get("published","1") == "1" else 0
        html = md.markdown(body_md)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO news (title, body_md, html, published, created_at, updated_at, author_id)
                VALUES (:t,:b,:h,:p,:c,:u,:a)
            """), {"t": title, "b": body_md, "h": html, "p": published,
                   "c": now_ts(), "u": now_ts(), "a": current_user.id})
        return redirect(url_for("news_list"))
    return render_template("news_edit.html", post=None, year=datetime.now().year)

@app.route("/news/<int:post_id>/edit", methods=["GET","POST"])
@login_required
def news_edit(post_id):
    if not _role_guard(("admin","editor")):
        abort(403)
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT id, title, body_md, html, published, created_at, updated_at FROM news WHERE id=:id
        """), {"id": post_id}).fetchone()
    if not row:
        abort(404)
    class P: pass
    post = P()
    (post.id, post.title, post.body_md, post.html,
     post.published, post.created_at, post.updated_at) = row

    if request.method == "POST":
        title = request.form.get("title","").strip()
        body_md = request.form.get("body","")
        published = 1 if request.form.get("published","1") == "1" else 0
        html = md.markdown(body_md)
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE news SET title=:t, body_md=:b, html=:h, published=:p, updated_at=:u WHERE id=:id
            """), {"t": title, "b": body_md, "h": html, "p": published, "u": now_ts(), "id": post_id})
        return redirect(url_for("news_list"))
    return render_template("news_edit.html", post=post, year=datetime.now().year)

# ========== Routes: Upload / Log / Download / JSON ==========
@app.post("/upload")
def upload_csv():
    api_key = os.getenv("DASH_API_KEY", "")
    allowed = (current_user.is_authenticated and current_user.role in ("admin","editor")) \
              or (request.headers.get("X-API-Key") == api_key)
    if not allowed:
        abort(403)
    if "file" not in request.files:
        abort(400)
    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        abort(400)
    dest = UPLOADS / secure_filename(f.filename)
    f.save(dest)
    append_status_line("success", f"File uploaded: {f.filename}")
    return "OK"

@app.post("/log")
def post_log():
    api_key = os.getenv("DASH_API_KEY", "")
    allowed = (current_user.is_authenticated and current_user.role in ("admin","editor")) \
              or (request.headers.get("X-API-Key") == api_key)
    if not allowed:
        abort(403)
    data = request.get_json(silent=True) or {}
    append_status_line(data.get("status", "info"), data.get("message", ""))
    return jsonify(ok=True)

@app.route("/download/<path:filename>")
def download(filename):
    # Serve from uploads/
    return send_from_directory(UPLOADS.as_posix(), filename, as_attachment=True)

@app.route("/api/status")
def api_status():
    return jsonify({"ok": True, "lines": _read_status_lines()})

@app.route("/api/csvs")
def api_csvs():
    return jsonify({"ok": True, "items": list_csvs()})

# ========== Misc ==========
@app.route("/contact")
def contact():
    # If contact.html exists, use it; otherwise show a simple fallback
    try:
        return render_template("contact.html", year=datetime.now().year, active="contact")
    except Exception:
        return "<h1>Contact</h1><p>Update contact.html to customize this page.</p>"

# ========== Error Logging ==========
@app.errorhandler(Exception)
def handle_any_error(e):
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{now_ts()}] {repr(e)}\n")
    except Exception:
        pass
    # Let Flask show default error pages in dev; simple 500 otherwise
    return ("Internal Server Error", 500)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
