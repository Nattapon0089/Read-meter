# app.py  — merged full version (MQTT + DB + Auth + Dashboard APIs)
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from functools import wraps
import sqlite3, datetime, json, threading
import paho.mqtt.client as mqtt
from werkzeug.security import check_password_hash, generate_password_hash
from pathlib import Path

# ===== Config =====
DATABASE = Path(__file__).with_name("users.db")
SECRET_KEY = "change-me-please-very-secret"   # เปลี่ยนใน production

# MQTT broker/topic (ต้องตรงกับฝั่ง ESP32)
MQTT_BROKER = "broker.mqttdashboard.com"
MQTT_PORT   = 1883
MQTT_TOPIC  = "cotto/energy/main"

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# ========= Helpers =========
def to_th_iso(ts_iso: str) -> str:
    """รับ ISO (UTC) -> คืน string เวลาไทย +07:00 (YYYY-MM-DD HH:MM:SS)"""
    try:
        ts = datetime.datetime.fromisoformat(ts_iso)
    except Exception:
        return ts_iso
    th = ts + datetime.timedelta(hours=7)
    return th.strftime("%Y-%m-%d %H:%M:%S")

# ===== DB helpers =====
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()

def ensure_users_schema():
    db = get_db()
    db.execute("""
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
    );
    """)
    db.commit()

def ensure_readings_schema():
    db = get_db()
    db.execute("""
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,                 -- เก็บเป็น ISO (UTC)
        voltage REAL,
        current REAL,
        power REAL,
        energy_kwh REAL,
        frequency REAL,
        pf REAL
    );
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);")
    db.commit()

def init_admin_if_missing():
    db = get_db()
    row = db.execute("SELECT 1 FROM users WHERE username='admin'").fetchone()
    if not row:
        db.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)",
                   ("admin", generate_password_hash("admin"), "admin"))
        db.commit()
        print("Created default admin / password: admin")

# ===== Auth =====
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped

# ====== MQTT (subscribe ใน thread แยก) ======
latest_reading = {}   # เก็บค่าล่าสุดจาก MQTT (เพื่อโชว์ทันทีบนหน้าจอ)

def on_connect(client, userdata, flags, rc):
    print("[MQTT] Connected:", rc)
    client.subscribe(MQTT_TOPIC)
    print(f"[MQTT] Subscribed: {MQTT_TOPIC}")

def _insert_reading_row(payload_dict: dict):
    """เปิด SQLite connection แยกใน thread MQTT, เขียนลง DB ให้ปลอดภัย"""
    # mapping energy -> energy_kwh หากส่งมาเป็นชื่อ energy
    energy_kwh = payload_dict.get("energy_kwh")
    if energy_kwh is None and "energy" in payload_dict:
        energy_kwh = payload_dict.get("energy")

    ts = payload_dict.get("ts") or datetime.datetime.utcnow().isoformat()

    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute("""
            INSERT INTO readings (ts, voltage, current, power, energy_kwh, frequency, pf)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ts,
              payload_dict.get("voltage"),
              payload_dict.get("current"),
              payload_dict.get("power"),
              energy_kwh,
              payload_dict.get("frequency"),
              payload_dict.get("pf")))
        conn.commit()
    finally:
        conn.close()
    return ts, energy_kwh

def on_message(client, userdata, msg):
    global latest_reading
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)

        # ให้แน่ใจว่ามีตารางแล้ว (ครั้งแรก)
        # ใช้ connection ใน context app ไม่ได้ใน thread นี้—ข้ามและใช้ _insert_reading_row แทน
        ensure_readings_schema()  # safe แม้อยู่ต่าง thread เพราะแค่ CREATE IF NOT EXISTS

        ts, energy_kwh = _insert_reading_row(data)

        # เก็บค่าไว้ในหน่วยความจำสำหรับโชว์ล่าสุด
        latest_reading = {
            "ts": ts,
            "voltage": data.get("voltage"),
            "current": data.get("current"),
            "power": data.get("power"),
            "energy_kwh": energy_kwh,
            "frequency": data.get("frequency"),
            "pf": data.get("pf"),
        }
        print("[MQTT] -> DB & memory:", latest_reading)
    except Exception as e:
        print("[MQTT] Parse/DB error:", e)

def mqtt_worker():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

# ===== Routes =====
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    ensure_users_schema()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("กรุณากรอกชื่อผู้ใช้และรหัสผ่าน", "error")
            return render_template("login.html", active="login")

        db = get_db()
        row = db.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username=?",
            (username,)
        ).fetchone()

        if row and check_password_hash(row["password_hash"], password):
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            session["role"] = row["role"]
            flash("เข้าสู่ระบบสำเร็จ", "success")
            return redirect(url_for("home"))
        else:
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "error")
    return render_template("login.html", active="login")

@app.route("/logout")
def logout():
    session.clear()
    flash("ออกจากระบบแล้ว", "info")
    return redirect(url_for("login"))

