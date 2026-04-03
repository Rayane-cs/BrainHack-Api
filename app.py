import os
import smtplib
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


# Handle all OPTIONS preflight requests globally — must come before other handlers
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


# Catch unhandled exceptions so CORS headers are still present on 500s
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
    # Check all known env var names for a full MySQL URI (Railway injects these natively)
    # Prefer Railway's native MYSQL_URL/MYSQL_PUBLIC_URL over manual DB_URL
    for env_name in ("MYSQL_URL", "MYSQL_PUBLIC_URL", "DATABASE_URL", "DB_URL", "MYSQL_PRIVATE_URL", "DB_HOST"):
        val = os.getenv(env_name, "")
        if val.startswith(("mysql://", "mysql+mysqlconnector://", "mysql+pymysql://")):
            print(f"[DB_CONFIG] Using URI from env var: {env_name}")
            return parse_mysql_url(val)

    # Fall back to individual env vars
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
# Support both custom SMTP names and the user-suggested GMAIL_* names
SMTP_HOST   = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", 587))
SMTP_USER   = os.getenv("SMTP_USER") or os.getenv("GMAIL_ADDRESS") or ""
SMTP_PASS   = os.getenv("SMTP_PASS") or os.getenv("GMAIL_APP_PASSWORD") or ""
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

last_smtp_error = None

# Log SMTP config at startup so Railway logs show what is loaded
if not SMTP_USER or not SMTP_PASS:
    print("[SMTP_WARNING] SMTP_USER/PASS or GMAIL_ADDRESS/APP_PASSWORD are NOT set. Emails will fail.")
else:
    print(f"[SMTP_CONFIG] host={SMTP_HOST} port={SMTP_PORT} user={SMTP_USER!r} admin={ADMIN_EMAIL!r}")

def send_email_sync(to: str, subject: str, html: str):
    global last_smtp_error
    if not SMTP_USER or not SMTP_PASS:
        last_smtp_error = "SMTP_USER or SMTP_PASS not configured"
        print(f"[EMAIL SKIP] {last_smtp_error} — skipping email to {to}")
        return False

    _app_pass = SMTP_PASS.replace(' ', '')
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"BrainHack <{SMTP_USER}>"
    msg["To"]      = to
    msg.attach(MIMEText(html, "html"))

    # Try SSL on port 465 first, fall back to STARTTLS
    # FIX for Railway: Force IPv4 (AF_INET) because Railway containers often lack
    # full IPv6 routes resulting in "Network is unreachable" when resolving Gmail.
    import socket
    orig_getaddrinfo = socket.getaddrinfo
    
    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    
    socket.getaddrinfo = getaddrinfo_ipv4
    
    try:
        try:
            with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=20) as server:
                server.login(SMTP_USER, _app_pass)
                server.sendmail(SMTP_USER, to, msg.as_string())
            print(f'[EMAIL OK] {to} (SSL 465)')
            last_smtp_error = None
            return True
        except Exception as e1:
            print(f'[EMAIL] SSL 465 failed ({e1}), trying STARTTLS {SMTP_PORT}...')
            try:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(SMTP_USER, _app_pass)
                    server.sendmail(SMTP_USER, to, msg.as_string())
                print(f'[EMAIL OK] {to} (STARTTLS {SMTP_PORT})')
                last_smtp_error = None
                return True
            except Exception as e2:
                last_smtp_error = f"SSL: {e1} | TLS: {e2}"
                print(f'[EMAIL ERROR] {to}: {last_smtp_error}')
                return False
    finally:
        # Always restore the original socket resolver
        socket.getaddrinfo = orig_getaddrinfo

import threading

def send_email(to: str, subject: str, html: str):
    # Send synchronously since background threads spawned inside Flask requests
    # can be immediately killed by Gunicorn once the HTTP response is returned.
    # It takes ~1-2 seconds but guarantees delivery.
    return send_email_sync(to, subject, html)

# ─── Email Templates ──────────────────────────────────────────────────────────
# All templates have been moved to backend/email_templates.py to keep app.py clean.

# ─── Routes ───────────────────────────────────────────────────────────────────

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
        cur.execute("SELECT email, phone, registration_number FROM participants WHERE email=%s OR phone=%s OR registration_number=%s LIMIT 1", 
                    (data["email"], data["phone"], data["registration_number"]))
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


@app.route("/api/send-confirmation", methods=["POST"])
def send_confirmation():
    data = request.get_json(force=True) or {}
    email = data.get("email")

    if not email:
        return jsonify({"error": "Missing email"}), 400

    # Send the email synchronously to guarantee delivery since Gunicorn
    # can kill background threads.
    success = send_email(
        email,
        "BrainHack — Registration Received ✓",
        get_registration_email_html(data)
    )
    
    if success:
        return jsonify({"message": "Confirmation email sent"}), 200
    else:
        return jsonify({
            "error": "Failed to send email",
            "details": last_smtp_error
        }), 500


@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.get_json(force=True) or {}
    for f in ["name", "email", "message"]:
        if not data.get(f, "").strip():
            return jsonify({"error": f"Missing field: {f}"}), 400

    html = f"""<div style="font-family:sans-serif;background:#03030d;color:#e2e8ff;padding:24px;">
        <h2 style="color:#818cf8;">New Question — BrainHack</h2>
        <p><strong>Name:</strong> {data['name']}</p>
        <p><strong>Email:</strong> {data['email']}</p>
        <p><strong>Message:</strong><br>{data['message']}</p>
    </div>"""
    ok = send_email(ADMIN_EMAIL, f"BrainHack Question from {data['name']}", html)
    if ok:
        return jsonify({"message": "Message sent"}), 200
    return jsonify({"error": "Failed to send email"}), 500


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
