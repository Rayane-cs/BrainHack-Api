import os
import smtplib
import json
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv
from email_templates import (
    get_registration_email_html,
    get_accepted_email_html,
    get_rejected_email_html
)
import socket
import threading

# ─── Railway Network Fix: Force IPv4 globally ────────────────────────────────
orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

load_dotenv()

app = Flask(__name__)

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=False)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS, PUT, DELETE",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _add_cors(response):
    for k, v in CORS_HEADERS.items():
        response.headers[k] = v
    return response


@app.before_request
def handle_preflight():
    from flask import request as req
    if req.method == "OPTIONS":
        from flask import make_response
        resp = make_response("", 204)
        for k, v in CORS_HEADERS.items():
            resp.headers[k] = v
        return resp


@app.after_request
def after_request_cors(response):
    return _add_cors(response)


@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    print(f"[SERVER ERROR] {e}")
    traceback.print_exc()
    response = jsonify({"error": str(e)})
    response.status_code = 500
    return _add_cors(response)


@app.errorhandler(500)
def handle_500(e):
    print(f"[500 ERROR] {e}")
    response = jsonify({"error": "Internal server error"})
    response.status_code = 500
    return _add_cors(response)

# ─── Registration Deadline ────────────────────────────────────────────────────
REG_DEADLINE = datetime(2026, 4, 15, 23, 59, 59, tzinfo=timezone.utc)

def registration_open() -> bool:
    return datetime.now(timezone.utc) < REG_DEADLINE

# ─── DB Config ────────────────────────────────────────────────────────────────
from urllib.parse import urlparse


def parse_mysql_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("mysql", "mysql+mysqlconnector", "mysql+pymysql"):
        raise ValueError(f"Unsupported DB URL scheme: {parsed.scheme}")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": parsed.path.lstrip("/") or "brainhack",
    }


def get_db_config():
    for env_name in ("MYSQL_URL", "MYSQL_PUBLIC_URL", "DATABASE_URL", "DB_URL", "MYSQL_PRIVATE_URL", "DB_HOST"):
        val = os.getenv(env_name, "")
        if val.startswith(("mysql://", "mysql+mysqlconnector://", "mysql+pymysql://")):
            print(f"[DB_CONFIG] Using URI from env var: {env_name}")
            return parse_mysql_url(val)

    return {
        "host": os.getenv("DB_HOST", os.getenv("MYSQL_HOST", "localhost")),
        "port": int(os.getenv("DB_PORT", os.getenv("MYSQL_PORT", 3306))),
        "user": os.getenv("DB_USER", os.getenv("MYSQL_USER", "root")),
        "password": os.getenv("DB_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        "database": os.getenv("DB_NAME", os.getenv("MYSQL_DATABASE", "brainhack")),
    }


DB_CONFIG = get_db_config()
print(f"[DB_CONFIG] host={DB_CONFIG['host']} port={DB_CONFIG['port']} user={DB_CONFIG['user']} db={DB_CONFIG['database']}")

connection_pool = None
last_pool_error = None

def init_db_pool():
    global connection_pool, last_pool_error
    if connection_pool is not None:
        return connection_pool
    try:
        connection_pool = pooling.MySQLConnectionPool(
            pool_name="brainhack_pool",
            pool_size=5,
            **DB_CONFIG
        )
        last_pool_error = None
        return connection_pool
    except Exception as e:
        print(f"[DB POOL ERROR] {e}")
        last_pool_error = str(e)
        connection_pool = None
        return None


def get_db():
    pool = init_db_pool()
    if pool is None:
        raise RuntimeError(f"Database connection pool is not available. Check DB env vars and server status. Error: {last_pool_error}")
    return pool.get_connection()

# ─── Email Config ─────────────────────────────────────────────────────────────
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", 587))
SMTP_USER      = os.getenv("SMTP_USER") or os.getenv("GMAIL_ADDRESS") or ""
SMTP_PASS      = os.getenv("SMTP_PASS") or os.getenv("GMAIL_APP_PASSWORD") or ""
ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "")

# Resend API support (https://resend.com)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM    = os.getenv("RESEND_FROM", f"BrainHack <{SMTP_USER}>")

last_smtp_error = None

if not SMTP_USER or not SMTP_PASS:
    print("[SMTP_WARNING] SMTP_USER/PASS or GMAIL_ADDRESS/APP_PASSWORD are NOT set. Emails will fail.")
else:
    print(f"[SMTP_CONFIG] host={SMTP_HOST} port={SMTP_PORT} user={SMTP_USER!r} admin={ADMIN_EMAIL!r}")


