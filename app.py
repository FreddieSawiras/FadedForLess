import streamlit as st
import sqlite3
import hashlib
import os
import re
import base64
import calendar as cal_module
import smtplib
import ssl
from email.message import EmailMessage
from datetime import date, datetime, timedelta


def raw_html(html: str):
    """Render raw HTML safely, stripping per-line indentation so the
    markdown parser never mistakes an indented line for a code block."""
    cleaned = "\n".join(line.strip() for line in html.strip("\n").split("\n"))
    st.markdown(cleaned, unsafe_allow_html=True)


def logo_html(height_px=42, extra_style=""):
    """The real FADEDFORLESS logo, sized for wherever it's used (navbar,
    intro screen, etc.) — swapped in for the old plain-text wordmark."""
    return f'<img src="{LOGO_IMG}" alt="FADEDFORLESS" class="brand-logo" style="height:{height_px}px; width:auto; display:block; {extra_style}" />'

# ----------------------------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# LOCAL IMAGES (logo, owner photo) — shipped in the assets/ folder next to
# this file. Loaded as base64 data URIs so they work the same whether the
# app is run locally or deployed, with no separate static-file server needed.
# ----------------------------------------------------------------------------
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
# Separate, more detailed logo used only inside emails (barber-pole crest with
# "FADED FOR LESS BARBER") — has a transparent background, so it sits right
# on top of the black email header with no white box around it.
EMAIL_LOGO_PATH = os.path.join(ASSETS_DIR, "email_logo.png")


@st.cache_data
def load_image_b64(filename):
    path = os.path.join(ASSETS_DIR, filename)
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


# ----------------------------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="FADEDFORLESS | Premium Barber",
    page_icon=LOGO_PATH,
    layout="wide",
    initial_sidebar_state="collapsed",
)

INSTAGRAM_URL = "https://www.instagram.com/fadedforless/"

LOGO_IMG = load_image_b64("logo.png")

# Real, freely-usable photography (Unsplash) — not AI generated.
IMG_HERO = "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?w=1600&q=80&auto=format&fit=crop"
IMG_ABOUT = load_image_b64("owner.jpg")
IMG_PRICE_10 = "https://images.unsplash.com/photo-1647140655214-e4a2d914971f?w=1000&q=80&auto=format&fit=crop"
IMG_PRICE_15 = "https://images.unsplash.com/photo-1567894340315-735d7c361db0?w=1000&q=80&auto=format&fit=crop"
IMG_STRIP_1 = "https://images.unsplash.com/photo-1585747860715-2ba37e788b70?w=800&q=80&auto=format&fit=crop"
IMG_STRIP_2 = "https://images.unsplash.com/photo-1621645582931-d1d3e6564943?w=800&q=80&auto=format&fit=crop"
IMG_STRIP_3 = "https://images.unsplash.com/photo-1536520002442-39764a41e987?w=800&q=80&auto=format&fit=crop"

# Style showcase — real barbering photography, one per featured cut so
# customers can see exactly what they're booking before they book it.
STYLE_SHOWCASE = [
    {"name": "Mid Fade", "tag": "Fade", "img": "https://images.unsplash.com/photo-1568339434343-2a640a1a9946?w=900&q=80&auto=format&fit=crop"},
    {"name": "Low Fade", "tag": "Fade", "img": "https://images.unsplash.com/photo-1578390432942-d323db577792?w=900&q=80&auto=format&fit=crop"},
    {"name": "Low Taper Fade", "tag": "Fade", "img": "https://images.unsplash.com/photo-1635273051839-003bf06a8751?w=900&q=80&auto=format&fit=crop"},
    {"name": "Lineup", "tag": "Edge Up", "img": "https://images.unsplash.com/photo-1599011176306-4a96f1516d4d?w=900&q=80&auto=format&fit=crop"},
    {"name": "Beard Trim", "tag": "Beard", "img": "https://images.unsplash.com/photo-1630827020718-3433092696e7?w=900&q=80&auto=format&fit=crop"},
    {"name": "Undercut", "tag": "Cut", "img": "https://images.unsplash.com/photo-1562004760-aceed7bb0fe3?w=900&q=80&auto=format&fit=crop"},
]

SERVICES = {
    "Fade or Trim - $10 (30 min)": {"label": "Fade or Trim", "price": "$10", "duration": "30 min"},
    "Full Haircut - $15 (1 hour)": {"label": "Full Haircut (Fade + Trim)", "price": "$15", "duration": "1 hour"},
}

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fadedforless.db")

