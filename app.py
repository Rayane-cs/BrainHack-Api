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

load_dotenv()

app = Flask(__name__)

# Enable CORS for all routes using ALLOWED_ORIGINS from environment
allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

@app.after_request
def add_cors_headers(response):
    # FORCE '*' to guarantee CORS fix - fallback for all requests
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

@app.before_request
def log_request():
    print(f"[DEBUG_REQUEST] {request.method} {request.path} from {request.headers.get('Origin')}")
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

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
    # Prioritize full URI env names (Railway-style might provide one URL string)
    potential_uri = (
        os.getenv("DB_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("MYSQL_URL")
        or os.getenv("DB_HOST")
        or os.getenv("MYSQL_HOST")
    )

    if potential_uri and potential_uri.startswith("mysql://"):
        return parse_mysql_url(potential_uri)

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

def init_db_pool():
    global connection_pool
    if connection_pool is not None:
        return connection_pool
    try:
        connection_pool = pooling.MySQLConnectionPool(
            pool_name="brainhack_pool",
            pool_size=5,
            **DB_CONFIG
        )
        return connection_pool
    except Exception as e:
        print(f"[DB POOL ERROR] {e}")
        connection_pool = None
        return None


def get_db():
    pool = init_db_pool()
    if pool is None:
        raise RuntimeError("Database connection pool is not available. Check DB env vars and server status.")
    return pool.get_connection()

# ─── Email Config ─────────────────────────────────────────────────────────────
SMTP_HOST   = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", 587))
SMTP_USER   = os.getenv("SMTP_USER", "")
SMTP_PASS   = os.getenv("SMTP_PASS", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

def send_email_sync(to: str, subject: str, html: str):
    _app_pass = SMTP_PASS.replace(' ', '')
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"BrainHack <{SMTP_USER}>"
    msg["To"]      = to
    msg.attach(MIMEText(html, "html"))

    # Try SSL on port 465 first, fall back to STARTTLS
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=15) as server:
            server.login(SMTP_USER, _app_pass)
            server.sendmail(SMTP_USER, to, msg.as_string())
        print(f'[EMAIL OK] {to} (SSL 465)')
        return True
    except Exception as e1:
        print(f'[EMAIL] SSL 465 failed ({e1}), trying STARTTLS {SMTP_PORT}...')
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(SMTP_USER, _app_pass)
                server.sendmail(SMTP_USER, to, msg.as_string())
            print(f'[EMAIL OK] {to} (STARTTLS {SMTP_PORT})')
            return True
        except Exception as e2:
            print(f'[EMAIL ERROR] {to}: SSL={e1} | TLS={e2}')
            return False

import threading

def send_email(to: str, subject: str, html: str):
    # Fire and forget email sending to avoid blocking the API response
    thread = threading.Thread(target=send_email_sync, args=(to, subject, html))
    thread.start()
    return True

# ─── Email Templates ──────────────────────────────────────────────────────────
BASE_STYLE = """
<style>
  body { font-family: 'Segoe UI', sans-serif; background:#03030d; color:#e2e8ff; margin:0; padding:0; }
  .container { max-width:600px; margin:40px auto; background:#07071a; border:1px solid #1c1c45;
               border-radius:12px; overflow:hidden; }
  .header { background:linear-gradient(135deg,#0c0c26,#111138); padding:40px 32px; text-align:center;
            border-bottom: 1px solid #1c1c45; }
  .header-bar { height:3px; background:linear-gradient(90deg,#6366f1,#a78bfa,#22d3ee); margin-bottom:0; }
  .header h1 { margin:0; font-size:28px; color:#818cf8; letter-spacing:4px; }
  .header p  { margin:8px 0 0; color:#7b82c4; font-size:13px; letter-spacing:2px; }
  .body { padding:32px; }
  .body h2 { color:#818cf8; font-size:20px; margin-top:0; }
  .body p  { color:#7b82c4; line-height:1.7; }
  .highlight { background:#0c0c26; border-left:3px solid #818cf8; padding:12px 16px;
               border-radius:0 8px 8px 0; margin:16px 0; color:#e2e8ff; }
  .badge { display:inline-block; padding:4px 12px; border-radius:999px; font-size:12px;
           font-weight:700; letter-spacing:1px; margin-bottom:16px; }
  .badge-green  { background:#1e1e5e; color:#818cf8; border:1px solid #818cf8; }
  .badge-red    { background:#2d0f0f; color:#f87171; border:1px solid #f87171; }
  .footer { padding:20px 32px; text-align:center; border-top:1px solid #1c1c45;
            color:#3a3a72; font-size:12px; }
</style>
"""

def tpl_received(name: str) -> str:
    return f"""<!DOCTYPE html><html><head>{BASE_STYLE}</head><body>
<div class="container">
  <div class="header-bar"></div>
  <div class="header"><h1>BRAINHACK</h1><p>InfoBrain Club · Hackathon 2026</p></div>
  <div class="body">
    <span class="badge badge-green">REGISTRATION RECEIVED</span>
    <h2>Hey {name}, you're in the queue! 🧠</h2>
    <p>We've received your registration for <strong>BrainHack</strong> — the InfoBrain Club Hackathon.</p>
    <div class="highlight">Our team will review your application and get back to you soon. Keep an eye on your inbox!</div>
    <p>The event takes place <strong>April 17–18, 2026</strong>. Stay tuned for updates.</p>
    <p style="color:#818cf8;">— The BrainHack Team</p>
  </div>
  <div class="footer">BrainHack · InfoBrain Club · Hassiba Ben Bouali University, Chlef</div>
</div></body></html>"""

def tpl_accepted(name: str) -> str:
    return f"""<!DOCTYPE html><html><head>{BASE_STYLE}</head><body>
<div class="container">
  <div class="header-bar"></div>
  <div class="header"><h1>BRAINHACK</h1><p>InfoBrain Club · Hackathon 2026</p></div>
  <div class="body">
    <span class="badge badge-green">ACCEPTED ✓</span>
    <h2>Congratulations, {name}! 🎉</h2>
    <p>We're thrilled to confirm that your application to <strong>BrainHack</strong> has been <strong style="color:#818cf8;">accepted</strong>!</p>
    <div class="highlight">📅 <strong>April 17–18, 2026</strong><br>Day 1 kicks off at 09:00. Full schedule will be shared closer to the event.</div>
    <p>Get ready to build, innovate, and compete. We'll send more details about the venue and logistics soon.</p>
    <p style="color:#818cf8;">— The BrainHack Team</p>
  </div>
  <div class="footer">BrainHack · InfoBrain Club · Hassiba Ben Bouali University, Chlef</div>
</div></body></html>"""

def tpl_rejected(name: str) -> str:
    return f"""<!DOCTYPE html><html><head>{BASE_STYLE}</head><body>
<div class="container">
  <div class="header-bar"></div>
  <div class="header"><h1>BRAINHACK</h1><p>InfoBrain Club · Hackathon 2026</p></div>
  <div class="body">
    <span class="badge badge-red">APPLICATION UPDATE</span>
    <h2>Thank you for applying, {name}</h2>
    <p>After careful review, we regret to inform you that we're unable to accommodate your participation in <strong>BrainHack</strong> this time due to limited spots.</p>
    <div class="highlight">We truly appreciate your interest and encourage you to keep building and innovating. Future editions of BrainHack will be open for registration!</div>
    <p>Thank you for being part of the InfoBrain community.</p>
    <p style="color:#818cf8;">— The BrainHack Team</p>
  </div>
  <div class="footer">BrainHack · InfoBrain Club · Hassiba Ben Bouali University, Chlef</div>
</div></body></html>"""

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "registration_open": registration_open()}), 200


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
        send_email(
            data["email"],
            "BrainHack — Registration Received ✓",
            tpl_received(data["full_name"])
        )
        return jsonify({"message": "Registration successful"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: conn.close()


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
            send_email(row["email"], "BrainHack — You're Accepted! 🎉", tpl_accepted(row["full_name"]))
        else:
            send_email(row["email"], "BrainHack — Application Update", tpl_rejected(row["full_name"]))

        return jsonify({"message": f"Participant {status}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:  cur.close()
        if conn: conn.close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