def send_email_resend(to: str, subject: str, html: str) -> bool:
    global last_smtp_error
    if not RESEND_API_KEY:
        last_smtp_error = "RESEND_API_KEY not configured"
        return False

    payload = {
        "from": RESEND_FROM,
        "to": to,
        "subject": subject,
        "html": html
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {RESEND_API_KEY}"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.getcode()
            if 200 <= status < 300:
                print(f"[RESEND] Email sent to {to} (status={status})")
                last_smtp_error = None
                return True
            last_smtp_error = f"Resend API status {status}"
            print(f"[RESEND] failed: {last_smtp_error}")
            return False
    except Exception as e:
        last_smtp_error = str(e)
        print(f"[RESEND] error: {e}")
        return False


def send_email_sync(to: str, subject: str, html: str):
    global last_smtp_error
    if not to or not str(to).strip():
        last_smtp_error = "Recipient email is missing"
        print(f"[EMAIL SKIP] {last_smtp_error} — skipping subject {subject}")
        return False

    to = str(to).strip()

    # Try Resend first (preferred API-based fallback in blocked SMTP environments)
    if RESEND_API_KEY:
        print("[RESEND] Using Resend API")
        if send_email_resend(to, subject, html):
            return True
        print(f"[RESEND] failed, will try SMTP fallback, last error: {last_smtp_error}")

    if not SMTP_USER or not SMTP_PASS:
        last_smtp_error = "SMTP_USER or SMTP_PASS not configured"
        print(f"[EMAIL SKIP] {last_smtp_error} — skipping email to {to}")
        return False

    _app_pass = SMTP_PASS.replace(' ', '')
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"BrainHack <{SMTP_USER}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    TIMEOUT = 10

    if SMTP_PORT == 587:
        print(f"[SMTP] Attempting STARTTLS on {SMTP_HOST}:{SMTP_PORT} (timeout={TIMEOUT}s)...")
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USER, _app_pass)
                server.sendmail(SMTP_USER, to, msg.as_string())
            print(f"[EMAIL OK] {to} (STARTTLS {SMTP_PORT})")
            last_smtp_error = None
            return True
        except Exception as e:
            print(f"[SMTP] STARTTLS failed: {e}")
            last_smtp_error = str(e)

        print(f"[SMTP] Falling back to SSL on {SMTP_HOST}:465...")
        try:
            with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=TIMEOUT) as server:
                server.login(SMTP_USER, _app_pass)
                server.sendmail(SMTP_USER, to, msg.as_string())
            print(f"[EMAIL OK] {to} (SSL 465 fallback)")
            last_smtp_error = None
            return True
        except Exception as e:
            print(f"[SMTP] SSL fallback failed: {e}")
            last_smtp_error = f"587: {last_smtp_error} | 465: {e}"
            return False

    else:
        print(f"[SMTP] Attempting SSL on {SMTP_HOST}:465 (timeout={TIMEOUT}s)...")
        try:
            with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=TIMEOUT) as server:
                server.login(SMTP_USER, _app_pass)
                server.sendmail(SMTP_USER, to, msg.as_string())
            print(f"[EMAIL OK] {to} (SSL 465)")
            last_smtp_error = None
            return True
        except Exception as e:
            print(f"[SMTP] SSL 465 failed: {e}")
            last_smtp_error = str(e)

        print(f"[SMTP] Falling back to STARTTLS on {SMTP_HOST}:{SMTP_PORT}...")
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USER, _app_pass)
                server.sendmail(SMTP_USER, to, msg.as_string())
            print(f"[EMAIL OK] {to} (STARTTLS {SMTP_PORT} fallback)")
            last_smtp_error = None
            return True
        except Exception as e:
            print(f"[SMTP] STARTTLS fallback failed: {e}")
            last_smtp_error = f"465: {last_smtp_error} | {SMTP_PORT}: {e}"
            return False


def send_email(to: str, subject: str, html: str):
    """Fire-and-forget: spawns a daemon thread so HTTP response is never blocked by SMTP."""
    t = threading.Thread(target=send_email_sync, args=(to, subject, html), daemon=True)
    t.start()
    return True


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/test-smtp", methods=["GET"])
def test_smtp():
    result = send_email_sync(
        ADMIN_EMAIL,
        "BrainHack SMTP Test",
        "<p>Test email from Railway</p>"
    )
    return jsonify({"sent": result, "last_error": last_smtp_error}), 200


@app.route("/api/health", methods=["GET"])
def health():
    safe_config = DB_CONFIG.copy()
    if "password" in safe_config:
        safe_config["password"] = "***"
    return jsonify({
        "status": "ok",
        "registration_open": registration_open(),
        "db_config": safe_config,
        "db_pool_error": last_pool_error
    }), 200


