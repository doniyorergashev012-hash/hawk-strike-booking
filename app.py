import os, sqlite3, hmac, hashlib, json, secrets
from datetime import datetime, date, timedelta
from urllib.parse import parse_qsl
import requests
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid

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
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

2
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
def get_shop_name():
    with db() as con:
        saved = con.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key='shop_name'"
        ).fetchone()

    if saved and saved["setting_value"].strip():
        return saved["setting_value"].strip()

    return SHOP_NAME


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
        # Safe additive migrations: keep existing stylists, services and bookings intact.
        if DATABASE_URL:
            for column, definition in [
                ("bio", "TEXT DEFAULT ''"), ("experience", "TEXT DEFAULT ''"),
                ("specialties", "TEXT DEFAULT ''")]:
                con.execute(f"ALTER TABLE stylists ADD COLUMN IF NOT EXISTS {column} {definition}")
            con.execute("ALTER TABLE services ADD COLUMN IF NOT EXISTS stylist_id BIGINT")
            con.execute("ALTER TABLE services ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''")
            con.execute("ALTER TABLE services ADD COLUMN IF NOT EXISTS photo TEXT DEFAULT ''")
            con.execute("CREATE TABLE IF NOT EXISTS stylist_certificates (id BIGSERIAL PRIMARY KEY, stylist_id BIGINT NOT NULL, title TEXT NOT NULL, photo TEXT NOT NULL DEFAULT '')")
            con.execute("CREATE TABLE IF NOT EXISTS app_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL DEFAULT '')")
            con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('shop_name',?) ON CONFLICT(setting_key) DO NOTHING", (SHOP_NAME,))
        else:
            stylist_cols = {r[1] for r in con.execute("PRAGMA table_info(stylists)").fetchall()}
            for column in ("bio", "experience", "specialties"):
                if column not in stylist_cols:
                    con.execute(f"ALTER TABLE stylists ADD COLUMN {column} TEXT DEFAULT ''")
            service_cols = {r[1] for r in con.execute("PRAGMA table_info(services)").fetchall()}
            for column, definition in [("stylist_id", "INTEGER"), ("description", "TEXT DEFAULT ''"), ("photo", "TEXT DEFAULT ''")]:
                if column not in service_cols:
                    con.execute(f"ALTER TABLE services ADD COLUMN {column} {definition}")
            con.execute("CREATE TABLE IF NOT EXISTS stylist_certificates (id INTEGER PRIMARY KEY AUTOINCREMENT, stylist_id INTEGER NOT NULL, title TEXT NOT NULL, photo TEXT NOT NULL DEFAULT '')")
            con.execute("CREATE TABLE IF NOT EXISTS app_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL DEFAULT '')")
            con.execute("INSERT OR IGNORE INTO app_settings(setting_key,setting_value) VALUES('shop_name',?)", (SHOP_NAME,))
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
        # Convert legacy shared services into a copy for each barber without deleting old rows
        # (old bookings continue to reference their original service IDs).
        legacy = con.execute("SELECT id,name,name_ru,duration,price,description,photo FROM services WHERE stylist_id IS NULL AND active=1 ORDER BY id").fetchall()
        if legacy:
            stylist_ids = [r["id"] for r in con.execute("SELECT id FROM stylists WHERE active=1 ORDER BY id").fetchall()]
            for old in legacy:
                for sid in stylist_ids:
                    exists = con.execute("SELECT 1 FROM services WHERE stylist_id=? AND name=?", (sid, old["name"])).fetchone()
                    if not exists:
                        con.execute("INSERT INTO services(name,name_ru,duration,price,active,stylist_id,description,photo) VALUES(?,?,?,?,1,?,?,?)",
                                    (old["name"], old["name_ru"], old["duration"], old["price"], sid, old["description"] or "", old["photo"] or ""))
            con.execute("UPDATE services SET active=0 WHERE stylist_id IS NULL")
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
        services = con.execute("SELECT * FROM services WHERE active=1 AND stylist_id IS NOT NULL ORDER BY stylist_id,id").fetchall()
        certificates = con.execute("SELECT * FROM stylist_certificates ORDER BY stylist_id,id").fetchall()
        saved_name = con.execute("SELECT setting_value FROM app_settings WHERE setting_key='shop_name'").fetchone()
        current_shop_name = get_shop_name()
    return render_template("landing.html", stylists=stylists, services=services, certificates=certificates,
                           shop_name=current_shop_name,
                           address=os.getenv("SHOP_ADDRESS", "Manzil tez orada qo‘shiladi"),
                           maps_url=os.getenv("MAPS_URL", ""))


