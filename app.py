import os, sqlite3, hmac, hashlib, json, secrets
from datetime import datetime, date
from urllib.parse import parse_qsl
import requests
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.getenv("DATABASE_URL", "").strip().strip('"').strip("\'")
if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.errors import UniqueViolation
else:
    UniqueViolation = sqlite3.IntegrityError

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
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")


class DatabaseConnection:
    """Small adapter so the same SQL works with local SQLite and hosted PostgreSQL."""
    def __init__(self):
        if DATABASE_URL:
            self.con = psycopg.connect(DATABASE_URL, row_factory=dict_row)
            self.postgres = True
        else:
            self.con = sqlite3.connect(DB_PATH)
            self.con.row_factory = sqlite3.Row
            self.postgres = False

    def execute(self, query, params=()):
        if self.postgres:
            query = query.replace("?", "%s")
        return self.con.execute(query, params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type:
                self.con.rollback()
            else:
                self.con.commit()
        finally:
            self.con.close()
        return False


def db():
    return DatabaseConnection()


def init_db():
    with db() as con:
        if DATABASE_URL:
            con.execute("""CREATE TABLE IF NOT EXISTS stylists (
                id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL,
                title TEXT DEFAULT 'BARBER', photo TEXT DEFAULT '', active INTEGER DEFAULT 1, telegram_chat_id TEXT DEFAULT '')""")
            con.execute("""CREATE TABLE IF NOT EXISTS services (
                id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL,
                name_ru TEXT DEFAULT '', duration INTEGER NOT NULL DEFAULT 30,
                price INTEGER NOT NULL DEFAULT 0, active INTEGER DEFAULT 1)""")
            con.execute("""CREATE TABLE IF NOT EXISTS bookings (
                id BIGSERIAL PRIMARY KEY, stylist_id BIGINT NOT NULL,
                service_id BIGINT NOT NULL, customer_name TEXT NOT NULL,
                phone TEXT NOT NULL, booking_date TEXT NOT NULL, booking_time TEXT NOT NULL,
                telegram_id TEXT DEFAULT '', status TEXT DEFAULT 'new', created_at TEXT NOT NULL,
                UNIQUE(stylist_id, booking_date, booking_time))""")
            con.execute("""CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL,
                stylist_id BIGINT, active INTEGER DEFAULT 1)""")
            con.execute("""CREATE TABLE IF NOT EXISTS telegram_link_codes (
                id BIGSERIAL PRIMARY KEY, stylist_id BIGINT NOT NULL, code_hash TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL, used_at TEXT DEFAULT '')""")
            con.execute("ALTER TABLE stylists ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT DEFAULT ''")
        else:
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
            con.execute("""CREATE TABLE IF NOT EXISTS telegram_link_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, stylist_id INTEGER NOT NULL, code_hash TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL, used_at TEXT DEFAULT '')""")
            cols = {row[1] for row in con.execute("PRAGMA table_info(stylists)").fetchall()}
            if "telegram_chat_id" not in cols:
                con.execute("ALTER TABLE stylists ADD COLUMN telegram_chat_id TEXT DEFAULT ''")
        if con.execute("SELECT COUNT(*) AS total FROM stylists").fetchone()["total"] == 0:
            for name in ("AZIZ", "DONI", "ALI"):
                con.execute("INSERT INTO stylists(name,title) VALUES(?,?)", (name, "BARBER"))
        if con.execute("SELECT COUNT(*) AS total FROM services").fetchone()["total"] == 0:
            for service in [
                ("Soch olish", "Стрижка", 30, 50000),
                ("Soqol olish", "Стрижка бороды", 20, 30000),
                ("Soch + soqol", "Стрижка + борода", 50, 70000),
            ]:
                con.execute("INSERT INTO services(name,name_ru,duration,price) VALUES(?,?,?,?)", service)
        for username, stylist_id in [("aziz", 1), ("doni", 2), ("ali", 3)]:
            if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is None:
                con.execute("INSERT INTO users(username,password_hash,role,stylist_id) VALUES(?,?,?,?)",
                            (username, generate_password_hash("change-me"), "barber", stylist_id))


def telegram_send(chat_id, message):
    if not BOT_TOKEN or not chat_id:
        return False
    try:
        response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                 json={"chat_id": str(chat_id), "text": message}, timeout=8)
        response.raise_for_status()
        return response.json().get("ok", False)
    except requests.RequestException:
        app.logger.exception("Telegram notification failed")
        return False


def telegram_notify(message):
    return telegram_send(ADMIN_CHAT_ID, message)


def telegram_webhook_url():
    explicit = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    if explicit:
        return explicit
    base = (os.getenv("PUBLIC_BASE_URL", "") or os.getenv("RENDER_EXTERNAL_URL", "")).strip().rstrip("/")
    return f"{base}/telegram/webhook" if base else ""