@app.route("/home")
@login_required
def home():
    # หน้า dashboard (ดึงค่าล่าสุดจาก memory เฉย ๆ)
    return render_template(
        "home.html",
        active="home",
        username=session.get("username"),
        role=session.get("role"),
        reading=latest_reading
    )

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    ensure_users_schema()
    db = get_db()

    if request.method == "POST":
        plant     = request.form.get("plant", "").strip()
        firstname = request.form.get("firstname", "").strip()
        lastname  = request.form.get("lastname", "").strip()
        email     = request.form.get("email", "").strip()
        position  = request.form.get("position", "").strip()
        section   = request.form.get("section", "").strip()
        new_pw    = request.form.get("new_password", "")

        if new_pw:
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (generate_password_hash(new_pw), session["user_id"]))

        db.execute("""
            UPDATE users
               SET plant=?, firstname=?, lastname=?, email=?, position=?, section=?
             WHERE id=?
        """, (plant, firstname, lastname, email, position, section, session["user_id"]))
        db.commit()
        flash("บันทึกโปรไฟล์สำเร็จ", "success")
        return redirect(url_for("profile"))

    profile_row = db.execute("""
        SELECT id, username, role, email, plant, firstname, lastname, position, section, created_at
          FROM users WHERE id=?
    """, (session["user_id"],)).fetchone()

    return render_template(
        "profile.html",
        active="profile",
        username=session.get("username"),
        role=session.get("role"),
        profile=profile_row
    )

# ---------- API สำหรับ Dashboard ----------
@app.route("/api/history")
@login_required
def api_history():
    """
    ส่งค่าล่าสุด N แถว สำหรับ plot chart (เรียงจากเก่า -> ใหม่)
    เพิ่มการแปลงเวลาเป็นไทยฝั่ง API ให้พร้อมใช้ทันที
    """
    n = int(request.args.get("n", 100))
    ensure_readings_schema()
    db = get_db()
    rows = db.execute("""
        SELECT ts, voltage, current, power, energy_kwh, frequency, pf
        FROM readings ORDER BY ts DESC LIMIT ?
    """, (n,)).fetchall()
    data = []
    for r in rows[::-1]:
        d = dict(r)
        d["ts"] = to_th_iso(d["ts"])
        data.append(d)
    return jsonify(data)

@app.route("/api/latest")
@login_required
def api_latest():
    """ส่งค่าแถวล่าสุด 1 แถว (เวลาแสดงเป็นไทย)"""
    ensure_readings_schema()
    db = get_db()
    row = db.execute("""
        SELECT ts, voltage, current, power, energy_kwh, frequency, pf
        FROM readings ORDER BY ts DESC LIMIT 1
    """).fetchone()
    if row:
        d = dict(row)
        d["ts"] = to_th_iso(d["ts"])
        return jsonify(d)
    return jsonify({})

@app.route("/api/monthly")
@login_required
def api_monthly():
    """
    ส่งข้อมูลแบบ day-level (เลือกวันแรกที่บันทึกของแต่ละวัน)
    ใช้สำหรับกราฟรายวันของเดือนนั้น
    params: year, month
    """
    now = datetime.datetime.utcnow()
    year  = int(request.args.get("year",  now.year))
    month = int(request.args.get("month", now.month))

    ensure_readings_schema()
    db = get_db()
    rows = db.execute("""
        SELECT DATE(ts) as day,
               MIN(ts)  as ts,        -- เลือกค่าแรกของวันนั้น
               voltage, current, power, energy_kwh, frequency, pf
        FROM readings
        WHERE strftime('%Y', ts)=? AND strftime('%m', ts)=?
        GROUP BY day
        ORDER BY day ASC
    """, (str(year), f"{month:02d}")).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        d["ts"] = to_th_iso(d["ts"])
        out.append(d)
    return jsonify(out)

# (ตัวเลือก) API รับค่าผ่าน HTTP จาก ESP32
@app.route("/api/readings", methods=["POST"])
def api_readings():
    """
    รองรับ ESP32 ส่งตรงทาง HTTP (นอกเหนือจาก MQTT)
    จะ map energy -> energy_kwh ให้อัตโนมัติ และบันทึก DB + อัปเดต latest_reading
    """
    global latest_reading
    data = request.get_json(silent=True) or {}
    print("[API] Received:", data)

    ensure_readings_schema()
    # map energy -> energy_kwh หากจำเป็น
    energy_kwh = data.get("energy_kwh")
    if energy_kwh is None and "energy" in data:
        energy_kwh = data.get("energy")

    ts = data.get("ts") or datetime.datetime.utcnow().isoformat()
    db = get_db()
    db.execute("""
        INSERT INTO readings (ts, voltage, current, power, energy_kwh, frequency, pf)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (ts, data.get("voltage"), data.get("current"), data.get("power"),
          energy_kwh, data.get("frequency"), data.get("pf")))
    db.commit()

    latest_reading = {
        "ts": ts,
        "voltage": data.get("voltage"),
        "current": data.get("current"),
        "power": data.get("power"),
        "energy_kwh": energy_kwh,
        "frequency": data.get("frequency"),
        "pf": data.get("pf"),
    }
    return jsonify({"ok": True})

# ===== main =====
if __name__ == "__main__":
    # เตรียม DB + admin ครั้งแรก
    with app.app_context():
        ensure_users_schema()
        ensure_readings_schema()
        init_admin_if_missing()

    # สตาร์ต MQTT worker 1 ตัว (ปิด reloader กัน thread ซ้ำตอน debug)
    threading.Thread(target=mqtt_worker, daemon=True).start()
    app.jinja_env.auto_reload = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