@app.get("/app")
def index():
    with db() as con:
        stylists = con.execute("SELECT * FROM stylists WHERE active=1 ORDER BY id").fetchall()
        services = con.execute("SELECT * FROM services WHERE active=1 AND stylist_id IS NOT NULL ORDER BY stylist_id,id").fetchall()
        certificates = con.execute("SELECT * FROM stylist_certificates ORDER BY stylist_id,id").fetchall()
        current_shop_name = get_shop_name()
    stylist_data = [dict(row) for row in stylists]
    certificate_data = [dict(row) for row in certificates]
    return render_template("index.html", stylists=stylists, services=services, certificates=certificates,
                           stylist_data=stylist_data, certificate_data=certificate_data,
                           shop_name=current_shop_name, selected_service=request.args.get("service", ""))



@app.get("/api/slots")
def slots():
    stylist_id = request.args.get("stylist_id", type=int)
    day = request.args.get("date", "")
    service_id = request.args.get("service_id", type=int)

    try:
        selected = date.fromisoformat(day)
    except ValueError:
        return jsonify({"slots": [], "error": "Invalid date"}), 400

    if selected < date.today():
        return jsonify({"slots": []})

    # Har 30 daqiqada boshlanadigan vaqtlar
    times = [
        f"{h:02d}:{m:02d}"
        for h in range(9, 24)
        for m in (0, 30)
    ]

    with db() as con:
        service = con.execute("""
            SELECT duration
            FROM services
            WHERE id = ?
              AND stylist_id = ?
              AND active = 1
        """, (service_id, stylist_id)).fetchone()

        if not service:
            return jsonify({
                "slots": [],
                "error": "Service not found"
            }), 404

        bookings = con.execute("""
            SELECT b.booking_date, b.booking_time, s.duration
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            WHERE b.stylist_id = ?
              AND b.booking_date IN (?, ?)
              AND b.status != 'cancelled'
        """, (
            stylist_id,
            (selected - timedelta(days=1)).isoformat(),
            day
        )).fetchall()

    busy_periods = []

    for booking in bookings:
        start = datetime.strptime(
            f'{booking["booking_date"]} {booking["booking_time"]}',
            "%Y-%m-%d %H:%M"
        )

        duration = int(booking["duration"] or 30)

        # Davomiylikni 30 daqiqalik oraliqqa yaxlitlash
        duration = ((duration + 29) // 30) * 30
        end = start + timedelta(minutes=duration)

        busy_periods.append((start, end))

    available = []

    new_duration = int(service["duration"] or 30)
    new_duration = ((new_duration + 29) // 30) * 30

    for t in times:
        start = datetime.strptime(
            f"{day} {t}",
            "%Y-%m-%d %H:%M"
        )

        end = start + timedelta(minutes=new_duration)

        is_busy = any(
            start < busy_end and end > busy_start
            for busy_start, busy_end in busy_periods
        )

        if not is_busy:
            available.append(t)

    return jsonify({"slots": available})


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
        service = con.execute("SELECT name,name_ru,price,duration FROM services WHERE id=? AND active=1 AND stylist_id=?",(service_id,stylist_id)).fetchone()
        if not stylist or not service:
            return jsonify({"ok":False,"message":"Tanlov topilmadi / Выбор не найден."}), 404
        # Yangi bron davomiyligini 30 daqiqaga yaxlitlash
        start_time = datetime.strptime(f"{day} {time}", "%Y-%m-%d %H:%M")
        duration = int(service["duration"] or 30)
        duration = ((duration + 29) // 30) * 30
        end_time = start_time + timedelta(minutes=duration)

        # Shu sartaroshning mavjud bronlarini tekshirish
        existing_bookings = con.execute("""
            SELECT b.booking_date, b.booking_time, s.duration
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            WHERE b.stylist_id = ?
              AND b.booking_date IN (?, ?)
              AND b.status != 'cancelled'
        """, (stylist_id, (selected - timedelta(days=1)).isoformat(), day)).fetchall()

        for booking in existing_bookings:
            old_start = datetime.strptime(
                f'{booking["booking_date"]} {booking["booking_time"]}',
                "%Y-%m-%d %H:%M"
            )
            old_duration = int(booking["duration"] or 30)
            old_duration = ((old_duration + 29) // 30) * 30
            old_end = old_start + timedelta(minutes=old_duration)

            if start_time < old_end and end_time > old_start:
                return jsonify({
                    "ok": False,
                    "message": "Bu vaqt band. Boshqa vaqtni tanlang."
                }), 409
        try:
            con.execute("""INSERT INTO bookings(stylist_id,service_id,customer_name,phone,booking_date,
    booking_time,telegram_id,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (stylist_id,service_id,name,phone,day,time,telegram_id,datetime.now().isoformat(timespec="seconds")))
        except (sqlite3.IntegrityError, UniqueViolation):
            return jsonify({"ok":False,"message":"Bu vaqt band / Это время уже занято."}), 409
    try:
        pretty_day = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        pretty_day = day
    message = (
        f"✂️ {get_shop_name().upper()}\n"
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
        telegram_send(chat_id, f"{get_shop_name()} sartarosh akkauntini bog‘lash uchun admin bergan kodni yuboring:\n/link KOD")
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
        if session["role"] == "admin":
            stylist_rows = con.execute("SELECT * FROM stylists ORDER BY id").fetchall()
            managed_stylist_id = None
        else:
            stylist_rows = con.execute("SELECT * FROM stylists WHERE id=?", (session["stylist_id"],)).fetchall()
            managed_stylist_id = session["stylist_id"]
        managed_services = con.execute("SELECT * FROM services WHERE stylist_id IN (SELECT id FROM stylists WHERE active=1) ORDER BY stylist_id,id").fetchall() if session["role"] == "admin" else con.execute("SELECT * FROM services WHERE stylist_id=? ORDER BY id", (managed_stylist_id,)).fetchall()
        certificates = con.execute("SELECT * FROM stylist_certificates ORDER BY stylist_id,id").fetchall() if session["role"] == "admin" else con.execute("SELECT * FROM stylist_certificates WHERE stylist_id=? ORDER BY id", (managed_stylist_id,)).fetchall()
    return render_template("admin.html", bookings=rows, stylists=stylist_rows, services=managed_services, certificates=certificates, shop_name=get_shop_name(),
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


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        return ""
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Faqat PNG, JPG, JPEG yoki WEBP rasmlar qabul qilinadi.")
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(UPLOAD_DIR, filename))
    return f"uploads/{filename}"


def can_manage_stylist(stylist_id):
    if session.get("role") == "admin":
        return True
    return session.get("role") == "barber" and session.get("stylist_id") == stylist_id


@app.post("/admin/shop-name")
def update_shop_name():
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))
    new_name = request.form.get("shop_name", "").strip()
    if not new_name or len(new_name) > 80:
        flash("Barbershop nomi 1–80 belgi oralig‘ida bo‘lishi kerak.")
        return redirect(url_for("admin"))
    with db() as con:
        con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('shop_name',?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value", (new_name,))
    global SHOP_NAME
    SHOP_NAME = new_name
    flash("Barbershop nomi saqlandi.")
    return redirect(url_for("admin"))


@app.post("/admin/stylist/<int:stylist_id>/deactivate")
def deactivate_stylist(stylist_id):
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))
    with db() as con:
        stylist = con.execute("SELECT id,name,active FROM stylists WHERE id=?", (stylist_id,)).fetchone()
        if not stylist:
            flash("Sartarosh topilmadi.")
            return redirect(url_for("admin"))
        if not stylist["active"]:
            flash("Bu sartarosh avval o‘chirilgan.")
            return redirect(url_for("admin"))
        # Soft-delete: retain stylist, services, Telegram association and booking history.
        con.execute("UPDATE stylists SET active=0 WHERE id=?", (stylist_id,))
        con.execute("UPDATE services SET active=0 WHERE stylist_id=?", (stylist_id,))
        con.execute("UPDATE users SET active=0 WHERE stylist_id=?", (stylist_id,))
    flash(f"{stylist['name']} faoliyatdan chiqarildi. Eski buyurtmalar va Telegram tarixi saqlandi.")
    return redirect(url_for("admin"))


@app.post("/admin/stylist/add")
def add_stylist():
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    if not name or not username or not username.replace("_", "").isalnum() or len(password) < 8:
        flash("Sartarosh ismi va loginini to‘g‘ri kiriting.")
        return redirect(url_for("admin"))
    try:
        with db() as con:
            if DATABASE_URL:
                row = con.execute("INSERT INTO stylists(name,title,active) VALUES(?,?,1) RETURNING id", (name,"BARBER")).fetchone()
                stylist_id = row["id"]
            else:
                cur = con.execute("INSERT INTO stylists(name,title,active) VALUES(?,?,1)", (name,"BARBER"))
                stylist_id = cur.lastrowid
            con.execute("INSERT INTO users(username,password_hash,role,stylist_id) VALUES(?,?,?,?)", (username, generate_password_hash(password), "barber", stylist_id))
        flash("Sartarosh qo‘shildi.")
    except Exception:
        flash("Sartarosh qo‘shilmadi. Bu login avval ishlatilgan bo‘lishi mumkin.")
    return redirect(url_for("admin"))


@app.post("/admin/stylist/<int:stylist_id>/profile")
def update_stylist_profile(stylist_id):
    if not can_manage_stylist(stylist_id):
        return redirect(url_for("admin_login"))
    try:
        photo = save_image(request.files.get("photo"))
        with db() as con:
            fields = (request.form.get("name", "").strip(), request.form.get("title", "BARBER").strip(),
                      request.form.get("bio", "").strip(), request.form.get("experience", "").strip(),
                      request.form.get("specialties", "").strip())
            if not fields[0]:
                raise ValueError("Sartarosh ismi bo‘sh bo‘lmasin.")
            if photo:
                con.execute("UPDATE stylists SET name=?,title=?,bio=?,experience=?,specialties=?,photo=? WHERE id=?", (*fields, photo, stylist_id))
            else:
                con.execute("UPDATE stylists SET name=?,title=?,bio=?,experience=?,specialties=? WHERE id=?", (*fields, stylist_id))
        flash("Sartarosh profili saqlandi.")
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("admin"))


@app.post("/admin/stylist/<int:stylist_id>/certificate")
def add_certificate(stylist_id):
    if not can_manage_stylist(stylist_id):
        return redirect(url_for("admin_login"))
    try:
        title = request.form.get("title", "").strip()
        photo = save_image(request.files.get("photo"))
        if not title or not photo:
            raise ValueError("Sertifikat nomi va rasmi kerak.")
        with db() as con:
            con.execute("INSERT INTO stylist_certificates(stylist_id,title,photo) VALUES(?,?,?)", (stylist_id,title,photo))
        flash("Sertifikat qo‘shildi.")
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("admin"))


@app.post("/admin/certificate/<int:certificate_id>/delete")
def delete_certificate(certificate_id):
    with db() as con:
        cert = con.execute("SELECT stylist_id FROM stylist_certificates WHERE id=?", (certificate_id,)).fetchone()
        if not cert or not can_manage_stylist(cert["stylist_id"]):
            return redirect(url_for("admin_login"))
        con.execute("DELETE FROM stylist_certificates WHERE id=?", (certificate_id,))
    flash("Sertifikat o‘chirildi.")
    return redirect(url_for("admin"))


@app.post("/admin/service")
def save_service():
    try:
        service_id = request.form.get("service_id", type=int)
        stylist_id = request.form.get("stylist_id", type=int)
        if not stylist_id or not can_manage_stylist(stylist_id):
            return redirect(url_for("admin_login"))
        name = request.form.get("name", "").strip()
        name_ru = request.form.get("name_ru", "").strip()
        description = request.form.get("description", "").strip()
        duration = int(request.form.get("duration", "30"))
        price = int(request.form.get("price", "0"))
        if not name or duration < 5 or duration > 300 or price < 0:
            raise ValueError("Xizmat nomi, davomiyligi yoki narxini tekshiring.")
        photo = save_image(request.files.get("photo"))
        with db() as con:
            if service_id:
                old = con.execute("SELECT stylist_id FROM services WHERE id=?", (service_id,)).fetchone()
                if not old or old["stylist_id"] != stylist_id:
                    return redirect(url_for("admin_login"))
                if photo:
                    con.execute("UPDATE services SET name=?,name_ru=?,description=?,duration=?,price=?,photo=? WHERE id=? AND stylist_id=?", (name,name_ru,description,duration,price,photo,service_id,stylist_id))
                else:
                    con.execute("UPDATE services SET name=?,name_ru=?,description=?,duration=?,price=? WHERE id=? AND stylist_id=?", (name,name_ru,description,duration,price,service_id,stylist_id))
            else:
                con.execute("INSERT INTO services(name,name_ru,description,duration,price,stylist_id,photo,active) VALUES(?,?,?,?,?,?,?,1)", (name,name_ru,description,duration,price,stylist_id,photo))
        flash("Xizmat saqlandi.")
    except (ValueError, TypeError) as e:
        flash(str(e) or "Ma’lumotlarni tekshiring.")
    return redirect(url_for("admin"))


@app.post("/admin/service/<int:service_id>/deactivate")
def deactivate_service(service_id):
    with db() as con:
        service = con.execute("SELECT stylist_id FROM services WHERE id=?", (service_id,)).fetchone()
        if not service or not can_manage_stylist(service["stylist_id"]):
            return redirect(url_for("admin_login"))
        # Keep service row so historical bookings remain readable.
        con.execute("UPDATE services SET active=0 WHERE id=?", (service_id,))
    flash("Xizmat yashirildi. Eski buyurtmalar saqlanadi.")
    return redirect(url_for("admin"))


init_db()
with db() as con:
    saved_shop = con.execute("SELECT setting_value FROM app_settings WHERE setting_key='shop_name'").fetchone()
    if saved_shop and saved_shop["setting_value"].strip():
        SHOP_NAME = saved_shop["setting_value"].strip()
configure_telegram_webhook()
if __name__ == "__main__":
    app.run(host="127.0.0.1",port=5000,debug=True)
