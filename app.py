import os, sqlite3, hmac, hashlib, json
from datetime import datetime, date
from urllib.parse import parse_qsl
import requests
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "barber.db")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "change-this-secret-before-deploying")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
SHOP_NAME = os.getenv("SHOP_NAME", "Hawk Strike")
APP_URL = os.getenv("APP_URL", "https://example.com")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS stylists (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            title TEXT DEFAULT 'BARBER', photo TEXT DEFAULT '', active INTEGER DEFAULT 1)""")
        con.execute("""CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            name_ru TEXT DEFAULT '', duration INTEGER NOT NULL DEFAULT 30,
            price INTEGER NOT NULL DEFAULT 0, active INTEGER DEFAULT 1)""")
        con.execute("""CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, stylist_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL, customer_name TEXT NOT NULL,
            phone TEXT NOT NULL, booking_date TEXT NOT NULL, booking_time TEXT NOT NULL,
            telegram_id TEXT DEFAULT '', status TEXT DEFAULT 'new', created_at TEXT NOT NULL,
            UNIQUE(stylist_id, booking_date, booking_time))""")
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL,
            stylist_id INTEGER, active INTEGER DEFAULT 1)""")
        if con.execute("SELECT COUNT(*) FROM stylists").fetchone()[0] == 0:
            con.executemany("INSERT INTO stylists(name,title) VALUES(?,?)",
                            [("AZIZ","BARBER"),("DONI","BARBER"),("ALI","BARBER")])
        if con.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
            con.executemany("INSERT INTO services(name,name_ru,duration,price) VALUES(?,?,?,?)", [
                ("Soch olish","Стрижка",30,50000),
                ("Soqol olish","Стрижка бороды",20,30000),
                ("Soch + soqol","Стрижка + борода",50,70000)])
        # Demo barber logins are created once; change passwords before public launch.
        for username, stylist_id in [("aziz",1),("doni",2),("ali",3)]:
            if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is None:
                con.execute("INSERT INTO users(username,password_hash,role,stylist_id) VALUES(?,?,?,?)",
                            (username, generate_password_hash("change-me"), "barber", stylist_id))


def telegram_notify(message):
    if BOT_TOKEN and ADMIN_CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                          json={"chat_id": ADMIN_CHAT_ID, "text": message}, timeout=8)
        except requests.RequestException:
            app.logger.exception("Telegram notification failed")


