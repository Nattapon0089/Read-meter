import sqlite3, sys
from pathlib import Path
from werkzeug.security import generate_password_hash

DB = Path(__file__).with_name("users.db")

def ensure_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        email TEXT, plant TEXT, firstname TEXT, lastname TEXT, position TEXT, section TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );""")
    conn.commit()

def add_user(username, password, role="user", email=None):
    with sqlite3.connect(DB) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), role, email),
            )
            conn.commit()
            print(f"[OK] Created user '{username}' (role={role})")
        except sqlite3.IntegrityError as e:
            print(f"[ERR] Cannot create user: {e}")

def list_users():
    with sqlite3.connect(DB) as conn:
        ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, username, role, email, created_at FROM users ORDER BY id").fetchall()
        if not rows: print("(no users)")
        for r in rows:
            print(f"{r['id']:>3}  {r['username']:<20}  {r['role']:<6}  {r['email'] or ''}  {r['created_at']}")

def set_password(username, new_password):
    with sqlite3.connect(DB) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute("UPDATE users SET password_hash=? WHERE username=?",
                    (generate_password_hash(new_password), username))
        if cur.rowcount: conn.commit(); print(f"[OK] Password updated for '{username}'")
        else: print(f"[ERR] User '{username}' not found")

def set_role(username, new_role):
    with sqlite3.connect(DB) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute("UPDATE users SET role=? WHERE username=?", (new_role, username))
        if cur.rowcount: conn.commit(); print(f"[OK] Role of '{username}' -> {new_role}")
        else: print(f"[ERR] User '{username}' not found")

def delete_user(username):
    with sqlite3.connect(DB) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE username=?", (username,))
        if cur.rowcount: conn.commit(); print(f"[OK] Deleted '{username}'")
        else: print(f"[ERR] User '{username}' not found")

def help():
    print("""
Usage:
  python manage_users.py add <username> <password> [role=user] [email]
  python manage_users.py list
  python manage_users.py passwd <username> <new_password>
  python manage_users.py role <username> <admin|user>
  python manage_users.py del <username>
""".strip())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        help(); sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "add":
        if len(sys.argv) < 4: print("need <username> <password>"); sys.exit(1)
        username, password = sys.argv[2], sys.argv[3]
        role = sys.argv[4] if len(sys.argv) >= 5 else "user"
        email = sys.argv[5] if len(sys.argv) >= 6 else None
        add_user(username, password, role, email)
    elif cmd == "list":
        list_users()
    elif cmd == "passwd":
        if len(sys.argv) < 4: print("need <username> <new_password>"); sys.exit(1)
        set_password(sys.argv[2], sys.argv[3])
    elif cmd == "role":
        if len(sys.argv) < 4: print("need <username> <role>"); sys.exit(1)
        set_role(sys.argv[2], sys.argv[3])
    elif cmd == "del":
        if len(sys.argv) < 3: print("need <username>"); sys.exit(1)
        delete_user(sys.argv[2])
    else:
        help()