def configure_telegram_webhook():
    webhook_url = telegram_webhook_url()
    if not (BOT_TOKEN and webhook_url and TELEGRAM_WEBHOOK_SECRET):
        return
    try:
        response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "secret_token": TELEGRAM_WEBHOOK_SECRET,
                  "allowed_updates": ["message"]}, timeout=10)
        if not response.ok:
            app.logger.error("Telegram webhook setup failed: %s", response.text[:300])
    except requests.RequestException:
        app.logger.exception("Telegram webhook setup request failed")


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
        stylist = con.execute("SELECT name,telegram_chat_id FROM stylists WHERE id=? AND active=1",(stylist_id,)).fetchone()
        service = con.execute("SELECT name,name_ru,price FROM services WHERE id=? AND active=1",(service_id,)).fetchone()
        if not stylist or not service:
            return jsonify({"ok":False,"message":"Tanlov topilmadi / Выбор не найден."}), 404
        try:
            con.execute("""INSERT INTO bookings(stylist_id,service_id,customer_name,phone,booking_date,
                booking_time,telegram_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)""".replace("VALUES(?,?,?,?,?,?,?,?,?)","VALUES(?,?,?,?,?,?,?,?)"),
                (stylist_id,service_id,name,phone,day,time,telegram_id,datetime.now().isoformat(timespec="seconds")))
        except (sqlite3.IntegrityError, UniqueViolation):
            return jsonify({"ok":False,"message":"Bu vaqt band / Это время уже занято."}), 409
    try:
        pretty_day = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        pretty_day = day
    message = (
        f"✂️ {SHOP_NAME.upper()}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆕 YANGI BUYURTMA!\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 Mijoz: {name}\n"
        f"📞 Telefon: {phone}\n"
        f"💈 Sartarosh: {stylist['name']}\n"
        f"✂️ Xizmat: {service['name']}\n"
        f"📅 Sana: {pretty_day}\n"
        f"🕒 Vaqt: {time}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Buyurtma qabul qilindi."
    )
    telegram_notify(message)
    if stylist["telegram_chat_id"]:
        telegram_send(stylist["telegram_chat_id"], message)
    return jsonify({"ok":True,"message":"Yozilishingiz qabul qilindi! / Запись принята!"})


@app.post("/telegram/webhook")
def telegram_webhook():
    if not TELEGRAM_WEBHOOK_SECRET or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TELEGRAM_WEBHOOK_SECRET:
        return jsonify({"ok": False}), 403
    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return jsonify({"ok": True})
    if text.startswith("/start"):
        telegram_send(chat_id, f"{SHOP_NAME} sartarosh akkauntini bog‘lash uchun admin bergan kodni yuboring:\n/link KOD")
    elif text.startswith("/link "):
        code = text.split(maxsplit=1)[1].strip()
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        now = datetime.now().isoformat(timespec="seconds")
        with db() as con:
            link = con.execute("SELECT stylist_id FROM telegram_link_codes WHERE code_hash=? AND used_at='' AND expires_at>?", (code_hash, now)).fetchone()
            if not link:
                telegram_send(chat_id, "Kod noto‘g‘ri, ishlatilgan yoki muddati tugagan. Admin’dan yangi kod oling.")
            else:
                con.execute("UPDATE stylists SET telegram_chat_id='' WHERE telegram_chat_id=?", (str(chat_id),))
                con.execute("UPDATE stylists SET telegram_chat_id=? WHERE id=?", (str(chat_id), link["stylist_id"]))
                con.execute("UPDATE telegram_link_codes SET used_at=? WHERE code_hash=?", (now, code_hash))
                stylist = con.execute("SELECT name FROM stylists WHERE id=?", (link["stylist_id"],)).fetchone()
                telegram_send(chat_id, f"✅ Telegram akkauntingiz {stylist['name']} profiliga bog‘landi. Endi faqat o‘zingizga tegishli yangi zakaslar haqida xabar olasiz.")
    else:
        telegram_send(chat_id, "Bog‘lash uchun /link KOD buyrug‘idan foydalaning.")
    return jsonify({"ok": True})


@app.post("/admin/stylist/<int:stylist_id>/telegram-code")
def create_stylist_telegram_code(stylist_id):
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))
    code = secrets.token_urlsafe(6)
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    from datetime import timedelta
    expires = (datetime.now() + timedelta(minutes=15)).isoformat(timespec="seconds")
    with db() as con:
        stylist = con.execute("SELECT name FROM stylists WHERE id=? AND active=1", (stylist_id,)).fetchone()
        if not stylist:
            flash("Sartarosh topilmadi.")
        else:
            con.execute("INSERT INTO telegram_link_codes(stylist_id,code_hash,expires_at,used_at) VALUES(?,?,?,?)",
                        (stylist_id, code_hash, expires, ""))
            flash(f"{stylist['name']} uchun bir martalik kod: {code} — 15 daqiqa amal qiladi. Sartarosh botga /link {code} yuborsin.")
    return redirect(url_for("admin"))


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
        stylist_rows = con.execute("SELECT id,name,telegram_chat_id FROM stylists WHERE active=1 ORDER BY id").fetchall() if session["role"] == "admin" else []
    return render_template("admin.html", bookings=rows, stylists=stylist_rows, shop_name=SHOP_NAME,
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
configure_telegram_webhook()
if __name__ == "__main__":
    app.run(host="127.0.0.1",port=5000,debug=True)