@app.route("/api/register", methods=["POST"])
def register():
    if not registration_open():
        return jsonify({"error": "Registration is closed"}), 403

    data = request.get_json(force=True) or {}
    required = ["full_name", "email", "phone", "registration_number", "level", "speciality"]
    for field in required:
        if not data.get(field, "").strip():
            return jsonify({"error": f"Missing field: {field}"}), 400

    valid_levels = {"L1", "L2", "L3", "M1", "M2"}
    if data["level"] not in valid_levels:
        return jsonify({"error": "Invalid level"}), 400

    conn = cur = None
    try:
        conn = get_db()
        cur  = conn.cursor(buffered=True)
        cur.execute(
            "SELECT email, phone, registration_number FROM participants WHERE email=%s OR phone=%s OR registration_number=%s LIMIT 1",
            (data["email"], data["phone"], data["registration_number"])
        )
        row = cur.fetchone()
        if row:
            if row[0] == data["email"]:
                return jsonify({"error": "Email already registered"}), 409
            if row[1] == data["phone"]:
                return jsonify({"error": "Phone number already registered"}), 409
            if row[2] == data["registration_number"]:
                return jsonify({"error": "Registration number already registered"}), 409
            return jsonify({"error": "Participant already registered"}), 409

        cur.execute("""
            INSERT INTO participants
              (full_name, email, phone, registration_number, level, speciality, portfolio_link)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            data["full_name"], data["email"], data["phone"],
            data["registration_number"], data["level"], data["speciality"],
            data.get("portfolio_link", "").strip()
        ))
        conn.commit()
        return jsonify({"message": "Registration successful"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: conn.close()


@app.route("/api/check-email", methods=["POST"])
def check_email():
    data = request.get_json(force=True) or {}
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Missing email"}), 400

    conn = cur = None
    try:
        conn = get_db()
        cur  = conn.cursor(buffered=True)
        cur.execute("SELECT id FROM participants WHERE email=%s LIMIT 1", (email,))
        row = cur.fetchone()
        return jsonify({"available": row is None}), 200
    except Exception as e:
        print(f"[CHECK EMAIL ERROR] {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: conn.close()


@app.route("/api/send-confirmation", methods=["POST"])
def send_confirmation():
    data = request.get_json(force=True) or {}
    email = str(data.get("email", "")).strip()

    if not email:
        return jsonify({"error": "Missing recipient email"}), 400

    if not SMTP_USER or not SMTP_PASS:
        print("[SMTP INFO] send_confirmation: SMTP not configured, skipping real send")
        return jsonify({"message": "Confirmation email is disabled on this server"}), 200

    html = get_registration_email_html(data)

    # Respond immediately — SMTP runs in background thread
    threading.Thread(
        target=send_email_sync,
        args=(email, "BrainHack — Registration Received ✓", html),
        daemon=True
    ).start()

    return jsonify({"message": "Confirmation email sent"}), 200


@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.get_json(force=True) or {}

    required = {"name": "Name", "email": "Email", "message": "Message"}
    for key, label in required.items():
        if not str(data.get(key, "")).strip():
            return jsonify({"error": f"Missing field: {label}"}), 400

    contact_email = str(data["email"]).strip()
    if not contact_email:
        return jsonify({"error": "Invalid sender email"}), 400

    recipient = ADMIN_EMAIL.strip() if ADMIN_EMAIL and ADMIN_EMAIL.strip() else SMTP_USER.strip()
    if not recipient:
        print("[SMTP INFO] contact: no recipient configured, disabling real send")
        return jsonify({"message": "Contact form is temporarily disabled"}), 200

    html = f"""<div style='font-family:sans-serif;background:#03030d;color:#e2e8ff;padding:24px;'>
        <h2 style='color:#818cf8;'>New Question — BrainHack</h2>
        <p><strong>Name:</strong> {data['name']}</p>
        <p><strong>Email:</strong> {contact_email}</p>
        <p><strong>Message:</strong><br>{data['message']}</p>
    </div>"""

    # Respond immediately — SMTP runs in background thread
    threading.Thread(
        target=send_email_sync,
        args=(recipient, f"BrainHack Contact: {data['name']}", html),
        daemon=True
    ).start()

    return jsonify({"message": "Message sent"}), 200


@app.route("/api/participants", methods=["GET"])
def get_participants():
    conn = cur = None
    try:
        conn = get_db()
        cur  = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM participants ORDER BY created_at DESC")
        rows = cur.fetchall()
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: conn.close()


@app.route("/api/participants/<int:pid>/accept", methods=["POST"])
def accept_participant(pid):
    return _update_status(pid, "accepted")


@app.route("/api/participants/<int:pid>/reject", methods=["POST"])
def reject_participant(pid):
    return _update_status(pid, "rejected")


def _update_status(pid: int, status: str):
    conn = cur = None
    try:
        conn = get_db()
        cur  = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM participants WHERE id=%s", (pid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Participant not found"}), 404

        cur.execute("UPDATE participants SET status=%s WHERE id=%s", (status, pid))
        conn.commit()

        if status == "accepted":
            send_email(row["email"], "BrainHack — You're Accepted! 🎉", get_accepted_email_html(row["full_name"]))
        else:
            send_email(row["email"], "BrainHack — Application Update", get_rejected_email_html(row["full_name"]))

        return jsonify({"message": f"Participant {status}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: conn.close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)