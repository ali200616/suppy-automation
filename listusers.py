# list_users.py
import sqlite3
conn = sqlite3.connect("app.db")
cur = conn.cursor()
print("\nUsers in DB:\n-------------")
for r in cur.execute("SELECT id, username, email, role, created_at FROM users ORDER BY id"):
    print(r)
conn.close()