def validate_telegram_init_data(init_data):
    if not init_data or not BOT_TOKEN:
        return None
    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash", None)
        if not received_hash:
            return None
        check_string = "\n".join(f"{k}={v}" for k,v in sorted(values.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            return None
        return json.loads(values.get("user", "{}"))
    except Exception:
        return None


@app.get("/")
def landing():
    with db() as con:
        stylists = con.execute("SELECT * FROM stylists WHERE active=1 ORDER BY id").fetchall()
        services = con.execute("SELECT * FROM services WHERE active=1 ORDER BY id").fetchall()
    return render_template("landing.html", stylists=stylists, services=services,
                           shop_name=SHOP_NAME,
                           address=os.getenv("SHOP_ADDRESS", "Manzil tez orada qo‘shiladi"),
                           maps_url=os.getenv("MAPS_URL", ""))


@app.get("/app")
def index():
    with db() as con:
        stylists = con.execute("SELECT * FROM stylists WHERE active=1 ORDER BY id").fetchall()
        services = con.execute("SELECT * FROM services WHERE active=1 ORDER BY id").fetchall()
    return render_template("index.html", stylists=stylists, services=services,
                           shop_name=SHOP_NAME, selected_service=request.args.get("service", ""))


@app.get("/api/slots")
def slots():
    stylist_id = request.args.get("stylist_id", type=int)
    day = request.args.get("date", "")
    try:
        selected = date.fromisoformat(day)
    except ValueError:
        return jsonify({"slots": [], "error": "Invalid date"}), 400
    if selected < date.today():
        return jsonify({"slots": []})
    times = [f"{h:02d}:00" for h in range(9,23)]
    with db() as con:
        booked = {r["booking_time"] for r in con.execute(
            "SELECT booking_time FROM bookings WHERE stylist_id=? AND booking_date=? AND status!='cancelled'",
            (stylist_id, day)).fetchall()}
    return jsonify({"slots": [t for t in times if t not in booked]})


@app.post("/api/book")
def book():
    data = request.get_json(silent=True) or {}
    name, phone = (data.get("name") or "").strip(), (data.get("phone") or "").strip()
    day, time = (data.get("date") or "").strip(), (data.get("time") or "").strip()
    try:
        stylist_id, service_id = int(data.get("stylist_id")), int(data.get("service_id"))
        if not name or not phone or len(name) > 100 or len(phone) > 30:
            raise ValueError()
        selected = date.fromisoformat(day)
        datetime.strptime(time, "%H:%M")
        if selected < date.today():
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"ok":False,"message":"Ma’lumotlarni tekshiring / Проверьте данные."}), 400
    tg_user = validate_telegram_init_data(data.get("init_data",""))
    telegram_id = str(tg_user.get("id","")) if tg_user else ""
    with db() as con:
        stylist = con.execute("SELECT name FROM stylists WHERE id=? AND active=1",(stylist_id,)).fetchone()
        service = con.execute("SELECT name,name_ru,price FROM services WHERE id=? AND active=1",(service_id,)).fetchone()
        if not stylist or not service:
            return jsonify({"ok":False,"message":"Tanlov topilmadi / Выбор не найден."}), 404
        try:
            con.execute("""INSERT INTO bookings(stylist_id,service_id,customer_name,phone,booking_date,
                booking_time,telegram_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)""".replace("VALUES(?,?,?,?,?,?,?,?,?)","VALUES(?,?,?,?,?,?,?,?)"),
                (stylist_id,service_id,name,phone,day,time,telegram_id,datetime.now().isoformat(timespec="seconds")))
        except sqlite3.IntegrityError:
            return jsonify({"ok":False,"message":"Bu vaqt band / Это время уже занято."}), 409
    telegram_notify(f"🆕 {SHOP_NAME}\\n{name} | {phone}\\n{stylist['name']}\\n{service['name']}\\n{day} {time}")
    return jsonify({"ok":True,"message":"Yozilishingiz qabul qilindi! / Запись принята!"})


@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        username, password = request.form.get("username",""), request.form.get("password","")
        if username == ADMIN_USER and password == ADMIN_PASSWORD:
            session.clear(); session["role"]="admin"; session["username"]=username
            return redirect(url_for("admin"))
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE username=? AND active=1",(username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["role"], session["username"], session["stylist_id"] = user["role"], user["username"], user["stylist_id"]
            return redirect(url_for("admin"))
        flash("Login yoki parol noto‘g‘ri / Неверный логин или пароль.")
    return render_template("login.html")


@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.get("/admin")
def admin():
    if not session.get("role"):
        return redirect(url_for("admin_login"))
    with db() as con:
        if session["role"] == "admin":
            rows = con.execute("""SELECT b.*,s.name AS stylist,v.name AS service,v.price
                FROM bookings b JOIN stylists s ON s.id=b.stylist_id
                JOIN services v ON v.id=b.service_id ORDER BY b.booking_date DESC,b.booking_time DESC""").fetchall()
        else:
            rows = con.execute("""SELECT b.*,s.name AS stylist,v.name AS service,v.price
                FROM bookings b JOIN stylists s ON s.id=b.stylist_id
                JOIN services v ON v.id=b.service_id
                WHERE b.stylist_id=? ORDER BY b.booking_date DESC,b.booking_time DESC""",
                (session["stylist_id"],)).fetchall()
    return render_template("admin.html", bookings=rows, shop_name=SHOP_NAME,
                           username=session["username"], role=session["role"])


@app.post("/admin/booking/<int:booking_id>/<action>")
def booking_action(booking_id, action):
    if not session.get("role") or action not in ("confirmed","cancelled","done"):
        return redirect(url_for("admin_login"))
    with db() as con:
        if session["role"] == "admin":
            con.execute("UPDATE bookings SET status=? WHERE id=?",(action,booking_id))
        else:
            con.execute("UPDATE bookings SET status=? WHERE id=? AND stylist_id=?",
                        (action,booking_id,session["stylist_id"]))
    return redirect(url_for("admin"))


init_db()
if __name__ == "__main__":
    app.run(host="127.0.0.1",port=5000,debug=True)
