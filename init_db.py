import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

DB = Path(__file__).with_name("users.db")

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        email TEXT,
        plant TEXT,
        firstname TEXT,
        lastname TEXT,
        position TEXT,
        section TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # readings (เก็บค่าไฟ)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        voltage REAL,
        current REAL,
        power REAL,
        energy_kwh REAL,
        frequency REAL,
        pf REAL
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts DESC)")

    # seed admin
    cur.execute("SELECT 1 FROM users WHERE username=?", ("admin",))
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users (username, password_hash, role, email, firstname, lastname)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "admin",
            generate_password_hash("admin123"),
            "admin",
            "admin@company.com",
            "admin", "admin"
        ))

    conn.commit()
    conn.close()
    print("DB ready at:", DB)

if __name__ == "__main__":
    main()