# ----------------------------------------------------------------------------
# DATABASE
# ----------------------------------------------------------------------------
@st.cache_resource
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            profile_pic TEXT,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    # Migration for DBs created before profile_pic existed — CREATE TABLE IF
    # NOT EXISTS above won't add a missing column to an already-existing table.
    try:
        conn.execute("ALTER TABLE users ADD COLUMN profile_pic TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already there
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service TEXT NOT NULL,
            price TEXT NOT NULL,
            appt_date TEXT NOT NULL,
            appt_time TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'Confirmed',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    # Migration for DBs created before reminder_sent existed — tracks whether
    # the "1 hour before" reminder email already went out for an appointment,
    # so the reminder_worker.py cron job never double-sends one.
    try:
        conn.execute("ALTER TABLE appointments ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already there
    # Every Style-AI recommendation a customer gets, so the owner can look
    # back at what was said to each person about their hair (Customers tab).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS style_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    conn.commit()


# ----------------------------------------------------------------------------
# PASSWORD HASHING
# ----------------------------------------------------------------------------
def hash_password(password, salt=None):
    """Salts + hashes a password with PBKDF2. Pass an existing salt (from a
    stored user record) to check a login attempt; leave it out to generate a
    brand-new salt for a new account."""
    if salt is None:
        salt = os.urandom(16).hex()
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()
    return salt, pw_hash


def create_user(name, email, phone, password):
    conn = get_conn()
    salt, pw_hash = hash_password(password)
    try:
        conn.execute(
            "INSERT INTO users (name, email, phone, salt, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name.strip(), email.strip().lower(), phone.strip(), salt, pw_hash, datetime.now().isoformat()),
        )
        conn.commit()
        notify_signup(name.strip(), email.strip().lower())
        return True, "Account created."
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists."


def verify_login(email, password):
    conn = get_conn()
    row = conn.execute(
        "SELECT id, name, email, phone, profile_pic, salt, password_hash FROM users WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()
    if not row:
        return None
    user_id, name, user_email, phone, profile_pic, salt, stored_hash = row
    _, check_hash = hash_password(password, salt)
    if check_hash == stored_hash:
        return {"id": user_id, "name": name, "email": user_email, "phone": phone, "profile_pic": profile_pic}
    return None


def update_profile(user_id, email, phone, profile_pic_b64=None):
    """Customer-editable profile fields — used by the Settings tab.
    profile_pic_b64=None leaves the existing picture untouched."""
    conn = get_conn()
    try:
        if profile_pic_b64 is not None:
            conn.execute(
                "UPDATE users SET email = ?, phone = ?, profile_pic = ? WHERE id = ?",
                (email.strip().lower(), phone.strip(), profile_pic_b64, user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET email = ?, phone = ? WHERE id = ?",
                (email.strip().lower(), phone.strip(), user_id),
            )
        conn.commit()
        return True, "Profile updated."
    except sqlite3.IntegrityError:
        return False, "Another account already uses that email."


def get_booked_times(appt_date_iso, exclude_appt_id=None):
    """Every time slot already taken (by ANY customer) on a given date, so the
    booking/reschedule pickers can hide them entirely — no double-booking."""
    conn = get_conn()
    if exclude_appt_id is None:
        rows = conn.execute(
            "SELECT appt_time FROM appointments WHERE appt_date = ? AND status = 'Confirmed'",
            (appt_date_iso,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT appt_time FROM appointments WHERE appt_date = ? AND status = 'Confirmed' AND id != ?",
            (appt_date_iso, exclude_appt_id),
        ).fetchall()
    return {r[0] for r in rows}


def create_appointment(user_id, service_key, appt_date, appt_time, notes):
    """Returns (ok, message). Re-checks the slot at write time (not just what
    the picker showed) so two people submitting at nearly the same moment
    can't both land the same slot."""
    conn = get_conn()
    conflict = conn.execute(
        "SELECT id FROM appointments WHERE appt_date = ? AND appt_time = ? AND status = 'Confirmed'",
        (appt_date.isoformat(), appt_time),
    ).fetchone()
    if conflict:
        return False, "Sorry - that time slot was just booked by someone else. Please pick another."
    service = SERVICES[service_key]
    conn.execute(
        "INSERT INTO appointments (user_id, service, price, appt_date, appt_time, notes, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Confirmed', ?)",
        (user_id, service["label"], service["price"], appt_date.isoformat(), appt_time, notes.strip(), datetime.now().isoformat()),
    )
    conn.commit()
    user_row = conn.execute("SELECT name, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if user_row:
        notify_booking(user_row[0], user_row[1], service["label"], appt_date.isoformat(), appt_time)
    return True, "Appointment booked."


def get_appointments(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, service, price, appt_date, appt_time, notes, status FROM appointments "
        "WHERE user_id = ? ORDER BY appt_date ASC, appt_time ASC",
        (user_id,),
    ).fetchall()
    return rows


def cancel_appointment(appt_id, user_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT a.service, a.appt_date, a.appt_time, u.name, u.email "
        "FROM appointments a JOIN users u ON u.id = a.user_id "
        "WHERE a.id = ? AND a.user_id = ?",
        (appt_id, user_id),
    ).fetchone()
    conn.execute(
        "UPDATE appointments SET status = 'Cancelled' WHERE id = ? AND user_id = ?",
        (appt_id, user_id),
    )
    conn.commit()
    if row:
        service, appt_date, appt_time, name, email = row
        notify_cancel(name, email, service, appt_date, appt_time, by_owner=False)


def reschedule_appointment(appt_id, user_id, new_date, new_time):
    """Returns (ok, message)."""
    conn = get_conn()
    conflict = conn.execute(
        "SELECT id FROM appointments WHERE appt_date = ? AND appt_time = ? AND status = 'Confirmed' AND id != ?",
        (new_date.isoformat(), new_time, appt_id),
    ).fetchone()
    if conflict:
        return False, "Sorry - that time slot was just booked by someone else. Please pick another."
    old_row = conn.execute(
        "SELECT a.service, a.appt_date, a.appt_time, u.name, u.email "
        "FROM appointments a JOIN users u ON u.id = a.user_id "
        "WHERE a.id = ? AND a.user_id = ?",
        (appt_id, user_id),
    ).fetchone()
    conn.execute(
        "UPDATE appointments SET appt_date = ?, appt_time = ? WHERE id = ? AND user_id = ?",
        (new_date.isoformat(), new_time, appt_id, user_id),
    )
    conn.commit()
    if old_row:
        service, old_date, old_time, name, email = old_row
        notify_reschedule(name, email, service, old_date, old_time, new_date.isoformat(), new_time, by_owner=False)
    return True, "Appointment updated."


def admin_cancel_appointment(appt_id):
    """Owner-only cancel — not scoped to a single user_id, since the owner
    manages every customer's bookings."""
    conn = get_conn()
    row = conn.execute(
        "SELECT a.service, a.appt_date, a.appt_time, u.name, u.email "
        "FROM appointments a JOIN users u ON u.id = a.user_id WHERE a.id = ?",
        (appt_id,),
    ).fetchone()
    conn.execute(
        "UPDATE appointments SET status = 'Cancelled' WHERE id = ?",
        (appt_id,),
    )
    conn.commit()
    if row:
        service, appt_date, appt_time, name, email = row
        notify_cancel(name, email, service, appt_date, appt_time, by_owner=True)


def admin_reschedule_appointment(appt_id, new_date, new_time):
    """Owner-only reschedule — not scoped to a single user_id. Returns (ok, message)."""
    conn = get_conn()
    conflict = conn.execute(
        "SELECT id FROM appointments WHERE appt_date = ? AND appt_time = ? AND status = 'Confirmed' AND id != ?",
        (new_date.isoformat(), new_time, appt_id),
    ).fetchone()
    if conflict:
        return False, "That time slot is already taken by another appointment."
    old_row = conn.execute(
        "SELECT a.service, a.appt_date, a.appt_time, u.name, u.email "
        "FROM appointments a JOIN users u ON u.id = a.user_id WHERE a.id = ?",
        (appt_id,),
    ).fetchone()
    conn.execute(
        "UPDATE appointments SET appt_date = ?, appt_time = ? WHERE id = ?",
        (new_date.isoformat(), new_time, appt_id),
    )
    conn.commit()
    if old_row:
        service, old_date, old_time, name, email = old_row
        notify_reschedule(name, email, service, old_date, old_time, new_date.isoformat(), new_time, by_owner=True)
    return True, "Appointment updated."


def get_all_appointments():
    """Every appointment across every customer — used by the owner/admin schedule view."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT a.id, a.service, a.price, a.appt_date, a.appt_time, a.notes, a.status,
               u.name, u.phone, u.email
        FROM appointments a
        JOIN users u ON u.id = a.user_id
        ORDER BY a.appt_date ASC, a.appt_time ASC
        """
    ).fetchall()
    return rows


def save_style_note(user_id, note):
    """Stores one Style-AI recommendation for a customer, so the owner can
    see it later in the Customers tab."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO style_notes (user_id, note, created_at) VALUES (?, ?, ?)",
        (user_id, note.strip(), datetime.now().isoformat()),
    )
    conn.commit()


def get_style_notes(user_id):
    """All Style-AI recommendations ever given to this customer, newest
    first — used by the owner's Customers tab."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT note, created_at FROM style_notes WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return rows


def get_customer_stats():
    """One row per registered customer: full name, phone, how many
    (confirmed) haircuts they've had, and which cut types those were —
    used by the owner's Customer Data table."""
    conn = get_conn()
    users = conn.execute(
        "SELECT id, name, phone FROM users ORDER BY name COLLATE NOCASE ASC"
    ).fetchall()
    stats = []
    for user_id, name, phone in users:
        appts = conn.execute(
            "SELECT service, appt_date FROM appointments "
            "WHERE user_id = ? AND status = 'Confirmed' "
            "ORDER BY appt_date DESC, appt_time DESC",
            (user_id,),
        ).fetchall()
        total_cuts = len(appts)
        if appts:
            # Unique cut types, most recent first.
            seen = []
            for service, _ in appts:
                if service not in seen:
                    seen.append(service)
            cut_types = ", ".join(seen)
            last_cut = appts[0][0]
        else:
            cut_types = "-"
            last_cut = "-"
        stats.append(
            {
                "Full Name": name,
                "Phone": phone or "-",
                "Total Cuts": total_cuts,
                "Cut Type(s)": cut_types,
                "Last Cut": last_cut,
            }
        )
    return stats


init_db()

# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9()\-\+\s\.]{7,20}$")


# ----------------------------------------------------------------------------
# GEMINI STYLE AI — customer takes a photo, Gemini recommends a haircut/fade.
# Uses plain urllib (no extra dependency) against the REST generateContent
# endpoint. Set the GEMINI_API_KEY environment variable (or add it to
# st.secrets) to enable this — the Style tab shows a clear message if it's
# missing instead of crashing.
#
# NOTE: some Google accounts are currently hitting a known, Google-side bug
# where newly-issued "AQ."-prefix keys get rejected here with a 401 "Expected
# OAuth 2 access token" error even though the key is valid. Vertex AI is NOT
# a working substitute for this — it requires full OAuth2/service-account
# credentials, not a bare API key. If you hit this, try restricting the key
# to "Gemini API only" in AI Studio, or generate a new key in a fresh project.
# ----------------------------------------------------------------------------
GEMINI_MODEL = "gemini-3.6-flash"


def get_gemini_api_key():
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            key = ""
    return key


def analyze_style_photo(image_bytes, mime_type="image/jpeg"):
    """Sends the customer's photo to Gemini and asks for a haircut/fade
    recommendation. Returns (ok, text_or_error_message)."""
    import json
    import urllib.request
    import urllib.error

    api_key = get_gemini_api_key()
    if not api_key:
        return False, "Style AI isn't set up yet - ask the shop owner to add a GEMINI_API_KEY."

    b64_img = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "You are an expert barber giving a quick in-person consultation. Look at this "
        "person's face shape, hair texture, and current hair length/style in the photo, "
        "then recommend a specific haircut. Cover: 1) the best fade type (e.g. low fade, "
        "mid fade, high fade, taper) and roughly where it should start, 2) whether they "
        "should keep the top short or long and about how many inches or clipper guard "
        "length, 3) any quick styling or beard-pairing notes. Write it as one short, "
        "friendly paragraph a barber would say in the chair — no headers, no markdown, "
        "no bullet points."
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": b64_img}},
                    {"text": prompt},
                ]
            }
        ]
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return True, text.strip()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        hint = ""
        if e.code == 401:
            hint = (
                " If your key starts with 'AQ.', try restricting it to 'Gemini API only' "
                "in AI Studio, or generate a new key in a fresh project - this is a known "
                "issue on some Google accounts."
            )
        elif e.code == 404:
            hint = (
                f" The model '{GEMINI_MODEL}' may have been retired - check "
                "ai.google.dev/gemini-api/docs/models for the current model name and "
                "update GEMINI_MODEL in app.py."
            )
        return False, f"Gemini API error ({e.code}). {detail[:300]}{hint}"
    except Exception as e:
        return False, f"Couldn't reach the Style AI right now ({e})."


def generate_time_slots():
    slots = []
    t = datetime.strptime("9:00 AM", "%I:%M %p")
    end = datetime.strptime("6:00 PM", "%I:%M %p")
    while t <= end:
        slots.append(t.strftime("%I:%M %p").lstrip("0"))
        t += timedelta(minutes=30)
    return slots


TIME_SLOTS = generate_time_slots()

# ----------------------------------------------------------------------------
# OWNER / ADMIN LOGIN
# ----------------------------------------------------------------------------
# Logging in with these credentials (instead of a normal customer account)
# unlocks the extra "Your Appointments" tab — a calendar of every booking from
# every customer. Change these before deploying, ideally by setting the
# BARBER_ADMIN_EMAIL / BARBER_ADMIN_PASSWORD environment variables.
ADMIN_EMAIL = os.environ.get("BARBER_ADMIN_EMAIL", "owner@fadedforless.com")
ADMIN_PASSWORD = os.environ.get("BARBER_ADMIN_PASSWORD", "FadedOwner2026!")

# ----------------------------------------------------------------------------
# EMAIL NOTIFICATIONS
# ----------------------------------------------------------------------------
# Sends real emails through Gmail's SMTP server using an "App Password" (not
# your normal Gmail password — Google blocks plain-password SMTP logins).
# The two addresses are fixed per your instructions: faded.for.less@gmail.com
# SENDS every email, freddiesawiras2@gmail.com is the owner inbox that gets
# the "your customer did X" alerts. The only thing still missing is the App
# Password, which has to be set as an environment variable (or in
# .streamlit/secrets.toml) since it's a secret and shouldn't live in code:
#   GMAIL_APP_PASSWORD   the 16-character App Password for faded.for.less@gmail.com
def _get_secret(key, default=""):
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


GMAIL_ADDRESS = "faded.for.less@gmail.com"
GMAIL_APP_PASSWORD = _get_secret("GMAIL_APP_PASSWORD")
OWNER_EMAIL = "freddiesawiras2@gmail.com"


def email_is_configured():
    return bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)


def send_email(to_email, subject, html_body):
    """Sends one HTML email (with the FADEDFORLESS crest logo embedded at
    the top) via Gmail SMTP. Fails silently (just prints to the server log)
    instead of raising — a booking or signup should never be blocked just
    because an email didn't go out."""
    if not email_is_configured() or not to_email:
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"FADEDFORLESS <{GMAIL_ADDRESS}>"
        msg["To"] = to_email
        msg.set_content("This email requires an HTML-capable email client to view.")
        msg.add_alternative(html_body, subtype="html")
        # Embed the logo as an inline image (cid) rather than a hosted URL —
        # works the same whether the site is deployed or running locally,
        # and won't break if the site's own image URLs ever change. The
        # crest logo has a transparent background, so it sits directly on
        # the black header with no white box around it.
        if os.path.exists(EMAIL_LOGO_PATH):
            with open(EMAIL_LOGO_PATH, "rb") as f:
                logo_bytes = f.read()
            msg.get_payload()[1].add_related(logo_bytes, maintype="image", subtype="png", cid="<logo>")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[email] Failed to send to {to_email}: {e}")
        return False


def email_wrapper(inner_html):
    """Wraps any email's body content in the shared FADEDFORLESS look: solid
    black background top to bottom, gold hairline accents, the crest logo
    front and center."""
    return f"""
    <div style="background:#000000; padding:40px 16px;">
        <div style="max-width:480px; margin:0 auto; background:#0d0d0d; border:1px solid #D4AF37; border-radius:14px; overflow:hidden; font-family:Arial, Helvetica, sans-serif; box-shadow:0 0 0 1px rgba(212,175,55,0.15);">
            <div style="background:#000000; padding:32px 24px 24px 24px; text-align:center;">
                <img src="cid:logo" alt="FADEDFORLESS" style="height:140px; width:auto;" />
            </div>
            <div style="height:2px; background:linear-gradient(90deg, transparent, #D4AF37, transparent);"></div>
            <div style="padding:30px 26px; color:#EDEAE2; font-size:15px; line-height:1.7;">
                {inner_html}
            </div>
            <div style="height:1px; background:rgba(212,175,55,0.25);"></div>
            <div style="padding:18px 24px; text-align:center; color:#D4AF37; font-size:12px; letter-spacing:1px; text-transform:uppercase;">
                FADEDFORLESS &middot; Premium cuts. Fair prices.
            </div>
        </div>
    </div>
    """


def pretty_appt(service, appt_date_iso, appt_time):
    """'Full Haircut on Mon, Aug 10 at 2:00 PM' — used in every email body."""
    d = datetime.strptime(appt_date_iso, "%Y-%m-%d").strftime("%a, %b %d, %Y")
    return f"{service} on {d} at {appt_time}"


def notify_signup(name, email):
    send_email(
        email,
        "Welcome to FADEDFORLESS",
        email_wrapper(
            f"<p>Hey {name},</p>"
            "<p>Your account is set up. You can now book appointments, reschedule, "
            "and get style recommendations any time.</p>"
            "<p>- FADEDFORLESS</p>"
        ),
    )
    send_email(
        OWNER_EMAIL,
        "New account created",
        email_wrapper(f"<p>{name} ({email}) just created an account.</p>"),
    )


def notify_booking(name, email, service, appt_date_iso, appt_time):
    details = pretty_appt(service, appt_date_iso, appt_time)
    send_email(
        email,
        "Appointment Confirmed - FADEDFORLESS",
        email_wrapper(
            f"<p>Hey {name},</p>"
            f"<p>You're booked for:<br><strong>{details}</strong></p>"
            "<p>We'll send you a reminder 1 hour before. See you then.</p>"
            "<p>- FADEDFORLESS</p>"
        ),
    )
    send_email(
        OWNER_EMAIL,
        "New booking",
        email_wrapper(f"<p>{name} booked an appointment.</p><p><strong>{details}</strong></p>"),
    )


def notify_cancel(name, email, service, appt_date_iso, appt_time, by_owner=False):
    details = pretty_appt(service, appt_date_iso, appt_time)
    send_email(
        email,
        "Appointment Cancelled - FADEDFORLESS",
        email_wrapper(
            f"<p>Hey {name},</p>"
            f"<p>This appointment has been cancelled:<br><strong>{details}</strong></p>"
            "<p>Head back to the site any time to book a new one.</p>"
            "<p>- FADEDFORLESS</p>"
        ),
    )
    who = "The owner" if by_owner else name
    send_email(
        OWNER_EMAIL,
        "Appointment cancelled",
        email_wrapper(f"<p>{who} cancelled {name}'s appointment.</p><p><strong>{details}</strong></p>"),
    )


def notify_reschedule(name, email, service, old_date_iso, old_time, new_date_iso, new_time, by_owner=False):
    old_details = pretty_appt(service, old_date_iso, old_time)
    new_details = pretty_appt(service, new_date_iso, new_time)
    send_email(
        email,
        "Appointment Updated - FADEDFORLESS",
        email_wrapper(
            f"<p>Hey {name},</p>"
            "<p>Your appointment was moved.</p>"
            f"<p>Old time: {old_details}<br>New time: <strong>{new_details}</strong></p>"
            "<p>- FADEDFORLESS</p>"
        ),
    )
    who = "The owner" if by_owner else name
    send_email(
        OWNER_EMAIL,
        "Appointment rescheduled",
        email_wrapper(
            f"<p>{who} rescheduled {name}'s appointment.</p>"
            f"<p>Old time: {old_details}<br>New time: <strong>{new_details}</strong></p>"
        ),
    )


# ----------------------------------------------------------------------------
# ROUTING (query params drive the "pages")
# ----------------------------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None

BASE_PAGES = ["Home", "About Me", "Pricing", "Book Now", "Instagram"]
IS_ADMIN = bool(st.session_state.user and st.session_state.user.get("is_admin"))
IS_CUSTOMER = bool(st.session_state.user and not IS_ADMIN)
VALID_PAGES = (
    BASE_PAGES
    + (["Your Appointments", "Customers", "Settings"] if IS_ADMIN else [])
    + (["Style", "Settings"] if IS_CUSTOMER else [])
)

qp = st.query_params
current_page = qp.get("page", "Home")
if current_page not in VALID_PAGES:
    current_page = "Home"

# ----------------------------------------------------------------------------
# GLOBAL CSS
# ----------------------------------------------------------------------------
raw_html(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;600;700;800&family=Inter:wght@300;400;500;600;700&display=swap');

    :root{
        --gold:#D4AF37;
        --gold-light:#F1D98B;
        --gold-soft:rgba(212,175,55,0.15);
        --black:#070707;
        --charcoal:#121212;
        --charcoal-2:#181818;
        --charcoal-3:#1f1f1f;
        --text-muted:#b8b3a8;
        --premium-black:#0a0a0a;
    }

    /* ---------- HIDE STREAMLIT CHROME ---------- */
    #MainMenu {visibility:hidden;}
    footer {visibility:hidden;}
    header[data-testid="stHeader"]{
        background:transparent;
        height:0;
        pointer-events:none;
    }
    div[data-testid="stToolbar"]{display:none;}
    div[data-testid="stDecoration"]{display:none;}
    div[data-testid="stStatusWidget"]{display:none;}
    #stDecoration{display:none;}
    .stDeployButton{display:none;}

    /* ---------- BASE ---------- */
    html, body, [class*="css"]{
        font-family:'Inter', sans-serif;
    }
    .stApp{
        background:
            radial-gradient(circle at 15% 0%, rgba(212,175,55,0.06), transparent 40%),
            radial-gradient(circle at 85% 20%, rgba(212,175,55,0.05), transparent 35%),
            var(--black);
        color:#EDEAE2;
    }
    .block-container{
        padding-top:0rem;
        padding-bottom:2rem;
        max-width:100%;
    }
    h1,h2,h3,h4{
        font-family:'Playfair Display', serif;
        color:#F5F1E6;
        letter-spacing:0.5px;
    }
    p, span, li, label{
        font-family:'Inter', sans-serif;
        color:var(--text-muted);
        line-height:1.7;
    }
    a{ text-decoration:none; }
    hr{ border-color: rgba(212,175,55,0.2); }

    .gold{ color:var(--gold); }
    .gold-grad{
        background: linear-gradient(120deg, var(--gold-light), var(--gold) 55%, #a67c1f);
        -webkit-background-clip:text;
        background-clip:text;
        color:transparent;
    }

    /* ---------- NAVBAR ---------- */
    /* Real Streamlit container (from st.container(key="site_navbar")) —
       gets the sticky/blur header treatment that used to live on a plain div. */
    .st-key-site_navbar{
        position:sticky;
        top:0;
        z-index:999;
        background:rgba(7,7,7,0.92);
        backdrop-filter:blur(10px);
        -webkit-backdrop-filter:blur(10px);
        border-bottom:1px solid rgba(212,175,55,0.25);
        padding:14px 32px;
    }
    .st-key-site_navbar [data-testid="stHorizontalBlock"]{
        max-width:1200px;
        margin:0 auto;
        align-items:center;
    }
    .brand{
        font-family:'Playfair Display', serif;
        font-weight:800;
        font-size:1.4rem;
        letter-spacing:2px;
        color:#F5F1E6;
        white-space:nowrap;
    }
    .brand span{ color:var(--gold); }
    .nav-account{
        font-size:0.8rem;
        color:var(--gold-light);
        border:1px solid rgba(212,175,55,0.4);
        padding:6px 14px;
        border-radius:20px;
        white-space:nowrap;
        text-align:center;
    }
    /* Nav buttons: real st.button widgets, restyled to look like text links
       instead of the site-wide gold pill CTA. Bigger min-height/padding than
       before gives them a comfortably large, reliable click/tap target. */
    .st-key-site_navbar .stButton{ margin:0; }
    .st-key-site_navbar .stButton > button{
        background:transparent !important;
        box-shadow:none !important;
        border:none !important;
        color:#FFFFFF !important;
        font-size:0.82rem !important;
        font-weight:600 !important;
        letter-spacing:1px !important;
        text-transform:uppercase;
        min-height:46px;
        padding:10px 12px !important;
        border-radius:6px !important;
        border-bottom:2px solid transparent !important;
        cursor:pointer;
        -webkit-tap-highlight-color:transparent;
        touch-action:manipulation;
        transition:color 0.2s ease, background 0.2s ease, border-color 0.2s ease;
    }
    .st-key-site_navbar .stButton > button:hover{
        color:var(--gold) !important;
        background:rgba(212,175,55,0.08) !important;
        transform:none;
        box-shadow:none !important;
    }
    .st-key-site_navbar .stButton > button[kind="primary"]{
        color:var(--gold) !important;
        border-bottom:2px solid var(--gold) !important;
    }
    /* Nav buttons are transparent, not gold-filled, so their labels stay
       white/gold — not the premium-black used on solid gold CTA buttons. */
    .st-key-site_navbar .stButton > button p, .st-key-site_navbar .stButton > button span, .st-key-site_navbar .stButton > button div{
        color:inherit !important;
    }


    /* ---------- BUTTONS (HTML links styled as buttons) ---------- */
    .btn{
        display:inline-block;
        padding:14px 34px;
        font-size:0.85rem;
        font-weight:700;
        letter-spacing:1.5px;
        text-transform:uppercase;
        border-radius:2px;
        transition:all 0.3s ease;
        cursor:pointer;
        border:1px solid transparent;
    }
    .btn-primary{
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:#0a0a0a !important;
        box-shadow:0 8px 24px rgba(212,175,55,0.25);
    }
    .btn-primary:hover{
        transform:translateY(-2px);
        box-shadow:0 12px 30px rgba(212,175,55,0.4);
        filter:brightness(1.05);
    }
    .btn-outline{
        background:transparent;
        color:var(--gold-light) !important;
        border:1px solid rgba(212,175,55,0.6);
    }
    .btn-outline:hover{
        background:rgba(212,175,55,0.1);
        border-color:var(--gold);
        transform:translateY(-2px);
    }

    /* ---------- STREAMLIT WIDGETS (forms, inputs, buttons) ---------- */
    .stTextInput input, .stTextArea textarea, .stDateInput input, .stNumberInput input{
        background:var(--charcoal-2) !important;
        color:#EDEAE2 !important;
        border:1px solid rgba(212,175,55,0.3) !important;
        border-radius:6px !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus, .stDateInput input:focus{
        border-color:var(--gold) !important;
        box-shadow:0 0 0 1px rgba(212,175,55,0.4) !important;
    }
    div[data-baseweb="select"] > div{
        background:var(--charcoal-2) !important;
        border:1px solid rgba(212,175,55,0.3) !important;
        color:#EDEAE2 !important;
        border-radius:6px !important;
    }
    div[data-baseweb="popover"] li{
        background:var(--charcoal-2) !important;
        color:#EDEAE2 !important;
    }
    .stForm{
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.2);
        border-radius:12px;
        padding:34px 34px 20px 34px;
    }
    /* Streamlit auto-adds a "Press Enter to submit form" hint under every
       text input inside a st.form (login_form, signup_form). It's not our
       text, so there's nothing to edit in Python — just hide the element
       Streamlit renders it in. */
    [data-testid="InputInstructions"]{
        display:none !important;
    }
    .stButton>button, .stFormSubmitButton>button{
        background:linear-gradient(120deg, var(--gold-light), var(--gold)) !important;
        color:#0a0a0a !important;
        border:none !important;
        font-weight:700 !important;
        letter-spacing:1px !important;
        text-transform:uppercase;
        font-size:0.82rem !important;
        border-radius:4px !important;
        padding:10px 22px !important;
        transition:all 0.25s ease !important;
    }
    .stButton>button:hover, .stFormSubmitButton>button:hover{
        transform:translateY(-2px);
        box-shadow:0 10px 24px rgba(212,175,55,0.35);
    }
    /* The line above only colors the <button> element itself, but Streamlit
       renders the visible label inside a nested <p> — and the earlier
       "p, span, li, label{ color:var(--text-muted) }" rule wins over an
       inherited color no matter how the parent was styled, !important or
       not, because a direct rule on the child always beats inheritance.
       Target the label text directly so every gold button (Book Now, Book
       Full Haircut, Book Fade or Trim, etc.) actually shows premium black. */
    .stButton>button p, .stButton>button span, .stButton>button div,
    .stFormSubmitButton>button p, .stFormSubmitButton>button span, .stFormSubmitButton>button div{
        color:var(--premium-black) !important;
    }
    .stTabs [data-baseweb="tab-list"]{
        gap:6px;
        border-bottom:1px solid rgba(212,175,55,0.2);
    }
    .stTabs [data-baseweb="tab"]{
        color:var(--text-muted);
        font-weight:600;
        letter-spacing:0.5px;
        text-transform:uppercase;
        font-size:0.85rem;
    }
    .stTabs [aria-selected="true"]{
        color:var(--gold) !important;
        border-bottom-color:var(--gold) !important;
    }
    .stAlert{
        border-radius:8px;
    }
    label, .stMarkdown p{ color:#D9D4C7; }

    /* ---------- HERO ---------- */
    .hero{
        position:relative;
        min-height:88vh;
        display:flex;
        align-items:center;
        overflow:hidden;
        border-bottom:1px solid rgba(212,175,55,0.2);
    }
    .hero-bg{
        position:absolute;
        inset:0;
        background-image:linear-gradient(100deg, rgba(7,7,7,0.96) 30%, rgba(7,7,7,0.55) 65%, rgba(7,7,7,0.25) 100%), url('__IMG_HERO__');
        background-size:cover;
        background-position:center 30%;
    }
    .hero-content{
        position:relative;
        z-index:2;
        max-width:1200px;
        margin:0 auto;
        padding:0 32px;
        width:100%;
    }
    .eyebrow{
        letter-spacing:4px;
        text-transform:uppercase;
        color:var(--gold);
        font-size:0.78rem;
        font-weight:700;
        margin-bottom:18px;
        display:flex;
        align-items:center;
        gap:12px;
    }
    .eyebrow::before{
        content:"";
        width:36px;
        height:1px;
        background:var(--gold);
        display:inline-block;
    }
    .hero-title{
        font-size:5rem;
        line-height:1.02;
        font-weight:800;
        margin:0 0 20px 0;
        max-width:800px;
    }
    .hero-tagline{
        font-size:1.35rem;
        color:#E8E3D6;
        font-weight:500;
        max-width:620px;
        margin-bottom:14px;
        font-family:'Playfair Display', serif;
        font-style:italic;
    }
    .hero-desc{
        font-size:1.02rem;
        max-width:560px;
        margin-bottom:10px;
    }

    /* Hero CTA buttons are real Streamlit buttons rendered just below the
       hero block; pull them up visually so they sit where the old inline
       .hero-btns row used to be. */
    .st-key-hero_cta{
        position:relative;
        z-index:5;
        max-width:1200px;
        margin:-64px auto 30px auto;
        padding:0 32px;
    }
    .st-key-hero_cta .stButton > button{ min-width:170px; }
    .st-key-hero_cta .stButton > button[kind="secondary"]{
        background:transparent !important;
        color:var(--gold-light) !important;
        border:1px solid rgba(212,175,55,0.6) !important;
        box-shadow:none !important;
    }
    .st-key-hero_cta .stButton > button[kind="secondary"] p, .st-key-hero_cta .stButton > button[kind="secondary"] span, .st-key-hero_cta .stButton > button[kind="secondary"] div{
        color:inherit !important;
    }
    .st-key-hero_cta .stButton > button[kind="secondary"]:hover{
        background:rgba(212,175,55,0.1) !important;
        border-color:var(--gold) !important;
    }

    /* ---------- SECTION SHELL ---------- */
    .section{
        max-width:1200px;
        margin:0 auto;
        padding:100px 32px;
    }
    .section-tight{ padding:70px 32px; }
    .section-head{ margin-bottom:56px; }
    .section-head .eyebrow{ justify-content:flex-start; }
    .section-title{ font-size:2.6rem; margin-bottom:14px; }
    .section-sub{ max-width:600px; font-size:1.05rem; }
    .divider{
        width:70px;
        height:2px;
        background:linear-gradient(90deg, var(--gold), transparent);
        margin:20px 0 0 0;
    }

    /* ---------- ABOUT ---------- */
    .about-wrap{
        display:grid;
        grid-template-columns:1.05fr 1fr;
        gap:70px;
        align-items:center;
    }
    .about-img-frame{
        position:relative;
        border:1px solid rgba(212,175,55,0.35);
        padding:14px;
        border-radius:4px;
    }
    .about-img-frame img{
        width:100%;
        display:block;
        border-radius:2px;
        filter:grayscale(15%) contrast(1.05);
    }
    .about-quote{
        font-family:'Playfair Display', serif;
        font-style:italic;
        font-size:1.28rem;
        color:#F1EADB;
        line-height:1.65;
        border-left:2px solid var(--gold);
        padding-left:26px;
        margin:26px 0 30px 0;
    }
    .pillars{
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:16px;
        margin-top:10px;
    }
    .pillar{
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.15);
        border-radius:6px;
        padding:16px 18px;
        font-size:0.92rem;
        color:#E9E4D6;
        font-weight:500;
        transition:border-color 0.25s ease, transform 0.25s ease;
    }
    .pillar:hover{
        border-color:rgba(212,175,55,0.55);
        transform:translateY(-3px);
    }
    .pillar b{ color:var(--gold); }

    /* ---------- PRICING ---------- */
    .price-grid{
        display:grid;
        grid-template-columns:1fr 1.12fr;
        gap:34px;
        align-items:stretch;
    }
    .price-card{
        background:linear-gradient(180deg, var(--charcoal-2), var(--charcoal));
        border:1px solid rgba(212,175,55,0.22);
        border-radius:10px;
        overflow:hidden;
        display:flex;
        flex-direction:column;
        transition:transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
        position:relative;
    }
    .price-card:hover{
        transform:translateY(-6px);
        box-shadow:0 22px 45px rgba(0,0,0,0.45);
        border-color:rgba(212,175,55,0.55);
    }
    .price-card.featured{
        border:1px solid rgba(212,175,55,0.75);
        box-shadow:0 0 0 1px rgba(212,175,55,0.15), 0 25px 60px rgba(212,175,55,0.12);
    }
    .price-card-img{
        height:230px;
        background-size:cover;
        background-position:center;
        position:relative;
    }
    .price-card-img::after{
        content:"";
        position:absolute; inset:0;
        background:linear-gradient(180deg, rgba(7,7,7,0.05), var(--charcoal-2) 96%);
    }
    .badge{
        position:absolute;
        top:18px; right:18px;
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:#0a0a0a;
        font-size:0.68rem;
        font-weight:800;
        letter-spacing:1.5px;
        text-transform:uppercase;
        padding:7px 14px;
        border-radius:20px;
        z-index:2;
        box-shadow:0 6px 16px rgba(0,0,0,0.35);
    }
    .price-card-body{
        padding:32px 30px 34px 30px;
        flex:1;
        display:flex;
        flex-direction:column;
    }
    .price-name{
        text-transform:uppercase;
        letter-spacing:2px;
        font-size:0.82rem;
        color:var(--gold);
        font-weight:700;
        margin-bottom:10px;
    }
    .price-amount{
        font-family:'Playfair Display', serif;
        font-size:3.2rem;
        font-weight:700;
        color:#F7F3E7;
        margin-bottom:4px;
        line-height:1;
    }
    .price-meta{
        display:flex;
        gap:14px;
        margin:14px 0 20px 0;
        flex-wrap:wrap;
    }
    .chip{
        border:1px solid rgba(212,175,55,0.35);
        color:#E9E4D6;
        font-size:0.78rem;
        font-weight:600;
        letter-spacing:0.5px;
        padding:6px 14px;
        border-radius:20px;
        background:rgba(212,175,55,0.06);
    }
    .price-desc{ font-size:0.98rem; margin-bottom:22px; color:#E9E4D6; }
    .price-line{
        margin-top:auto;
        padding-top:18px;
        border-top:1px solid rgba(212,175,55,0.15);
    }

    /* ---------- GOLD TAG ----------
       Solid gold-gradient chip used for any short note/label sitting inside
       a gold-bordered box. Text is always premium black for max contrast —
       the same treatment already used on .badge and the primary buttons. */
    .gold-tag{
        display:inline-block;
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:var(--premium-black) !important;
        font-weight:600;
        font-style:normal;
        font-size:0.82rem;
        letter-spacing:0.3px;
        padding:6px 13px;
        border-radius:6px;
    }

    .st-key-pricing_cta{
        max-width:700px;
        margin:10px auto 60px auto;
        padding:0 32px;
    }

    /* "Press this card to book it" buttons — real Streamlit buttons placed
       directly under each price card, restyled to read as part of the card
       instead of a generic Streamlit button. Using a real button (not a raw
       <a href>) keeps the logged-in session intact on click. */
    .st-key-price_link_10 .stButton>button, .st-key-price_link_15 .stButton>button{
        width:100%;
        margin-top:-14px;
        border-radius:0 0 10px 10px !important;
    }

    .strip{
        display:grid;
        grid-template-columns:repeat(3, 1fr);
        gap:20px;
    }
    .strip img{
        width:100%;
        height:230px;
        object-fit:cover;
        border-radius:6px;
        border:1px solid rgba(212,175,55,0.18);
        filter:grayscale(20%) contrast(1.05);
        transition:filter 0.3s ease, transform 0.3s ease;
    }
    .strip img:hover{
        filter:grayscale(0%) contrast(1.1);
        transform:scale(1.02);
    }

    /* ---------- STYLE SHOWCASE (Home page "The Craft") ---------- */
    .style-grid{
        display:grid;
        grid-template-columns:repeat(3, 1fr);
        gap:20px;
    }
    .style-card{
        position:relative;
        border-radius:8px;
        overflow:hidden;
        border:1px solid rgba(212,175,55,0.22);
        transition:transform 0.3s ease, border-color 0.3s ease;
    }
    .style-card:hover{
        transform:translateY(-4px);
        border-color:rgba(212,175,55,0.6);
    }
    .style-card img{
        width:100%;
        height:280px;
        object-fit:cover;
        display:block;
        filter:grayscale(10%) contrast(1.05);
        transition:filter 0.3s ease, transform 0.4s ease;
    }
    .style-card:hover img{
        filter:grayscale(0%) contrast(1.1);
        transform:scale(1.05);
    }
    .style-label{
        position:absolute;
        left:0; right:0; bottom:0;
        padding:16px 18px;
        background:linear-gradient(0deg, rgba(7,7,7,0.95) 20%, transparent 100%);
    }
    .style-label .name{
        font-family:'Playfair Display', serif;
        font-size:1.15rem;
        font-weight:700;
        color:#F5F1E6;
    }
    .style-label .tag{
        display:block;
        margin-top:4px;
        font-size:0.72rem;
        letter-spacing:1.5px;
        text-transform:uppercase;
        color:var(--gold-light);
        font-weight:700;
    }

    /* ---------- INSTAGRAM ---------- */
    .insta-panel{
        text-align:center;
        max-width:720px;
        margin:0 auto;
        padding:80px 40px;
        background:
            radial-gradient(circle at 50% 0%, rgba(212,175,55,0.08), transparent 60%),
            var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.25);
        border-radius:14px;
    }
    .insta-icon{
        width:70px; height:70px;
        margin:0 auto 26px auto;
        border-radius:18px;
        background:linear-gradient(45deg,#f9ce34,#ee2a7b,#6228d7);
        display:flex; align-items:center; justify-content:center;
        font-size:1.8rem;
        box-shadow:0 10px 26px rgba(0,0,0,0.4);
    }
    .insta-handle{
        font-family:'Playfair Display', serif;
        font-size:2.2rem;
        color:#F5F1E6;
        margin-bottom:10px;
    }
    .insta-sub{ margin-bottom:34px; color:#E9E4D6; }
    .btn-insta{
        display:inline-block;
        padding:16px 42px;
        font-size:0.9rem;
        font-weight:800;
        letter-spacing:2px;
        text-transform:uppercase;
        border-radius:3px;
        color:#0a0a0a !important;
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        box-shadow:0 10px 28px rgba(212,175,55,0.3);
        transition:all 0.3s ease;
    }
    .btn-insta:hover{
        transform:translateY(-3px);
        box-shadow:0 16px 36px rgba(212,175,55,0.45);
    }

    /* ---------- BOOKING ---------- */
    .booking-head{ text-align:center; margin-bottom:44px; }
    .appt-card{
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.22);
        border-radius:10px;
        padding:20px 24px;
        margin-bottom:14px;
        display:flex;
        justify-content:space-between;
        align-items:center;
        flex-wrap:wrap;
        gap:12px;
    }
    .appt-service{ color:#F5F1E6; font-weight:700; font-size:1.02rem; }
    .appt-meta{ margin-top:6px; }
    .status-pill{
        padding:5px 14px;
        border-radius:20px;
        font-size:0.72rem;
        font-weight:800;
        letter-spacing:1px;
        text-transform:uppercase;
    }
    .status-Confirmed{ background:rgba(212,175,55,0.15); color:var(--gold-light); border:1px solid rgba(212,175,55,0.4); }
    .status-Cancelled{ background:rgba(200,60,60,0.12); color:#e28080; border:1px solid rgba(200,60,60,0.35); }

    /* ---------- ADMIN SCHEDULE / CALENDAR ---------- */
    .cal-grid{
        display:grid;
        grid-template-columns:repeat(7, 1fr);
        gap:6px;
        margin:20px 0 10px 0;
    }
    .cal-dow{
        text-align:center;
        font-size:0.72rem;
        letter-spacing:1px;
        text-transform:uppercase;
        color:var(--gold);
        font-weight:700;
        padding-bottom:6px;
    }
    .cal-cell{
        min-height:76px;
        border:1px solid rgba(212,175,55,0.15);
        border-radius:8px;
        background:var(--charcoal-2);
        padding:8px;
        position:relative;
    }
    .cal-cell.empty{ background:transparent; border-color:transparent; }
    .cal-cell.today{ border-color:rgba(212,175,55,0.7); }
    .cal-daynum{ font-size:0.85rem; color:#EDEAE2; font-weight:600; }
    .cal-count{
        margin-top:8px;
        display:inline-block;
        background:rgba(212,175,55,0.18);
        color:var(--gold-light);
        font-size:0.7rem;
        font-weight:800;
        padding:2px 8px;
        border-radius:12px;
    }
    .admin-appt-row{
        display:flex;
        justify-content:space-between;
        align-items:center;
        flex-wrap:wrap;
        gap:8px;
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.18);
        border-radius:8px;
        padding:14px 18px;
        margin-bottom:10px;
    }
    .admin-appt-time{ color:var(--gold-light); font-weight:700; min-width:90px; }
    .admin-appt-cust{ color:#F5F1E6; font-weight:600; margin-bottom:6px; }
    .admin-appt-service{ margin-top:4px; }

    /* ---------- FOOTER ---------- */
    .footer{
        border-top:1px solid rgba(212,175,55,0.18);
        padding:40px 32px;
        text-align:center;
        color:#847f72;
        font-size:0.82rem;
        letter-spacing:1px;
    }
    .footer span{ color:var(--gold); }

    /* ---------- COLLAPSIBLE MOBILE NAV (phone mode) ---------- */
    /* When the hamburger menu is open, each page link is its own stacked
       st.button inside the navbar's vertical block — give it a little
       breathing room between links. */
    .st-key-site_navbar [data-testid="stVerticalBlock"]{ gap:6px; }

    /* ---------- RESPONSIVE ---------- */
    @media (max-width: 900px){
        .hero-title{ font-size:3rem; }
        .about-wrap{ grid-template-columns:1fr; gap:36px; }
        .price-grid{ grid-template-columns:1fr; }
        .strip{ grid-template-columns:1fr; }
        .st-key-site_navbar [data-testid="stHorizontalBlock"]{
            flex-wrap:wrap;
            justify-content:center;
        }
        /* Give each nav pill only the width its own label actually needs
           instead of an equal forced share — that's what was breaking
           "Instagram" into "Insta"/"gram" on two lines. Shorter labels
           (Home, About Me) shrink, longer ones (Instagram, Customers) get
           the room they need, and the row wraps as a whole if it runs out
           of space rather than breaking a single word apart. */
        .st-key-site_navbar [data-testid="stColumn"],
        .st-key-site_navbar [data-testid="column"]{
            width:auto !important;
            flex:0 1 auto !important;
            min-width:0 !important;
        }
        .st-key-site_navbar .stButton{ width:auto !important; }
        .st-key-site_navbar .stButton > button{
            font-size:0.7rem !important;
            padding:8px 12px !important;
            white-space:nowrap !important;
            width:auto !important;
        }
        .section{ padding:60px 20px; }
        .pillars{ grid-template-columns:1fr; }
    }
    </style>
    """.replace("__IMG_HERO__", IMG_HERO)
)

# ----------------------------------------------------------------------------
# NAVBAR
# ----------------------------------------------------------------------------
# IMPORTANT: navigation used to be plain <a href="?page=..."> links. Clicking
# one made the browser do a real full-page navigation/reload, which throws
# away the in-memory Streamlit session (that's what was logging people out on
# every click). A second attempt routed clicks through onclick="" JavaScript —
# but Streamlit's HTML sanitizer strips onclick attributes and javascript:
# links from st.markdown content for security, so those clicks silently did
# nothing. The reliable fix: the nav is built from *real* Streamlit buttons
# (st.button), just styled with CSS to look like the original pill nav links.
# Real widgets always trigger a proper in-session rerun — no reload, no
# stripped attributes, no cross-frame hacks.
def go_to(page_name):
    st.query_params["page"] = page_name


def go_to_service(page_name, service_key):
    """Used by the clickable pricing cards — jumps to Book Now and
    pre-selects the exact service that was pressed."""
    st.session_state.preselect_service = service_key
    st.query_params["page"] = page_name


with st.container(key="site_navbar"):
    n_pages = len(VALID_PAGES)
    col_ratios = [1.6] + [1] * n_pages + [1.3 if st.session_state.user else 0.001]
    cols = st.columns(col_ratios, vertical_alignment="center")

    with cols[0]:
        raw_html(logo_html(42))

    for i, page_name in enumerate(VALID_PAGES):
        with cols[i + 1]:
            is_active = current_page == page_name
            st.button(
                "Your Appts" if page_name == "Your Appointments" else page_name,
                key=f"navbtn_{page_name}",
                on_click=go_to,
                args=(page_name,),
                type="primary" if is_active else "secondary",
                use_container_width=True,
            )

    if st.session_state.user:
        with cols[-1]:
            first_name = st.session_state.user["name"].split(" ")[0]
            raw_html(f'<div class="nav-account">Hi, {first_name}</div>')

# ----------------------------------------------------------------------------
# HOME PAGE
# ----------------------------------------------------------------------------
def render_home():
    raw_html(
        f"""
        <div class="hero">
            <div class="hero-bg"></div>
            <div class="hero-content">
                <div class="eyebrow">Modern Barbering</div>
                <h1 class="hero-title">FADED<span class="gold-grad">FOR</span>LESS</h1>
                <div class="hero-tagline">Premium cuts. Fair prices. No unnecessary markup.</div>
                <p class="hero-desc">
                    The goal is simple - quality barbering at a price that actually makes sense.
                    Every client gets a clean, precise cut and a professional experience,
                    without paying for the markup that comes with it.
                </p>
            </div>
        </div>
        """
    )
    with st.container(key="hero_cta"):
        c1, c2, _sp = st.columns([1, 1, 3])
        with c1:
            st.button("Book Now", key="hero_book_now", type="primary", on_click=go_to, args=("Book Now",))
        with c2:
            st.button("View Pricing", key="hero_view_pricing", on_click=go_to, args=("Pricing",))

    style_cards = "".join(
        f"""
        <div class="style-card">
            <img src="{s['img']}" />
            <div class="style-label">
                <span class="tag">{s['tag']}</span>
                <span class="name">{s['name']}</span>
            </div>
        </div>
        """
        for s in STYLE_SHOWCASE
    )
    raw_html(
        f"""
        <div class="section section-tight">
            <div class="section-head">
                <div class="eyebrow">The Craft</div>
                <h2 class="section-title">Precision, every single time</h2>
                <div class="divider"></div>
                <p class="section-sub">Six cuts, one standard. See the difference between a mid fade, a low fade, a low taper, a sharp lineup, a clean beard, and an undercut - then book the one you want.</p>
            </div>
            <div class="style-grid">
                {style_cards}
            </div>
        </div>
        """
    )

    raw_html(
        f"""
        <div class="section section-tight" style="padding-top:0;">
            <div class="insta-panel">
                <div class="insta-icon">📷</div>
                <div class="insta-handle">@fadedforless</div>
                <p class="insta-sub">See the latest work, book your next cut, and follow along on Instagram.</p>
                <a class="btn-insta" href="{INSTAGRAM_URL}" target="_blank">Follow on Instagram</a>
            </div>
        </div>
        """
    )

# ----------------------------------------------------------------------------
# ABOUT PAGE
# ----------------------------------------------------------------------------
def render_about():
    raw_html(
        f"""
        <div class="section">
            <div class="section-head">
                <div class="eyebrow">About Me</div>
                <h2 class="section-title">Quality work, honest pricing</h2>
                <div class="divider"></div>
            </div>
            <div class="about-wrap">
                <div class="about-img-frame">
                    <img src="{IMG_ABOUT}" />
                </div>
                <div>
                    <div class="about-quote">
                        "I'm 17 years old with 4 years of hands-on experience behind the chair,
                        and I'm still sharpening my craft every single day. I believe getting a
                        clean haircut shouldn't have to be expensive, which is why I keep my
                        prices affordable while putting real effort into every cut."
                    </div>
                    <p>
                        Every client walks in for a fresh cut and walks out with a full, professional
                        experience - sharp lines, clean fades, and genuine attention to detail. No
                        rushed appointments, no inflated prices for a basic service.
                    </p>
                    <p>
                        Don't let my age fool you - I've been cutting hair for 4 years and I'm
                        always working to get better. If you're not sure yet, check out
                        <a href="{INSTAGRAM_URL}" target="_blank" class="gold">@fadedforless on Instagram</a>
                        and see the work for yourself.
                    </p>
                    <div class="pillars">
                        <div class="pillar"><b>17, Growing Fast</b><br/>4 years of real experience so far</div>
                        <div class="pillar"><b>Affordable</b><br/>Pricing that respects your wallet</div>
                        <div class="pillar"><b>Precise</b><br/>Clean lines and sharp fades</div>
                        <div class="pillar"><b>Premium Feel</b><br/>A pro experience, fair price</div>
                    </div>
                </div>
            </div>
        </div>
        """
    )

# ----------------------------------------------------------------------------
# PRICING PAGE
# ----------------------------------------------------------------------------
def render_pricing():
    raw_html(
        """
        <div class="section" style="padding-bottom:20px;">
            <div class="section-head">
                <div class="eyebrow">Pricing</div>
                <h2 class="section-title">Simple, honest pricing</h2>
                <div class="divider"></div>
                <p class="section-sub">Two straightforward options. No hidden add-ons, no inflated markup. Tap a service to book it.</p>
            </div>
        </div>
        """
    )

    with st.container(key="pricing_grid"):
        outer_l, outer_mid, outer_r = st.columns([1, 5.4, 1])
        with outer_mid:
            col_10, col_15 = st.columns([1, 1.12])

            with col_10:
                raw_html(
                    f"""
                    <div class="price-card">
                        <div class="price-card-img" style="background-image:url('{IMG_PRICE_10}');"></div>
                        <div class="price-card-body">
                            <div class="price-name">Fade or Trim</div>
                            <div class="price-amount">$10</div>
                            <div class="price-meta">
                                <span class="chip">30 min</span>
                                <span class="chip">Fade OR Trim</span>
                            </div>
                            <p class="price-desc">
                                Choose either a clean fade or a trim. Perfect for keeping your haircut
                                fresh without spending a lot.
                            </p>
                            <div class="price-line"><span class="gold-tag">One service - fade or trim, not both</span></div>
                        </div>
                    </div>
                    """
                )
                with st.container(key="price_link_10"):
                    st.button(
                        "Book Fade or Trim - $10 →",
                        key="pricing_book_10",
                        type="primary",
                        use_container_width=True,
                        on_click=go_to_service,
                        args=("Book Now", "Fade or Trim - $10 (30 min)"),
                    )

            with col_15:
                raw_html(
                    f"""
                    <div class="price-card featured">
                        <div class="badge">Most Popular</div>
                        <div class="price-card-img" style="background-image:url('{IMG_PRICE_15}');"></div>
                        <div class="price-card-body">
                            <div class="price-name">Full Haircut</div>
                            <div class="price-amount">$15</div>
                            <div class="price-meta">
                                <span class="chip">1 hour</span>
                                <span class="chip">Fade + Trim</span>
                            </div>
                            <p class="price-desc">
                                A complete haircut including a clean fade plus a trim for a full,
                                refreshed look.
                            </p>
                            <div class="price-line"><span class="gold-tag">The full service - fade and trim together</span></div>
                        </div>
                    </div>
                    """
                )
                with st.container(key="price_link_15"):
                    st.button(
                        "Book Full Haircut - $15 →",
                        key="pricing_book_15",
                        type="primary",
                        use_container_width=True,
                        on_click=go_to_service,
                        args=("Book Now", "Full Haircut - $15 (1 hour)"),
                    )

    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# BOOK NOW PAGE (account creation, login, appointment booking)
# ----------------------------------------------------------------------------
def render_book_now():
    raw_html(
        """
        <div class="section" style="padding-bottom:20px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">Book Now</div>
                <h2 class="section-title">Reserve your appointment</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
                <p class="section-sub" style="margin:14px auto 0 auto;">
                    Create a free account to book - it keeps your appointment history in one place
                    and makes rebooking quick.
                </p>
            </div>
        </div>
        """
    )

    left, mid, right = st.columns([1, 2.2, 1])

    with mid:
        if not st.session_state.user:
            with st.container(key="auth_tabs"):
                tab_login, tab_signup = st.tabs(["Log In", "Sign Up"])

                with tab_login:
                    with st.form("login_form"):
                        email = st.text_input("Email", key="login_email")
                        password = st.text_input("Password", type="password", key="login_password")
                        submitted = st.form_submit_button("Log In")
                        if submitted:
                            if not email or not password:
                                st.error("Please enter your email and password.")
                            elif email.strip().lower() == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
                                st.session_state.user = {
                                    "id": None,
                                    "name": "Freddie",
                                    "email": ADMIN_EMAIL,
                                    "phone": None,
                                    "is_admin": True,
                                }
                                st.success("Welcome back, Freddie!")
                                st.query_params["page"] = "Your Appointments"
                                st.rerun()
                            else:
                                user = verify_login(email, password)
                                if user:
                                    user["is_admin"] = False
                                    st.session_state.user = user
                                    st.success(f"Welcome back, {user['name']}!")
                                    st.rerun()
                                else:
                                    st.error("Incorrect email or password.")

                with tab_signup:
                    with st.form("signup_form"):
                        name = st.text_input("Full Name")
                        email = st.text_input("Email *", key="signup_email")
                        phone = st.text_input("Phone Number *", placeholder="e.g. (555) 123-4567")
                        password = st.text_input("Password", type="password", key="signup_password")
                        confirm = st.text_input("Confirm Password", type="password")
                        submitted = st.form_submit_button("Create Account")
                        if submitted:
                            if not name or not email or not phone or not password:
                                st.error("Name, email, phone number, and password are all required.")
                            elif not EMAIL_RE.match(email):
                                st.error("Please enter a valid email address.")
                            elif not PHONE_RE.match(phone):
                                st.error("Please enter a valid phone number.")
                            elif len(password) < 6:
                                st.error("Password must be at least 6 characters.")
                            elif password != confirm:
                                st.error("Passwords do not match.")
                            elif email.strip().lower() == ADMIN_EMAIL.lower():
                                st.error("This email is reserved. Please use a different one.")
                            else:
                                ok, msg = create_user(name, email, phone, password)
                                if ok:
                                    user = verify_login(email, password)
                                    user["is_admin"] = False
                                    st.session_state.user = user
                                    st.success("Account created! You're now signed in.")
                                    st.rerun()
                                else:
                                    st.error(msg)

        elif st.session_state.user.get("is_admin"):
            user = st.session_state.user
            st.markdown("### Welcome back, Freddie 👋")
            st.markdown(
                '<p style="color:#847f72;">Booking is for customer accounts. '
                'Head to the <b>Your Appointments</b> tab to see everyone\'s bookings on a calendar.</p>',
                unsafe_allow_html=True,
            )
            if st.button("Log Out", key="logout_freddie"):
                st.session_state.user = None
                st.rerun()

        else:
            user = st.session_state.user
            with st.container(key="customer_header"):
                top_l, top_r = st.columns([3, 1])
                with top_l:
                    st.markdown(f"### Welcome back, {user['name']} 👋")
                with top_r:
                    if st.button("Log Out", key="logout_customer"):
                        st.session_state.user = None
                        st.rerun()

            st.markdown("#### Book an Appointment")
            # Not wrapped in st.form on purpose: the Time dropdown needs to
            # refresh the moment the Date changes, so it only ever offers
            # slots nobody else has already taken that day.
            with st.container(key="booking_widget"):
                service_options = list(SERVICES.keys())
                preselected = st.session_state.pop("preselect_service", None)
                default_idx = service_options.index(preselected) if preselected in service_options else 0
                service_key = st.selectbox("Service", service_options, index=default_idx, key="booking_service")
                col_a, col_b = st.columns(2)
                with col_a:
                    appt_date = st.date_input(
                        "Date",
                        min_value=date.today(),
                        max_value=date.today() + timedelta(days=60),
                        value=date.today(),
                        key="booking_date",
                    )
                with col_b:
                    booked_times = get_booked_times(appt_date.isoformat())
                    available_times = [t for t in TIME_SLOTS if t not in booked_times]
                    if available_times:
                        appt_time = st.selectbox("Time", available_times, key="booking_time")
                    else:
                        appt_time = None
                        st.selectbox(
                            "Time",
                            ["Fully booked - pick another day"],
                            disabled=True,
                            key="booking_time_full",
                        )
                notes = st.text_area("Notes (optional)", placeholder="Anything the barber should know", key="booking_notes")
                if st.button("Confirm Appointment", key="booking_confirm_btn"):
                    if appt_time is None:
                        st.error("That day is fully booked - please choose another date.")
                    else:
                        ok, msg = create_appointment(user["id"], service_key, appt_date, appt_time, notes or "")
                        if ok:
                            st.success("Appointment booked! See it below.")
                            st.rerun()
                        else:
                            st.error(msg)

            st.markdown("#### Your Appointments")
            appts = get_appointments(user["id"])
            if not appts:
                st.markdown(
                    '<p style="color:#847f72;">No appointments yet - book your first one above.</p>',
                    unsafe_allow_html=True,
                )
            else:
                if "editing_appt_id" not in st.session_state:
                    st.session_state.editing_appt_id = None

                for appt_id, service, price, appt_date_str, appt_time_str, appt_notes, status in appts:
                    pretty_date = datetime.strptime(appt_date_str, "%Y-%m-%d").strftime("%b %d, %Y")
                    raw_html(
                        f"""
                        <div class="appt-card">
                            <div>
                                <div class="appt-service">{service} · {price}</div>
                                <div class="appt-meta"><span class="gold-tag">{pretty_date} at {appt_time_str}</span></div>
                            </div>
                            <div class="status-pill status-{status}">{status}</div>
                        </div>
                        """
                    )
                    if status == "Confirmed":
                        with st.container(key=f"appt_actions_{appt_id}"):
                            btn_a, btn_b = st.columns(2)
                            with btn_a:
                                if st.button("Change Time", key=f"change_{appt_id}"):
                                    st.session_state.editing_appt_id = (
                                        None if st.session_state.editing_appt_id == appt_id else appt_id
                                    )
                                    st.rerun()
                            with btn_b:
                                if st.button("Cancel", key=f"cancel_{appt_id}"):
                                    cancel_appointment(appt_id, user["id"])
                                    st.rerun()

                        if st.session_state.editing_appt_id == appt_id:
                            # Not st.form — the time list has to refresh live
                            # as soon as a new date is picked, so it only ever
                            # shows slots that are actually still open.
                            with st.container(key=f"reschedule_widget_{appt_id}"):
                                st.markdown(f"**Reschedule - {service}**")
                                rc_a, rc_b = st.columns(2)
                                with rc_a:
                                    new_date = st.date_input(
                                        "New date",
                                        min_value=date.today(),
                                        max_value=date.today() + timedelta(days=60),
                                        value=datetime.strptime(appt_date_str, "%Y-%m-%d").date(),
                                        key=f"reschedule_date_{appt_id}",
                                    )
                                with rc_b:
                                    booked_times = get_booked_times(new_date.isoformat(), exclude_appt_id=appt_id)
                                    available_times = [t for t in TIME_SLOTS if t not in booked_times]
                                    if new_date.isoformat() == appt_date_str and appt_time_str not in available_times:
                                        available_times = [appt_time_str] + available_times
                                    if available_times:
                                        current_idx = (
                                            available_times.index(appt_time_str)
                                            if appt_time_str in available_times
                                            else 0
                                        )
                                        new_time = st.selectbox(
                                            "New time",
                                            available_times,
                                            index=current_idx,
                                            key=f"reschedule_time_{appt_id}",
                                        )
                                    else:
                                        new_time = None
                                        st.selectbox(
                                            "New time",
                                            ["Fully booked - pick another day"],
                                            disabled=True,
                                            key=f"reschedule_time_full_{appt_id}",
                                        )
                                save_col, cancel_col = st.columns(2)
                                with save_col:
                                    save_clicked = st.button("Save New Time", key=f"reschedule_save_{appt_id}")
                                with cancel_col:
                                    cancel_clicked = st.button("Nevermind", key=f"reschedule_cancel_{appt_id}")
                                if save_clicked:
                                    if new_time is None:
                                        st.error("That day is fully booked - please choose another date.")
                                    else:
                                        ok, msg = reschedule_appointment(appt_id, user["id"], new_date, new_time)
                                        if ok:
                                            st.session_state.editing_appt_id = None
                                            st.success("Appointment updated.")
                                            st.rerun()
                                        else:
                                            st.error(msg)
                                if cancel_clicked:
                                    st.session_state.editing_appt_id = None
                                    st.rerun()

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# INSTAGRAM PAGE
# ----------------------------------------------------------------------------
def render_instagram():
    raw_html(
        f"""
        <div class="section" style="text-align:center;">
            <div class="section-head" style="text-align:center;">
                <div class="eyebrow" style="justify-content:center;">Stay Connected</div>
                <h2 class="section-title">Follow @fadedforless</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
            </div>
            <div class="insta-panel">
                <div class="insta-icon">📷</div>
                <div class="insta-handle">@fadedforless</div>
                <p class="insta-sub">
                    Fresh cuts, before-and-afters, and booking updates - all posted on Instagram.
                    Follow along to see the latest work and stay up to date.
                </p>
                <a class="btn-insta" href="{INSTAGRAM_URL}" target="_blank">Follow on Instagram</a>
            </div>
        </div>
        """
    )

# ----------------------------------------------------------------------------
# YOUR APPOINTMENTS PAGE (admin/owner only — calendar of every booking)
# ----------------------------------------------------------------------------
def render_my_schedule():
    user = st.session_state.user
    if not user or not user.get("is_admin"):
        st.warning("This page is only available to the shop owner.")
        return

    raw_html(
        """
        <div class="section" style="padding-bottom:20px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">Owner View</div>
                <h2 class="section-title">Your Appointments</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
                <p class="section-sub" style="margin:14px auto 0 auto;">
                    Every customer's booking, all in one calendar.
                </p>
            </div>
        </div>
        """
    )

    left, mid, right = st.columns([1, 2.6, 1])
    with mid:
        all_appts = get_all_appointments()
        active_appts = [a for a in all_appts if a[6] == "Confirmed"]

        by_date = {}
        for appt in active_appts:
            by_date.setdefault(appt[3], []).append(appt)

        if "schedule_month" not in st.session_state:
            today = date.today()
            st.session_state.schedule_month = (today.year, today.month)

        year, month = st.session_state.schedule_month

        nav_prev, nav_label, nav_next = st.columns([1, 3, 1])
        with nav_prev:
            if st.button("← Prev"):
                m = month - 1
                y = year
                if m == 0:
                    m, y = 12, year - 1
                st.session_state.schedule_month = (y, m)
                st.rerun()
        with nav_label:
            st.markdown(
                f"<h4 style='text-align:center; margin:6px 0;'>{cal_module.month_name[month]} {year}</h4>",
                unsafe_allow_html=True,
            )
        with nav_next:
            if st.button("Next →"):
                m = month + 1
                y = year
                if m == 13:
                    m, y = 1, year + 1
                st.session_state.schedule_month = (y, m)
                st.rerun()

        weeks = cal_module.Calendar(firstweekday=6).monthdayscalendar(year, month)
        dow_html = "".join(f'<div class="cal-dow">{d}</div>' for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])
        cells_html = ""
        today = date.today()
        for week in weeks:
            for day_num in week:
                if day_num == 0:
                    cells_html += '<div class="cal-cell empty"></div>'
                    continue
                this_date = date(year, month, day_num)
                iso = this_date.isoformat()
                count = len(by_date.get(iso, []))
                today_class = " today" if this_date == today else ""
                count_html = f'<div class="cal-count">{count} booked</div>' if count else ""
                cells_html += f'<div class="cal-cell{today_class}"><div class="cal-daynum">{day_num}</div>{count_html}</div>'
        raw_html(f'<div class="cal-grid">{dow_html}{cells_html}</div>')

        st.markdown("#### Pick a day to see the schedule")
        picked_day = st.date_input(
            "Day",
            value=today,
            min_value=date(year, month, 1),
            max_value=date(year, month, cal_module.monthrange(year, month)[1]),
            label_visibility="collapsed",
        )
        day_appts = by_date.get(picked_day.isoformat(), [])
        if not day_appts:
            st.markdown(
                '<p style="color:#847f72;">No appointments booked for this day.</p>',
                unsafe_allow_html=True,
            )
        else:
            for appt_id, service, price, appt_date_str, appt_time_str, notes, status, cust_name, cust_phone, cust_email in day_appts:
                contact = cust_phone or cust_email or ""
                raw_html(
                    f"""
                    <div class="admin-appt-row">
                        <div class="admin-appt-time">{appt_time_str}</div>
                        <div style="flex:1; min-width:160px;">
                            <div class="admin-appt-cust">{cust_name}</div>
                            <div class="admin-appt-service"><span class="gold-tag">{service} · {price}{" · " + contact if contact else ""}</span></div>
                        </div>
                    </div>
                    """
                )

        st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
        st.markdown("#### All Upcoming Appointments")
        raw_html('<p style="color:#E9E4D6; font-size:0.88rem; margin-top:-6px;">Change or cancel any customer\'s appointment right here.</p>')
        upcoming = [a for a in active_appts if a[3] >= today.isoformat()]
        if not upcoming:
            st.markdown(
                '<p style="color:#847f72;">Nothing upcoming.</p>',
                unsafe_allow_html=True,
            )
        else:
            if "admin_editing_appt_id" not in st.session_state:
                st.session_state.admin_editing_appt_id = None

            for appt_id, service, price, appt_date_str, appt_time_str, notes, status, cust_name, cust_phone, cust_email in upcoming:
                pretty_date = datetime.strptime(appt_date_str, "%Y-%m-%d").strftime("%b %d, %Y")
                contact = cust_phone or cust_email or ""
                raw_html(
                    f"""
                    <div class="admin-appt-row">
                        <div class="admin-appt-time">{pretty_date}<br>{appt_time_str}</div>
                        <div style="flex:1; min-width:160px;">
                            <div class="admin-appt-cust">{cust_name}</div>
                            <div class="admin-appt-service"><span class="gold-tag">{service} · {price}{" · " + contact if contact else ""}</span></div>
                        </div>
                    </div>
                    """
                )
                with st.container(key=f"admin_appt_actions_{appt_id}"):
                    btn_a, btn_b = st.columns(2)
                    with btn_a:
                        if st.button("Change Time", key=f"admin_change_{appt_id}"):
                            st.session_state.admin_editing_appt_id = (
                                None if st.session_state.admin_editing_appt_id == appt_id else appt_id
                            )
                            st.rerun()
                    with btn_b:
                        if st.button("Cancel", key=f"admin_cancel_{appt_id}"):
                            admin_cancel_appointment(appt_id)
                            st.rerun()

                if st.session_state.admin_editing_appt_id == appt_id:
                    # Not st.form — same reasoning as the customer reschedule:
                    # the time list must refresh the instant the date changes.
                    with st.container(key=f"admin_reschedule_widget_{appt_id}"):
                        st.markdown(f"**Reschedule {cust_name} - {service}**")
                        rc_a, rc_b = st.columns(2)
                        with rc_a:
                            new_date = st.date_input(
                                "New date",
                                min_value=date.today(),
                                max_value=date.today() + timedelta(days=60),
                                value=datetime.strptime(appt_date_str, "%Y-%m-%d").date(),
                                key=f"admin_reschedule_date_{appt_id}",
                            )
                        with rc_b:
                            booked_times = get_booked_times(new_date.isoformat(), exclude_appt_id=appt_id)
                            available_times = [t for t in TIME_SLOTS if t not in booked_times]
                            if new_date.isoformat() == appt_date_str and appt_time_str not in available_times:
                                available_times = [appt_time_str] + available_times
                            if available_times:
                                current_idx = (
                                    available_times.index(appt_time_str)
                                    if appt_time_str in available_times
                                    else 0
                                )
                                new_time = st.selectbox(
                                    "New time",
                                    available_times,
                                    index=current_idx,
                                    key=f"admin_reschedule_time_{appt_id}",
                                )
                            else:
                                new_time = None
                                st.selectbox(
                                    "New time",
                                    ["Fully booked - pick another day"],
                                    disabled=True,
                                    key=f"admin_reschedule_time_full_{appt_id}",
                                )
                        save_col, cancel_col = st.columns(2)
                        with save_col:
                            save_clicked = st.button("Save New Time", key=f"admin_reschedule_save_{appt_id}")
                        with cancel_col:
                            cancel_clicked = st.button("Nevermind", key=f"admin_reschedule_cancel_{appt_id}")
                        if save_clicked:
                            if new_time is None:
                                st.error("That day is fully booked - please choose another date.")
                            else:
                                ok, msg = admin_reschedule_appointment(appt_id, new_date, new_time)
                                if ok:
                                    st.session_state.admin_editing_appt_id = None
                                    st.success("Appointment updated.")
                                    st.rerun()
                                else:
                                    st.error(msg)
                        if cancel_clicked:
                            st.session_state.admin_editing_appt_id = None
                            st.rerun()

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# CUSTOMERS PAGE (admin/owner only) — every registered customer, their
# contact info, and their haircut history at a glance.
# ----------------------------------------------------------------------------
def render_customers():
    user = st.session_state.user
    if not user or not user.get("is_admin"):
        st.warning("This page is only available to the shop owner.")
        return

    raw_html(
        """
        <div class="section" style="padding-bottom:10px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">Owner View</div>
                <h2 class="section-title">Customer Data</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
                <p class="section-sub" style="margin:14px auto 0 auto;">
                    Every registered customer - full name, phone, how many times they've
                    come in, and the different haircuts they've gotten.
                </p>
            </div>
        </div>
        """
    )
    left2, mid2, right2 = st.columns([1, 2.6, 1])
    with mid2:
        customer_stats = get_customer_stats()
        if not customer_stats:
            st.markdown(
                '<p style="color:#847f72;">No customers have signed up yet.</p>',
                unsafe_allow_html=True,
            )
        else:
            st.dataframe(customer_stats, use_container_width=True, hide_index=True)

            st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)
            st.markdown("#### Customer Details")
            st.markdown(
                '<p style="color:#847f72; margin-top:-6px;">Open a name to see their appointments '
                'and what the Style AI told them about their hair.</p>',
                unsafe_allow_html=True,
            )

            conn = get_conn()
            customers = conn.execute(
                "SELECT id, name, phone FROM users ORDER BY name COLLATE NOCASE ASC"
            ).fetchall()
            for cust_id, cust_name, cust_phone in customers:
                cust_appts = get_appointments(cust_id)
                cust_notes = get_style_notes(cust_id)
                with st.expander(f"{cust_name}" + (f" · {cust_phone}" if cust_phone else "")):
                    st.markdown("**Appointments**")
                    if not cust_appts:
                        st.markdown(
                            '<p style="color:#847f72;">No appointments yet.</p>',
                            unsafe_allow_html=True,
                        )
                    else:
                        for _appt_id, service, price, appt_date_str, appt_time_str, _notes, status in cust_appts:
                            pretty_date = datetime.strptime(appt_date_str, "%Y-%m-%d").strftime("%b %d, %Y")
                            raw_html(
                                f"""
                                <div class="appt-card">
                                    <div>
                                        <div class="appt-service">{service} · {price}</div>
                                        <div class="appt-meta"><span class="gold-tag">{pretty_date} at {appt_time_str}</span></div>
                                    </div>
                                    <div class="status-pill status-{status}">{status}</div>
                                </div>
                                """
                            )

                    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
                    st.markdown("**What the Style AI told them**")
                    if not cust_notes:
                        st.markdown(
                            '<p style="color:#847f72;">Hasn\'t used the Style AI yet.</p>',
                            unsafe_allow_html=True,
                        )
                    else:
                        for note, created_at in cust_notes:
                            pretty_ts = datetime.fromisoformat(created_at).strftime("%b %d, %Y at %I:%M %p")
                            raw_html(
                                f"""
                                <div class="appt-card" style="flex-direction:column; align-items:flex-start; gap:6px;">
                                    <div class="appt-meta"><span class="gold-tag">{pretty_ts}</span></div>
                                    <p style="margin:0; color:#EDEAE2;">{note}</p>
                                </div>
                                """
                            )

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# SETTINGS PAGE — device view switch (for everyone) plus, for customers,
# an editable profile: picture, email, phone.
# ----------------------------------------------------------------------------
def render_settings():
    user = st.session_state.user
    if not user:
        st.warning("Please log in to view Settings.")
        return

    raw_html(
        """
        <div class="section" style="padding-bottom:10px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">Account</div>
                <h2 class="section-title">Settings</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
            </div>
        </div>
        """
    )

    left, mid, right = st.columns([1, 2.2, 1])
    with mid:
        if user.get("is_admin"):
            st.markdown(
                '<p style="color:#847f72;">Profile editing is for customer accounts only.</p>',
                unsafe_allow_html=True,
            )
            return

        st.markdown("#### Profile")
        current_pic = user.get("profile_pic")
        if current_pic:
            raw_html(
                f'<img src="{current_pic}" alt="Profile picture" '
                f'style="width:120px; height:120px; border-radius:50%; object-fit:cover; '
                f'border:2px solid var(--gold); margin-bottom:14px;" />'
            )
        uploaded_pic = st.file_uploader(
            "Profile picture", type=["png", "jpg", "jpeg"], key="settings_pic_upload"
        )

        new_email = st.text_input("Email", value=user.get("email", ""), key="settings_email")
        new_phone = st.text_input("Phone Number", value=user.get("phone", "") or "", key="settings_phone")

        if st.button("Save Changes", key="settings_save_btn"):
            if not EMAIL_RE.match(new_email):
                st.error("Please enter a valid email address.")
            elif not PHONE_RE.match(new_phone):
                st.error("Please enter a valid phone number.")
            else:
                pic_b64 = None
                if uploaded_pic is not None:
                    ext = uploaded_pic.name.rsplit(".", 1)[-1].lower()
                    mime = "image/png" if ext == "png" else "image/jpeg"
                    encoded = base64.b64encode(uploaded_pic.getvalue()).decode("ascii")
                    pic_b64 = f"data:{mime};base64,{encoded}"
                ok, msg = update_profile(user["id"], new_email, new_phone, pic_b64)
                if ok:
                    st.session_state.user["email"] = new_email.strip().lower()
                    st.session_state.user["phone"] = new_phone.strip()
                    if pic_b64:
                        st.session_state.user["profile_pic"] = pic_b64
                    st.success("Profile updated.")
                    st.rerun()
                else:
                    st.error(msg)

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# STYLE PAGE (customers only) — take a photo, Gemini recommends a haircut.
# ----------------------------------------------------------------------------
def render_style():
    user = st.session_state.user
    if not user or user.get("is_admin"):
        st.warning("Please log in with a customer account to use Style AI.")
        return

    raw_html(
        """
        <div class="section" style="padding-bottom:10px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">AI Consultation</div>
                <h2 class="section-title">Find Your Style</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
                <p class="section-sub" style="margin:14px auto 0 auto;">
                    Snap a photo and get a fade and haircut recommendation before you sit in the chair.
                </p>
            </div>
        </div>
        """
    )

    with st.container(key="style_photo_widget"):
        left, mid, right = st.columns([1, 3.4, 1])
        with mid:
            photo = st.camera_input("Take a photo", key="style_camera")
            if photo is not None:
                if st.button("Get My Recommendation", key="style_analyze_btn"):
                    with st.spinner("Analyzing your photo..."):
                        ok, result = analyze_style_photo(photo.getvalue(), mime_type=photo.type or "image/jpeg")
                    if ok:
                        # Stash it in session state (not the database yet) — the
                        # customer decides below whether Freddie gets to see it.
                        st.session_state.style_result_text = result
                        st.session_state.style_result_decision = None
                    else:
                        st.session_state.style_result_text = None
                        st.error(result)

            if st.session_state.get("style_result_text"):
                raw_html(
                    f"""
                    <div class="appt-card" style="flex-direction:column; align-items:flex-start; gap:10px;">
                        <div class="appt-service">Your Recommendation</div>
                        <p style="margin:0; color:#EDEAE2; font-size:1.08rem; line-height:1.65;">{st.session_state.style_result_text}</p>
                    </div>
                    """
                )

            decision = st.session_state.get("style_result_decision")
            if decision is None:
                st.markdown(
                    """
                    <p style="color:#847f72; margin:16px 0 8px 0;">
                        Want to share this with Freddie so he knows what you're going for before your appointment?
                    </p>
                    """,
                    unsafe_allow_html=True,
                )
                with st.container(key="style_share_buttons"):
                    send_col, keep_col = st.columns(2)
                    with send_col:
                        if st.button("Send to Freddie", key="style_send_btn"):
                            save_style_note(user["id"], st.session_state.style_result_text)
                            st.session_state.style_result_decision = "sent"
                            st.rerun()
                    with keep_col:
                        if st.button("Keep Just for Me", key="style_private_btn"):
                            st.session_state.style_result_decision = "private"
                            st.rerun()
            elif decision == "sent":
                st.success("Sent to Freddie ✓ - he'll have this before your appointment.")
            else:
                st.info("Kept private - only you can see this.")

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# ROUTER
# ----------------------------------------------------------------------------
if current_page == "Home":
    render_home()
elif current_page == "About Me":
    render_about()
elif current_page == "Pricing":
    render_pricing()
elif current_page == "Book Now":
    render_book_now()
elif current_page == "Instagram":
    render_instagram()
elif current_page == "Your Appointments":
    render_my_schedule()
elif current_page == "Customers":
    render_customers()
elif current_page == "Settings":
    render_settings()
elif current_page == "Style":
    render_style()

# ----------------------------------------------------------------------------
# FOOTER
# ----------------------------------------------------------------------------
raw_html(
    """
    <div class="footer">
        FADED<span>FOR</span>LESS - Premium cuts. Fair prices.
    </div>
    """
)

#.\.venv\Scripts\Activate.ps1; streamlit run app.py
#git add .; git commit -m "Update website"; git push