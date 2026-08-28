import streamlit as st
import streamlit.components.v1 as components
import libsql
import hashlib
import os
import re
import random
import string
import base64
import calendar as cal_module
import smtplib
import ssl
import threading
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

# Style showcase — real barbering photography from the shop itself, one per
# featured cut so customers can see exactly what they're booking before they
# book it. Loaded locally (same pattern as the logo/owner photo above) so
# they keep working with no internet dependency once deployed.
STYLE_SHOWCASE = [
    {"name": "Mid Fade", "tag": "Fade", "img": load_image_b64("style_midfade.jpg")},
    {"name": "Low Fade", "tag": "Fade", "img": load_image_b64("style_lowfade.jpg")},
    {"name": "Low Taper Fade", "tag": "Fade", "img": load_image_b64("style_lowtaperfade.jpg")},
    {"name": "Lineup", "tag": "Edge Up", "img": load_image_b64("style_lineup.jpg")},
    {"name": "Beard Trim", "tag": "Beard", "img": load_image_b64("style_beardtrim.jpg")},
    {"name": "Undercut", "tag": "Cut", "img": load_image_b64("style_undercut.jpg")},
]

SERVICES = {
    "Fade or Trim - $10 (30 min)": {"label": "Fade or Trim", "price": "$10", "duration": "30 min"},
    "Full Haircut - $15 (1 hour)": {"label": "Full Haircut (Fade + Trim)", "price": "$15", "duration": "1 hour"},
}

# Cents version of each service price, used for referral-credit math (the
# "price" strings above stay as the display labels everywhere else).
SERVICE_PRICE_CENTS = {k: int(round(float(v["price"].replace("$", "")) * 100)) for k, v in SERVICES.items()}

# ----------------------------------------------------------------------------
# DATABASE
# ----------------------------------------------------------------------------
# Data now lives in Turso (a hosted, persistent libSQL/SQLite-compatible
# database) instead of a local file — Streamlit Cloud wipes local files on
# every sleep/restart, which used to wipe every account, booking, and Style
# AI note along with it. Turso survives restarts since it's not part of the
# app's own filesystem.
#
# Reads the two secrets set in Settings > Secrets (or a local
# .streamlit/secrets.toml when running on your own machine):
#   TURSO_DATABASE_URL   e.g. libsql://your-db-name-yourorg.turso.io
#   TURSO_AUTH_TOKEN     the long token generated alongside it
def get_db_secret(key):
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


def _raw_connect():
    database_url = get_db_secret("TURSO_DATABASE_URL")
    auth_token = get_db_secret("TURSO_AUTH_TOKEN")
    if not database_url or not auth_token:
        st.error(
            "Database isn't configured: TURSO_DATABASE_URL and/or TURSO_AUTH_TOKEN "
            "are missing from Secrets. Add them in Settings > Secrets, then reload."
        )
        st.stop()
    return libsql.connect(database=database_url, auth_token=auth_token)


class _ResilientConn:
    """Wraps the real libsql connection and transparently reconnects+retries
    ONCE if a query fails. get_conn() is cached with @st.cache_resource, so
    the whole app was sharing one raw connection for its entire lifetime -
    great for speed, but Turso can drop an idle connection after a quiet
    stretch (very common on Streamlit Cloud, which sleeps between
    visitors), and there was no way to recover from that: the next query
    ANYWHERE in the app - like get_all_appointments() on the schedule page -
    would just crash. Only .execute() and .commit() are used on `conn`
    anywhere in this file, so wrapping just those two methods is a drop-in
    fix; nothing else in the app has to change."""
    def __init__(self, connect_fn):
        self._connect_fn = connect_fn
        self._raw = connect_fn()

    def _reconnect(self):
        self._raw = self._connect_fn()

    def execute(self, *args, **kwargs):
        try:
            return self._raw.execute(*args, **kwargs)
        except Exception:
            self._reconnect()
            return self._raw.execute(*args, **kwargs)

    def commit(self):
        try:
            return self._raw.commit()
        except Exception:
            self._reconnect()
            return self._raw.commit()


@st.cache_resource
def get_conn():
    return _ResilientConn(_raw_connect)


def check_turso_status():
    """Round-trip test — actually writes a value to the settings table and
    reads it back, rather than just checking that get_conn() didn't error.
    That way a stale/cached connection object can't report 'connected' when
    writes are silently failing. Returns (ok, message)."""
    try:
        conn = get_conn()
        test_value = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("_turso_healthcheck", test_value),
        )
        conn.commit()
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", ("_turso_healthcheck",)
        ).fetchone()
        if row and row[0] == test_value:
            return True, f"Connected to Turso — data is saving correctly. (checked {test_value})"
        return False, "Connected, but the write didn't read back correctly — something's off."
    except Exception as e:
        return False, f"Could NOT reach Turso: {e}"


@st.cache_resource
def init_db():
    """Cached with @st.cache_resource so this only actually runs ONCE for
    the whole app (not once per click). Without this, every button press
    re-ran all 6 CREATE/ALTER TABLE statements as fresh network round-trips
    to Turso before the page even started rendering — that was the single
    biggest source of lag after moving off local SQLite."""
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
    except Exception as e:
        # Column already there — Turso/libsql doesn't necessarily raise the
        # same exception class sqlite3 does, so match on the message instead.
        if "duplicate column" not in str(e).lower():
            raise
    # Referral program: every user gets a unique shareable code, plus a
    # credit balance (in cents, to avoid float rounding) that's earned by
    # referring friends and spent at booking time. referred_by records which
    # code a user signed up with, purely for the owner's own records.
    for stmt in (
        "ALTER TABLE users ADD COLUMN referral_code TEXT",
        "ALTER TABLE users ADD COLUMN credit_cents INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN referred_by TEXT",
    ):
        try:
            conn.execute(stmt)
            conn.commit()
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                raise
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
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise
    # How much referral credit (in cents) was applied to this specific
    # booking — kept per-appointment so the owner can see exactly what was
    # honored at checkout, even after the customer's balance has moved on.
    try:
        conn.execute("ALTER TABLE appointments ADD COLUMN credit_applied_cents INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise
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
    # Simple owner-editable key/value settings — currently used to store the
    # booking-availability window (start/end time) the owner picks in
    # Settings, so customers can only book/reschedule inside those hours.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
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


REFERRAL_BONUS_CENTS = 1000  # $10 credit for both the new signup and the friend who referred them


def _generate_referral_code(name):
    """4 letters from the name + 4 random digits, e.g. 'ALEX4821'. Retries
    on the rare collision since it's stored as UNIQUE-ish (checked by hand
    below, since ALTER TABLE can't easily add a UNIQUE constraint after the
    fact on every DB backend)."""
    conn = get_conn()
    base = "".join(ch for ch in name.upper() if ch.isalpha())[:4] or "CUT"
    for _ in range(10):
        code = f"{base}{random.randint(1000, 9999)}"
        exists = conn.execute("SELECT id FROM users WHERE referral_code = ?", (code,)).fetchone()
        if not exists:
            return code
    return f"{base}{random.randint(10000, 99999)}"


def format_cents(cents):
    return f"${cents / 100:.2f}".rstrip("0").rstrip(".") if cents % 100 == 0 else f"${cents / 100:.2f}"


def create_user(name, email, phone, password, referral_code_used=None):
    conn = get_conn()
    salt, pw_hash = hash_password(password)
    clean_name = name.strip()
    clean_email = email.strip().lower()
    my_code = _generate_referral_code(clean_name)
    try:
        conn.execute(
            "INSERT INTO users (name, email, phone, salt, password_hash, created_at, referral_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (clean_name, clean_email, phone.strip(), salt, pw_hash, datetime.now().isoformat(), my_code),
        )
        conn.commit()
    except Exception as e:
        # Same reasoning as the migration catches above: match on the
        # message instead of a specific exception class.
        if "unique" in str(e).lower() or "constraint" in str(e).lower():
            return False, "An account with this email already exists."
        raise

    new_user_row = conn.execute("SELECT id FROM users WHERE email = ?", (clean_email,)).fetchone()
    new_user_id = new_user_row[0] if new_user_row else None

    referral_applied = False
    if referral_code_used and referral_code_used.strip():
        entered = referral_code_used.strip().upper()
        referrer = conn.execute(
            "SELECT id, name, email FROM users WHERE referral_code = ?", (entered,)
        ).fetchone()
        if referrer and referrer[0] != new_user_id:
            conn.execute(
                "UPDATE users SET credit_cents = credit_cents + ? WHERE id = ?",
                (REFERRAL_BONUS_CENTS, new_user_id),
            )
            conn.execute(
                "UPDATE users SET credit_cents = credit_cents + ? WHERE id = ?",
                (REFERRAL_BONUS_CENTS, referrer[0]),
            )
            conn.execute("UPDATE users SET referred_by = ? WHERE id = ?", (entered, new_user_id))
            conn.commit()
            referral_applied = True
            send_email(
                referrer[2],
                "You earned $10 in referral credit!",
                email_wrapper(
                    f"<p>Hey {referrer[1]},</p>"
                    f"<p>{clean_name} just signed up using your referral code - "
                    f"you've got <strong>$10 in credit</strong> toward your next visit.</p>"
                    "<p>- FADEDFORLESS</p>"
                ),
            )

    notify_signup(clean_name, clean_email, referral_applied)
    return True, "Account created."


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
    except Exception as e:
        if "unique" in str(e).lower() or "constraint" in str(e).lower():
            return False, "Another account already uses that email."
        raise


@st.cache_data(ttl=5)
def _get_booked_slots_cached(appt_date_iso):
    """(appt_time, appt_id) pairs for every Confirmed appointment on a date,
    cached briefly. The booking/reschedule pickers used to hit Turso on
    every single script rerun (typing in Notes, tapping a service card,
    etc. reruns the whole page) just to re-fetch the same booked list for
    the same date - this cuts that down to one network round trip per 5
    seconds instead of one per keystroke. Actual double-booking safety
    still comes from the fresh check inside create_appointment /
    reschedule_appointment at write time, so a few seconds of staleness
    here can't cause a real conflict - worst case someone briefly sees a
    slot as open that just got taken, and the write-time check catches it.
    Cleared immediately on any booking/cancel/reschedule via .clear()."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT appt_time, id FROM appointments WHERE appt_date = ? AND status = 'Confirmed'",
        (appt_date_iso,),
    ).fetchall()
    return rows


def get_booked_times(appt_date_iso, exclude_appt_id=None):
    """Every time slot already taken (by ANY customer) on a given date, so the
    booking/reschedule pickers can hide them entirely — no double-booking."""
    rows = _get_booked_slots_cached(appt_date_iso)
    if exclude_appt_id is None:
        return {r[0] for r in rows}
    return {r[0] for r in rows if r[1] != exclude_appt_id}


def create_appointment(user_id, service_key, appt_date, appt_time, notes, credit_cents_to_apply=0):
    """Returns (ok, message). Re-checks the slot at write time (not just what
    the picker showed) so two people submitting at nearly the same moment
    can't both land the same slot. credit_cents_to_apply (referral credit)
    is recorded on the appointment and deducted from the user's balance -
    the owner honors the discount in person, same as every other price on
    this site (there's no live payment processing here)."""
    conn = get_conn()
    conflict = conn.execute(
        "SELECT id FROM appointments WHERE appt_date = ? AND appt_time = ? AND status = 'Confirmed'",
        (appt_date.isoformat(), appt_time),
    ).fetchone()
    if conflict:
        return False, "Sorry - that time slot was just booked by someone else. Please pick another."
    service = SERVICES[service_key]
    conn.execute(
        "INSERT INTO appointments (user_id, service, price, appt_date, appt_time, notes, status, created_at, credit_applied_cents) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Confirmed', ?, ?)",
        (
            user_id, service["label"], service["price"], appt_date.isoformat(), appt_time,
            notes.strip(), datetime.now().isoformat(), credit_cents_to_apply,
        ),
    )
    if credit_cents_to_apply:
        conn.execute(
            "UPDATE users SET credit_cents = MAX(0, credit_cents - ?) WHERE id = ?",
            (credit_cents_to_apply, user_id),
        )
    conn.commit()
    _get_booked_slots_cached.clear()
    _get_appointments_cached.clear()
    user_row = conn.execute("SELECT name, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if user_row:
        notify_booking(user_row[0], user_row[1], service["label"], appt_date.isoformat(), appt_time)
    return True, "Appointment booked."


def get_credit_cents(user_id):
    conn = get_conn()
    row = conn.execute("SELECT credit_cents FROM users WHERE id = ?", (user_id,)).fetchone()
    return row[0] if row and row[0] else 0


def get_referral_code(user_id):
    conn = get_conn()
    row = conn.execute("SELECT referral_code FROM users WHERE id = ?", (user_id,)).fetchone()
    return row[0] if row else None


LOYALTY_CYCLE = 6  # every 6th completed cut is free


def get_loyalty_progress(user_id):
    """Loyalty punch card is purely informational (no separate redemption
    tracking/new table) - it's computed straight from appointment history:
    every past Confirmed appointment counts as one punch. Returns
    (completed_cuts, punches_in_current_cycle, free_cuts_earned)."""
    conn = get_conn()
    today_iso = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM appointments WHERE user_id = ? AND status = 'Confirmed' AND appt_date < ?",
        (user_id, today_iso),
    ).fetchone()
    completed = row[0] if row else 0
    return completed, completed % LOYALTY_CYCLE, completed // LOYALTY_CYCLE


@st.cache_data(ttl=5)
def _get_appointments_cached(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, service, price, appt_date, appt_time, notes, status FROM appointments "
        "WHERE user_id = ? ORDER BY appt_date ASC, appt_time ASC",
        (user_id,),
    ).fetchall()
    return rows


def get_appointments(user_id):
    return _get_appointments_cached(user_id)


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
    _get_booked_slots_cached.clear()
    _get_appointments_cached.clear()
    _get_all_appointments_cached.clear()
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
    _get_booked_slots_cached.clear()
    _get_appointments_cached.clear()
    _get_all_appointments_cached.clear()
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
    _get_booked_slots_cached.clear()
    _get_appointments_cached.clear()
    _get_all_appointments_cached.clear()
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
    _get_booked_slots_cached.clear()
    _get_appointments_cached.clear()
    _get_all_appointments_cached.clear()
    if old_row:
        service, old_date, old_time, name, email = old_row
        notify_reschedule(name, email, service, old_date, old_time, new_date.isoformat(), new_time, by_owner=True)
    return True, "Appointment updated."


@st.cache_data(ttl=5)
def _get_all_appointments_cached():
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


def get_all_appointments():
    """Every appointment across every customer — used by the owner/admin
    schedule view. Cached briefly (see _get_all_appointments_cached) since
    the admin schedule re-queries this on every rerun otherwise."""
    return _get_all_appointments_cached()


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


@st.cache_data(ttl=30)
def _get_all_settings_cached():
    """All settings in ONE network round-trip, cached for 30 seconds.
    get_setting() used to cost its own Turso round-trip every single call —
    and get_day_hours() calls it 3x per weekday, so just rendering the
    Availability section made 21 separate network requests. This fetches
    everything at once and reuses it. Cleared instantly on any write via
    set_setting(), so the owner's changes still show up right away."""
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return dict(rows)


def get_setting(key, default=None):
    settings = _get_all_settings_cached()
    return settings.get(key, default)


def set_setting(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    _get_all_settings_cached.clear()


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


def _call_gemini(contents):
    """Shared low-level Gemini caller — takes a ready-made `contents` list
    (Gemini's multi-turn message format) and returns (ok, text_or_error)."""
    import json
    import urllib.request
    import urllib.error

    api_key = get_gemini_api_key()
    if not api_key:
        return False, "Style AI isn't set up yet - ask the shop owner to add a GEMINI_API_KEY."

    payload = {"contents": contents}
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


def analyze_style_photo(image_bytes, mime_type="image/jpeg"):
    """Sends the customer's photo to Gemini and asks for a haircut/fade
    recommendation. Returns (ok, text_or_error_message)."""
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
    contents = [
        {
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": b64_img}},
                {"text": prompt},
            ],
        }
    ]
    return _call_gemini(contents)


def analyze_style_photos_owner(photos):
    """Owner-only version — takes three photos (back, side, top/front) of a
    customer's head and asks Gemini for a full cutting plan: what to do on
    top, which fade (if any), and whether the fade should be sides-only.
    `photos` is a list of (image_bytes, mime_type) tuples in that order.
    Returns (ok, text_or_error_message)."""
    labels = ["back of the head", "side of the head", "top/front of the head"]
    parts = []
    for (image_bytes, mime_type), label in zip(photos, labels):
        b64_img = base64.b64encode(image_bytes).decode("ascii")
        parts.append({"text": f"Photo of the {label}:"})
        parts.append({"inline_data": {"mime_type": mime_type, "data": b64_img}})
    prompt = (
        "You are a master barber giving another barber a precise cutting plan before they "
        "pick up the clippers, based on these three photos of the same customer's head "
        "(back, side, and top/front). Be specific and decisive. Cover, as short labeled "
        "lines (not paragraphs): "
        "1) Top: exactly how to cut the top (length in clipper guard number or inches, "
        "texture/point cutting notes, how much to take off). "
        "2) Fade or not: state clearly whether this customer should get a fade at all, "
        "given their hair type and current length — some heads shouldn't be faded. "
        "3) Fade type: if yes, which fade (skin/bald fade, low, mid, high, taper) and "
        "exactly where it should start relative to the back and sides photos. "
        "4) Sides only: state explicitly whether the fade should be done on the sides only "
        "(leaving the back blended but not faded) or should wrap all the way around the "
        "back too. "
        "Keep it tight and practical, like a note pinned to the mirror before the cut — "
        "no fluff, no markdown headers, just the four points."
    )
    parts.append({"text": prompt})
    contents = [{"role": "user", "parts": parts}]
    return _call_gemini(contents)


def style_chat_reply(history):
    """Continues a Style-AI conversation after the initial photo
    recommendation. `history` is a list of {"role": "user"/"model", "text":
    str} dicts (the running conversation, oldest first). Returns
    (ok, text_or_error_message)."""
    contents = [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in history]
    return _call_gemini(contents)


FULL_DAY_SLOTS = None  # every possible 30-min slot, 12:00 AM - 11:30 PM — used by
                       # the owner's Availability picker in Settings


def generate_time_slots(start_str="9:00 AM", end_str="9:00 PM"):
    """Generates 30-minute slots between start_str and end_str (inclusive).
    No longer hard-capped at 6:00 PM — the owner controls the real cutoff
    via the Availability setting below, and it can run as late as they like."""
    slots = []
    t = datetime.strptime(start_str, "%I:%M %p")
    end = datetime.strptime(end_str, "%I:%M %p")
    while t <= end:
        slots.append(t.strftime("%I:%M %p").lstrip("0"))
        t += timedelta(minutes=30)
    return slots


FULL_DAY_SLOTS = generate_time_slots("12:00 AM", "11:30 PM")

# The owner picks hours PER DAY OF THE WEEK (Settings > Availability) — e.g.
# open later on weekends, closed on Sundays, etc. Falls back to 9:00 AM -
# 9:00 PM (already later than the old fixed 6:00 PM cutoff) for any day the
# owner hasn't customized yet.
WEEKDAYS = [
    ("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"),
    ("thu", "Thursday"), ("fri", "Friday"), ("sat", "Saturday"), ("sun", "Sunday"),
]


def get_day_hours(weekday_key):
    """Returns (start_str, end_str, closed_bool) for one weekday key
    ('mon'..'sun'), reading the owner's per-day Settings — or the old
    single avail_start/avail_end as a fallback for anyone upgrading from
    the previous single-window version, or sane defaults if neither is set."""
    fallback_start = get_setting("avail_start", "9:00 AM")
    fallback_end = get_setting("avail_end", "9:00 PM")
    start = get_setting(f"avail_{weekday_key}_start", fallback_start)
    end = get_setting(f"avail_{weekday_key}_end", fallback_end)
    closed = get_setting(f"avail_{weekday_key}_closed", "0") == "1"
    return start, end, closed


def time_slots_for_date(target_date):
    """The actual bookable 30-min slots for a specific calendar date, based
    on whatever hours the owner set for that day of the week. Empty list
    means the shop is closed that day."""
    weekday_key = WEEKDAYS[target_date.weekday()][0]
    start, end, closed = get_day_hours(weekday_key)
    if closed:
        return []
    return generate_time_slots(start, end)


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


def _send_email_raw(to_email, subject, html_body):
    """Does the actual send, returns (ok, error_message). error_message is
    "" on success — this is the version that shows the real reason when
    something fails, used by the Settings 'Send Test Email' button."""
    if not email_is_configured():
        return False, "Not configured: GMAIL_APP_PASSWORD secret is missing or empty."
    if not to_email:
        return False, "No recipient email address was given."
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"FADEDFORLESS <{GMAIL_ADDRESS}>"
        msg["To"] = to_email
        msg.set_content("This email requires an HTML-capable email client to view.")
        msg.add_alternative(html_body, subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _send_email_background(to_email, subject, html_body):
    ok, error = _send_email_raw(to_email, subject, html_body)
    if not ok:
        print(f"[email] Failed to send to {to_email}: {error}")


def send_email(to_email, subject, html_body):
    """Fires off one HTML email via Gmail SMTP on a background thread and
    returns immediately. Every signup/booking/cancel/reschedule used to call
    this 2x (customer + owner) *synchronously* — each SMTP round trip (SSL
    handshake + login + send) can easily take 1-3 seconds, so actions like
    "Create Account" or "Confirm Appointment" were blocking the whole page
    for several seconds with zero visual feedback. That's what made the
    button feel dead and invited a second click - and on signup specifically,
    that second click landed the request AFTER the first one had already
    gone through, so it hit the UNIQUE email constraint and showed "account
    already exists" for an account that had, in fact, just been created
    successfully. Backgrounding the send fixes both: the page responds
    almost instantly, and email delivery (or a real failure, logged to the
    server console) happens off the critical path. Fails silently from the
    caller's perspective by design — a booking or signup should never be
    blocked just because an email didn't go out."""
    threading.Thread(
        target=_send_email_background,
        args=(to_email, subject, html_body),
        daemon=True,
    ).start()
    return True


def email_wrapper(inner_html):
    """Wraps any email's body content in the shared FADEDFORLESS look: solid
    black background top to bottom, gold hairline accents, the crest logo
    front and center."""
    return f"""
    <div style="background:#000000; padding:40px 16px;">
        <div style="max-width:480px; margin:0 auto; background:#0d0d0d; border:1px solid #D4AF37; border-radius:14px; overflow:hidden; font-family:Arial, Helvetica, sans-serif; box-shadow:0 0 0 1px rgba(212,175,55,0.15);">
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


# Only two prices exist on this site, so this is enough to recover a
# duration for the .ics file from the stored price string alone (the
# appointments table doesn't keep the original SERVICES key).
PRICE_TO_DURATION_MINUTES = {"$10": 30, "$15": 60}


def build_ics_bytes(summary, appt_date_iso, appt_time, price, description=""):
    """One VEVENT .ics file for a single appointment — works with Google
    Calendar, Apple Calendar, and Outlook alike. Building this is just
    string formatting (no network call, no extra dependency), so it's
    effectively free performance-wise."""
    start_dt = datetime.strptime(f"{appt_date_iso} {appt_time}", "%Y-%m-%d %I:%M %p")
    duration = PRICE_TO_DURATION_MINUTES.get(price, 45)
    end_dt = start_dt + timedelta(minutes=duration)
    uid = f"{appt_date_iso}-{appt_time}-{random.randint(1000,9999)}@fadedforless".replace(" ", "")
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")

    def esc(text):
        return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//FADEDFORLESS//Booking//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"SUMMARY:{esc(summary)}\r\n"
        f"DESCRIPTION:{esc(description)}\r\n"
        "LOCATION:FADEDFORLESS Barbershop\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return ics.encode("utf-8")


def notify_signup(name, email, referral_applied=False):
    referral_note = (
        "<p style=\"color:#F1D98B;\"><strong>You've also got $10 in credit</strong> from your "
        "referral code - it'll show up on the Rewards tab and can be applied at booking.</p>"
        if referral_applied else ""
    )
    send_email(
        email,
        "Welcome to FADEDFORLESS",
        email_wrapper(
            f"<p>Hey {name},</p>"
            "<p>Your account is set up. You can now book appointments, reschedule, "
            "and get style recommendations any time.</p>"
            f"{referral_note}"
            "<p style=\"font-size:13px; color:#b8b3a8;\">Tip: if this email landed in your "
            "Spam/Junk folder, mark it \"Not Spam\" (or add faded.for.less@gmail.com to your "
            "contacts) so your booking confirmations and reminders show up in your inbox.</p>"
            "<p>- FADEDFORLESS</p>"
        ),
    )
    send_email(
        OWNER_EMAIL,
        f"New account created - {name}",
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
        f"New booking - {name} - {details}",
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
        f"Appointment cancelled - {name} - {details}",
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
        f"Appointment rescheduled - {name} - {new_details}",
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

BASE_PAGES = ["Home", "About Me", "Pricing", "What You Get", "Book Now"]
IS_ADMIN = bool(st.session_state.user and st.session_state.user.get("is_admin"))
IS_CUSTOMER = bool(st.session_state.user and not IS_ADMIN)
AUTH_PAGES = [] if st.session_state.user else ["Log In"]
VALID_PAGES = (
    BASE_PAGES
    + AUTH_PAGES
    + (["Your Appointments", "Customers", "Style", "Settings"] if IS_ADMIN else [])
    + (["Style", "Rewards", "Settings"] if IS_CUSTOMER else [])
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
        font-size:clamp(2.1rem, 9vw, 5rem);
        line-height:1.02;
        font-weight:800;
        margin:0 0 20px 0;
        max-width:800px;
        white-space:nowrap;
    }
    .hero-title .title-break{ display:none; }
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
    /* The "One service..." / "The full service..." note at the bottom of
       each pricing card was the same gold color on both, making the two
       cards blend together. Give the $10 card a cooler silver tag and
       keep the $15 (featured) card's tag gold, so they read as visually
       distinct at a glance — the Book buttons below are untouched. */
    .price-card .price-line .gold-tag{
        background:linear-gradient(120deg, #d7dade, #9aa1a8);
        color:#0a0a0a !important;
    }
    .price-card.featured .price-line .gold-tag{
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:var(--premium-black) !important;
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

    /* ---------- CLICK-TO-ENLARGE LIGHTBOX (Craft section images) ---------- */
    .craft-item{
        display:contents;
    }
    .lb-toggle{
        position:absolute;
        opacity:0;
        pointer-events:none;
        width:0; height:0;
    }
    label.style-card{
        display:block;
        cursor:zoom-in;
    }
    .lb-overlay{
        display:none;
        position:fixed;
        inset:0;
        z-index:9999;
        background:rgba(5,5,5,0.94);
        align-items:center;
        justify-content:center;
        cursor:zoom-out;
        padding:40px;
    }
    .lb-overlay img{
        max-width:min(90vw, 900px);
        max-height:88vh;
        object-fit:contain;
        border:2px solid var(--gold);
        border-radius:10px;
        box-shadow:0 20px 60px rgba(0,0,0,0.6);
    }
    .lb-close{
        position:fixed;
        top:18px; right:24px;
        width:42px; height:42px;
        border-radius:50%;
        background:rgba(255,255,255,0.08);
        border:1px solid rgba(212,175,55,0.5);
        color:#F5F1E6;
        font-size:1.6rem;
        line-height:40px;
        text-align:center;
        cursor:pointer;
    }
    /* Scoped to each .craft-item so opening one card never lights up another
       card's overlay — the general-sibling selector only ever sees siblings
       within the same (display:contents) wrapper. */
    .craft-item .lb-toggle:checked ~ .lb-overlay{
        display:flex;
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

    /* ---------- BOOKING PANEL (Book Now page redesign) ---------- */
    /* Wraps the whole "Book an Appointment" form in the same dark card
       treatment used elsewhere on the site (see .stForm), so it reads as
       one cohesive panel instead of loose widgets floating on the page.
       Pure CSS on an existing st.container(key=...) — no extra widgets,
       no performance cost. */
    .st-key-booking_widget{
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.22);
        border-radius:12px;
        padding:30px 30px 26px 30px;
        margin-bottom:26px;
    }
    .st-key-customer_header{
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.18);
        border-radius:12px;
        padding:18px 24px;
        margin-bottom:22px;
    }
    /* Step labels that break the booking form into clear, ordered sections
       (Service / Date & Time / Notes) instead of one long stack of
       widgets. */
    .booking-step-label{
        display:flex;
        align-items:center;
        gap:10px;
        margin:26px 0 14px 0;
        text-transform:uppercase;
        letter-spacing:1.5px;
        font-size:0.78rem;
        font-weight:700;
        color:var(--gold-light);
    }
    .booking-step-label:first-child{ margin-top:0; }
    .booking-step-label .step-num{
        display:inline-flex;
        align-items:center;
        justify-content:center;
        width:22px; height:22px;
        border-radius:50%;
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:var(--premium-black);
        font-size:0.72rem;
        font-weight:800;
        flex-shrink:0;
    }
    /* Visual, tappable service cards replacing the plain dropdown. Reuses
       the same base64 images already loaded for the Pricing page, so
       there's no extra network/image cost. */
    .service-card{
        background:var(--charcoal-3);
        border:1px solid rgba(212,175,55,0.2);
        border-radius:10px;
        overflow:hidden;
        transition:border-color 0.2s ease, box-shadow 0.2s ease;
        margin-bottom:8px;
    }
    .service-card.selected{
        border:1px solid var(--gold);
        box-shadow:0 0 0 1px rgba(212,175,55,0.25);
    }
    .service-card-img{
        height:86px;
        background-size:cover;
        background-position:center;
    }
    .service-card-body{ padding:12px 14px 14px 14px; position:relative; }
    .service-card-name{ color:#F5F1E6; font-weight:700; font-size:0.92rem; }
    .service-card-price{ color:var(--gold); font-weight:800; font-size:1.15rem; margin:2px 0 6px 0; }
    .service-card-check{
        position:absolute;
        top:10px; right:12px;
        color:var(--gold);
        font-size:1rem;
    }
    .slots-caption{
        color:#847f72;
        font-size:0.8rem;
        margin-top:6px;
    }
    /* Live summary of the current selection, shown just above the Confirm
       button so there's no doubt what's about to be booked. */
    .booking-summary{
        background:var(--charcoal-3);
        border-left:3px solid var(--gold);
        border-radius:6px;
        padding:14px 18px;
        margin:22px 0 18px 0;
    }
    .booking-summary-label{
        text-transform:uppercase;
        letter-spacing:1px;
        font-size:0.68rem;
        color:#847f72;
        margin-bottom:4px;
    }
    .booking-summary-line{ color:#F5F1E6; font-weight:700; font-size:0.98rem; }
    .appt-group-label{
        text-transform:uppercase;
        letter-spacing:1.5px;
        font-size:0.78rem;
        font-weight:700;
        color:var(--gold);
        margin:22px 0 12px 0;
    }
    .appt-group-label:first-of-type{ margin-top:0; }

    /* ---------- REWARDS (loyalty punch card + referral program) ---------- */
    .rewards-card{
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.22);
        border-radius:12px;
        padding:26px 28px;
        margin-bottom:22px;
    }
    .rewards-card-title{
        font-family:'Playfair Display', serif;
        font-size:1.35rem;
        color:#F5F1E6;
        margin-bottom:4px;
    }
    .rewards-card-sub{ color:#847f72; font-size:0.9rem; margin-bottom:18px; }
    .punch-row{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
    .punch{
        width:44px; height:44px;
        border-radius:50%;
        display:flex; align-items:center; justify-content:center;
        font-size:1.1rem;
        border:1.5px dashed rgba(212,175,55,0.4);
        color:#4a463d;
        flex-shrink:0;
    }
    .punch.filled{
        border:1.5px solid var(--gold);
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:var(--premium-black);
        font-weight:800;
    }
    .reward-banner{
        background:linear-gradient(120deg, rgba(212,175,55,0.18), rgba(212,175,55,0.05));
        border:1px solid rgba(212,175,55,0.5);
        border-radius:8px;
        padding:14px 18px;
        color:var(--gold-light);
        font-weight:700;
        margin-top:8px;
    }
    .referral-code-box{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:14px;
        background:var(--charcoal-3);
        border:1px dashed rgba(212,175,55,0.45);
        border-radius:8px;
        padding:16px 20px;
        margin:6px 0 16px 0;
        flex-wrap:wrap;
    }
    .referral-code{
        font-family:'Playfair Display', serif;
        font-size:1.5rem;
        letter-spacing:3px;
        color:var(--gold-light);
        font-weight:700;
    }
    .credit-balance-line{
        font-size:1.6rem;
        font-weight:800;
        color:var(--gold);
        font-family:'Playfair Display', serif;
    }

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

    /* "☰ Menu" toggle button — a normal nav-style button (inherits the
       .st-key-site_navbar .stButton styling above), hidden on desktop where
       every page link already shows inline. Only appears at phone widths. */
    .st-key-mobile_menu_toggle_wrap{ display:none; }

    /* ---------- RESPONSIVE ---------- */
    @media (max-width: 900px){
        .hero-title .title-break{ display:block; }
        .about-wrap{ grid-template-columns:1fr; gap:36px; }
        .price-grid{ grid-template-columns:1fr; }
        .strip{ grid-template-columns:1fr; }

        /* On desktop the CTA row is deliberately pulled up (negative
           margin) so it overlaps the bottom of the hero image. On phone
           the hero is shorter, so that same overlap dragged the row up
           into the hero's border-bottom line — the gold hairline was
           cutting straight through "View Pricing". Let it sit naturally
           below the hero instead. */
        .st-key-hero_cta{
            margin-top:28px !important;
        }

        /* Show the hamburger toggle only on phone-width screens, and let
           the logo / toggle / account badge wrap onto their own line if
           they don't all fit side by side. */
        .st-key-nav_top_row [data-testid="stHorizontalBlock"]{
            flex-wrap:wrap !important;
            row-gap:8px;
        }
        .st-key-mobile_menu_toggle_wrap{
            display:block !important;
        }
        .st-key-mobile_menu_toggle_wrap .stButton>button{
            font-size:0.7rem !important;
            padding:8px 14px !important;
            white-space:nowrap !important;
        }

        /* Page links collapse into a "Menu" dropdown: hidden entirely until
           the hamburger toggle is pressed, then stacked vertically below
           the logo/menu-button row. */
        .st-key-nav_links_closed{ display:none !important; }
        .st-key-nav_links_open{
            display:block !important;
            margin-top:10px;
            padding-top:10px;
            border-top:1px solid rgba(212,175,55,0.2);
        }
        .st-key-nav_links_open [data-testid="stHorizontalBlock"]{
            flex-direction:column !important;
            flex-wrap:nowrap !important;
            gap:6px !important;
        }
        .st-key-nav_links_open [data-testid="stColumn"],
        .st-key-nav_links_open [data-testid="column"]{
            width:100% !important;
            flex:1 1 100% !important;
            min-width:0 !important;
        }
        .st-key-nav_links_open .stButton{ width:100% !important; }
        .st-key-nav_links_open .stButton>button{
            width:100% !important;
            text-align:left !important;
            justify-content:flex-start !important;
            font-size:0.85rem !important;
            padding:12px 16px !important;
        }
        .section{ padding:60px 20px; }
        .pillars{ grid-template-columns:1fr; }

        .wyg-step{ flex-direction:column !important; }
        .wyg-step-img{ width:100% !important; height:180px; }
        .wyg-step-body{ padding:18px 22px 22px 22px; }
        .cut-picker-options{ flex-direction:column !important; }
        .splash-title{ font-size:2.1rem !important; }
        .splash-tagline{ font-size:0.95rem !important; }
    }

    /* ---------- CAMERA (un-mirrored preview) ----------
       st.camera_input mirrors its live preview by default (like a selfie
       cam), which is confusing when lining up a fade or checking a part —
       what you see should match what actually gets captured. Force the
       live <video> feed to display un-mirrored. */
    div[data-testid="stCameraInput"] video{
        transform:scaleX(1) !important;
    }
    div[data-testid="stCameraInputWebcamComponent"] video{
        transform:scaleX(1) !important;
    }

    /* ---------- INTRO / SPLASH SCREEN ---------- */
    .splash-screen{
        position:fixed;
        inset:0;
        z-index:99999;
        background:var(--black);
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        text-align:center;
        animation:splashFadeOut 0.6s ease forwards;
        animation-delay:2.1s;
    }
    .splash-title{
        font-family:'Playfair Display', serif;
        font-weight:800;
        font-size:3.2rem;
        letter-spacing:3px;
        color:#F5F1E6;
        opacity:0;
        animation:splashRise 0.7s ease forwards;
        animation-delay:0.15s;
    }
    .splash-title span{ color:var(--gold); }
    .splash-tagline{
        margin-top:14px;
        font-size:1.05rem;
        font-weight:600;
        letter-spacing:2px;
        text-transform:uppercase;
        color:var(--gold-light);
        opacity:0;
        animation:splashRise 0.7s ease forwards;
        animation-delay:0.85s;
    }
    @keyframes splashRise{
        from{ opacity:0; transform:translateY(14px); }
        to{ opacity:1; transform:translateY(0); }
    }
    @keyframes splashFadeOut{
        from{ opacity:1; visibility:visible; }
        to{ opacity:0; visibility:hidden; pointer-events:none; }
    }

    /* ---------- FLOATING "BOOK A CUT" BUTTON (mobile-first, sticky) ---------- */
    .st-key-floating_book_cta{
        position:fixed;
        left:50%;
        bottom:18px;
        transform:translateX(-50%);
        z-index:9998;
        width:auto;
    }
    .st-key-floating_book_cta .stButton > button{
        padding:12px 26px !important;
        border-radius:30px !important;
        font-size:0.78rem !important;
        letter-spacing:1.5px !important;
        box-shadow:0 10px 26px rgba(212,175,55,0.45) !important;
        white-space:nowrap;
    }

    /* ---------- WHAT YOU GET (image step cards, scroll reveal) ---------- */
    .wyg-steps{
        display:flex;
        flex-direction:column;
        gap:26px;
        max-width:760px;
        margin:0 auto;
    }
    .wyg-step{
        display:flex;
        align-items:stretch;
        gap:0;
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.22);
        border-radius:14px;
        overflow:hidden;
        opacity:0;
        transform:translateY(30px);
        transition:opacity 0.6s ease, transform 0.6s ease;
    }
    .wyg-step.visible{
        opacity:1;
        transform:translateY(0);
    }
    .wyg-step-img{
        width:170px;
        flex-shrink:0;
        background-size:cover;
        background-position:center;
    }
    .wyg-step-body{
        padding:20px 26px;
        display:flex;
        flex-direction:column;
        justify-content:center;
    }
    .wyg-step-num{
        font-size:0.72rem;
        letter-spacing:2px;
        text-transform:uppercase;
        color:var(--gold);
        font-weight:700;
        margin-bottom:6px;
    }
    .wyg-step-title{
        font-family:'Playfair Display', serif;
        font-size:1.5rem;
        color:#F5F1E6;
        margin-bottom:6px;
    }
    .wyg-step-title .check{ color:var(--gold); margin-left:8px; }
    .wyg-step-desc{ font-size:0.95rem; margin:0; }

    /* ---------- CHOOSE YOUR CUT (interactive picker) ---------- */
    .cut-picker-wrap{
        max-width:760px;
        margin:50px auto 0 auto;
        background:linear-gradient(180deg, var(--charcoal-2), var(--charcoal));
        border:1px solid rgba(212,175,55,0.25);
        border-radius:14px;
        padding:36px 32px;
    }
    .cut-picker-head{ text-align:center; margin-bottom:22px; }
    .cut-picker-head h3{ font-size:1.5rem; margin:0 0 6px 0; }
    .st-key-cut_picker_radio .stRadio > div{
        display:flex;
        gap:12px;
        flex-wrap:wrap;
        justify-content:center;
    }
    .st-key-cut_picker_radio label{
        background:var(--charcoal-3);
        border:1px solid rgba(212,175,55,0.3);
        border-radius:30px;
        padding:10px 22px !important;
        margin:0 !important;
    }
    .cut-result{
        margin-top:26px;
        text-align:center;
        padding:22px;
        border-top:1px solid rgba(212,175,55,0.2);
    }
    .cut-result-price{
        font-family:'Playfair Display', serif;
        font-size:2.4rem;
        font-weight:700;
        color:#F7F3E7;
    }
    .cut-result-meta{ margin:10px 0 16px 0; }

    /* ---------- VISUAL POLISH ---------- */
    /* Subtle film-grain texture over the whole page - a tiny tiled SVG
       noise pattern at very low opacity with mix-blend-mode so text stays
       perfectly readable. Pure CSS, no image download (it's an inline SVG
       data URI), so this costs nothing extra to load or render. */
    [data-testid="stAppViewContainer"]::before{
        content:"";
        position:fixed;
        inset:0;
        z-index:9999;
        pointer-events:none;
        opacity:0.035;
        mix-blend-mode:overlay;
        background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    }

    /* Thin gold scrollbar instead of the default browser one. */
    ::-webkit-scrollbar{ width:10px; height:10px; }
    ::-webkit-scrollbar-track{ background:var(--black); }
    ::-webkit-scrollbar-thumb{
        background:linear-gradient(180deg, var(--gold-light), var(--gold));
        border-radius:10px;
        border:2px solid var(--black);
    }
    html{ scrollbar-color:var(--gold) var(--black); scrollbar-width:thin; }

    /* Ornamental gold flourish in the middle of every section divider
       site-wide, instead of a plain line - a single shared rule, so every
       page that already uses .divider picks this up automatically. */
    .divider{ position:relative; overflow:visible; }
    .divider::after{
        content:"◆";
        position:absolute;
        top:50%; left:50%;
        transform:translate(-50%, -50%);
        background:var(--black);
        color:var(--gold);
        font-size:0.7rem;
        padding:0 10px;
    }

    /* Gold-foil hover glow + gentle 3D tilt, added to every card style
       already on the site (price cards, style showcase, feature pillars,
       service picker) - just enhancing existing :hover rules, no new
       markup or elements needed. */
    .price-card:hover, .service-card:hover, .pillar:hover{
        transform:perspective(800px) rotateX(1.5deg) translateY(-6px);
        box-shadow:0 22px 45px rgba(0,0,0,0.45), 0 0 24px rgba(212,175,55,0.18);
    }
    .style-card:hover{
        transform:perspective(800px) rotateX(1.5deg) scale(1.02);
        box-shadow:0 18px 40px rgba(212,175,55,0.22);
    }
    .service-card{ transition:transform 0.25s ease, box-shadow 0.25s ease, border-color 0.2s ease; }

    /* Generic scroll-reveal: any element with class="reveal" starts faded
       down and rises into place the first time it scrolls into view (see
       the shared inject_scroll_reveal() JS below). Same mechanism already
       used for the "What You Get" step cards, just made reusable. */
    .reveal{
        opacity:0;
        transform:translateY(28px);
        transition:opacity 0.6s ease, transform 0.6s ease;
    }
    .reveal.visible{ opacity:1; transform:translateY(0); }
    </style>
    """.replace("__IMG_HERO__", IMG_HERO)
)

# ----------------------------------------------------------------------------
# INTRO / SPLASH SCREEN
# ----------------------------------------------------------------------------
# Shown once per browser session (not on every rerun/click) — briefly
# flashes the wordmark + tagline, then fades away on its own via CSS so the
# rest of the site can render underneath it the whole time.
if "splash_shown" not in st.session_state:
    st.session_state.splash_shown = True
    raw_html(
        """
        <div class="splash-screen">
            <div class="splash-title">FADED<span>FOR</span>LESS</div>
            <div class="splash-tagline">Cuts without the crazy price.</div>
        </div>
        """
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
    st.session_state.mobile_menu_open = False


def go_to_service(page_name, service_key):
    """Used by the clickable pricing cards — jumps to Book Now and
    pre-selects the exact service that was pressed."""
    st.session_state.preselect_service = service_key
    st.query_params["page"] = page_name
    st.session_state.mobile_menu_open = False


def set_booking_service(service_key):
    """Used by the visual service cards on the Book Now page itself."""
    st.session_state.booking_service_choice = service_key


def toggle_mobile_menu():
    st.session_state.mobile_menu_open = not st.session_state.mobile_menu_open


if "mobile_menu_open" not in st.session_state:
    st.session_state.mobile_menu_open = False

with st.container(key="site_navbar"):
    # Top row: logo, a "☰ Menu" toggle (only ever visible on phone-width
    # screens — plain CSS hides it on desktop), and the account badge.
    with st.container(key="nav_top_row"):
        top_cols = st.columns(
            [1.6, 0.5, 1.3 if st.session_state.user else 0.001],
            vertical_alignment="center",
        )

        with top_cols[0]:
            raw_html(logo_html(42))

        with top_cols[1]:
            with st.container(key="mobile_menu_toggle_wrap"):
                st.button(
                    "✕ Close" if st.session_state.mobile_menu_open else "☰ Menu",
                    key="mobile_menu_toggle",
                    on_click=toggle_mobile_menu,
                    use_container_width=True,
                )

        if st.session_state.user:
            with top_cols[2]:
                first_name = st.session_state.user["name"].split(" ")[0]
                raw_html(f'<div class="nav-account">Hi, {first_name}</div>')

    # Page links. On desktop these render inline right below the row above
    # (CSS makes the two rows look seamless, like one navbar). On phone-width
    # screens they're hidden entirely unless the "☰ Menu" toggle above was
    # pressed, in which case they stack into a vertical dropdown.
    n_pages = len(VALID_PAGES)
    links_key = "nav_links_open" if st.session_state.mobile_menu_open else "nav_links_closed"
    NAV_LABELS = {"Your Appointments": "Your Appts", "Style": "AI Consult"}
    with st.container(key=links_key):
        link_cols = st.columns([1] * n_pages, vertical_alignment="center")
        for i, page_name in enumerate(VALID_PAGES):
            with link_cols[i]:
                is_active = current_page == page_name
                st.button(
                    NAV_LABELS.get(page_name, page_name),
                    key=f"navbtn_{page_name}",
                    on_click=go_to,
                    args=(page_name,),
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                )

# ----------------------------------------------------------------------------
# FLOATING "BOOK A CUT" BUTTON
# ----------------------------------------------------------------------------
# Small gold pill fixed near the bottom of the screen, visible while
# scrolling on any device (styled small/sticky for phone in the CSS above).
# Hidden on the Book Now page itself, since it's redundant there.
if current_page != "Book Now":
    with st.container(key="floating_book_cta"):
        st.button("Book a Cut", key="floating_book_cta_btn", type="primary", on_click=go_to, args=("Book Now",))

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
                <h1 class="hero-title">FADED<span class="gold-grad">FOR</span><br class="title-break">LESS</h1>
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
        <div class="craft-item">
            <input type="checkbox" id="lb-craft-{i}" class="lb-toggle" />
            <label for="lb-craft-{i}" class="style-card reveal">
                <img src="{s['img']}" />
                <div class="style-label">
                    <span class="tag">{s['tag']}</span>
                    <span class="name">{s['name']}</span>
                </div>
            </label>
            <label for="lb-craft-{i}" class="lb-overlay">
                <span class="lb-close">&times;</span>
                <img src="{s['img']}" />
            </label>
        </div>
        """
        for i, s in enumerate(STYLE_SHOWCASE)
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
                        experience, with sharp lines, clean fades, and genuine attention to detail. No
                        rushed appointments, no inflated prices for a basic service.
                    </p>
                    <p>
                        Don't let my age fool you. I've been cutting hair for 4 years and I'm
                        always working to get better. If you're not sure yet, check out
                        <a href="{INSTAGRAM_URL}" target="_blank" class="gold">@fadedforless on Instagram</a>
                        and see the work for yourself.
                    </p>
                    <div class="pillars">
                        <div class="pillar reveal"><b>17, Growing Fast</b><br/>4 years of real experience so far</div>
                        <div class="pillar reveal"><b>Affordable</b><br/>Pricing that respects your wallet</div>
                        <div class="pillar reveal"><b>Precise</b><br/>Clean lines and sharp fades</div>
                        <div class="pillar reveal"><b>Premium Feel</b><br/>A pro experience, fair price</div>
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
                    <div class="price-card reveal">
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
                    <div class="price-card featured reveal">
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

    # ---------- CHOOSE YOUR CUT (interactive, sits under the two cards above) ----------
    raw_html(
        """
        <div class="cut-picker-wrap">
            <div class="cut-picker-head">
                <div class="eyebrow" style="justify-content:center;">Not Sure Yet?</div>
                <h3>Choose Your Cut</h3>
                <p class="section-sub" style="margin:0 auto;">Pick what you want done and see the price, time, and what's included.</p>
            </div>
        </div>
        """
    )

    CUT_OPTIONS = {
        "Fade": {
            "service_key": "Fade or Trim - $10 (30 min)",
            "price": "$10",
            "time": "30 min",
            "includes": ["Clean, blended fade"],
        },
        "Trim": {
            "service_key": "Fade or Trim - $10 (30 min)",
            "price": "$10",
            "time": "30 min",
            "includes": ["Neat, tidy trim"],
        },
        "Full Haircut": {
            "service_key": "Full Haircut - $15 (1 hour)",
            "price": "$15",
            "time": "1 hour",
            "includes": ["Fade", "Trim", "Cleanup", "Finished look"],
        },
    }

    outer_l2, outer_mid2, outer_r2 = st.columns([1, 5.4, 1])
    with outer_mid2:
        with st.container(key="cut_picker_radio"):
            choice = st.radio(
                "Choose your cut",
                list(CUT_OPTIONS.keys()),
                key="cut_picker_choice",
                horizontal=True,
                label_visibility="collapsed",
            )
        picked = CUT_OPTIONS[choice]
        chips = "".join(f'<span class="chip">{item}</span>' for item in picked["includes"])
        raw_html(
            f"""
            <div class="cut-result">
                <div class="cut-result-price">{picked['price']}</div>
                <div class="cut-result-meta"><span class="chip">{picked['time']}</span></div>
                <div class="price-meta" style="justify-content:center;">{chips}</div>
            </div>
            """
        )
        st.button(
            f"Book {choice} - {picked['price']} →",
            key="cut_picker_book_btn",
            type="primary",
            use_container_width=True,
            on_click=go_to_service,
            args=("Book Now", picked["service_key"]),
        )

    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# WHAT YOU GET PAGE
# ----------------------------------------------------------------------------
def render_what_you_get():
    raw_html(
        """
        <div class="section" style="padding-bottom:10px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">What You Get</div>
                <h2 class="section-title">The $15 Full Haircut, step by step</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
                <p class="section-sub" style="margin:14px auto 0 auto;">
                    Scroll down to see exactly what's included in every full haircut -
                    no shortcuts, no upsells.
                </p>
            </div>
        </div>
        """
    )

    WYG_STEPS = [
        {
            "num": "Step 1",
            "title": "Fade",
            "img": STYLE_SHOWCASE[0]["img"],
            "desc": "A clean, blended fade built around your hair type and face shape - "
                    "low, mid, or high, whatever suits you best.",
        },
        {
            "num": "Step 2",
            "title": "Trim",
            "img": IMG_STRIP_2,
            "desc": "The top gets shaped and trimmed to length, keeping everything even "
                    "and blending seamlessly into the fade underneath.",
        },
        {
            "num": "Step 3",
            "title": "Cleanup",
            "img": STYLE_SHOWCASE[3]["img"],
            "desc": "Sharp lineup around the edges, neckline, and hairline for that fresh, "
                    "just-left-the-shop look.",
        },
        {
            "num": "Step 4",
            "title": "Finished",
            "img": IMG_PRICE_15,
            "desc": "A complete, polished cut - checked over and touched up before you "
                    "leave the chair.",
        },
    ]

    steps_html = "".join(
        f"""
        <div class="wyg-step">
            <div class="wyg-step-img" style="background-image:url('{s['img']}');"></div>
            <div class="wyg-step-body">
                <div class="wyg-step-num">{s['num']}</div>
                <div class="wyg-step-title">{s['title']} <span class="check">✓</span></div>
                <p class="wyg-step-desc">{s['desc']}</p>
            </div>
        </div>
        """
        for s in WYG_STEPS
    )
    raw_html(
        f"""
        <div class="section section-tight" style="padding-top:10px;">
            <div class="wyg-steps">
                {steps_html}
            </div>
        </div>
        """
    )

    # Scroll-triggered reveal: this small iframe's JS reaches out to the
    # *parent* document (same-origin, so this is safe) and watches each
    # .wyg-step card individually with an IntersectionObserver, so each one
    # fades in right as the user scrolls to it - not all at once.
    components.html(
        """
        <script>
        (function() {
            const doc = window.parent.document;
            const steps = Array.from(doc.querySelectorAll('.wyg-step'));
            if (!steps.length || steps[0].dataset.wygBound) return;
            steps.forEach(el => { el.dataset.wygBound = "1"; });

            const observer = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('visible');
                        observer.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.25, root: null, rootMargin: "0px 0px -60px 0px" });

            steps.forEach(el => observer.observe(el));
        })();
        </script>
        """,
        height=0,
    )

    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)

    with st.container(key="wyg_cta"):
        c1, c2, _sp = st.columns([1, 1, 3])
        with c1:
            st.button("Book the $15 Cut", key="wyg_book_now", type="primary", on_click=go_to, args=("Book Now",))
        with c2:
            st.button("See Full Pricing", key="wyg_view_pricing", on_click=go_to, args=("Pricing",))

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)


def render_login():
    if st.session_state.user:
        st.success("You're already logged in.")
        return

    raw_html(
        """
        <div class="section" style="padding-bottom:20px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">Account</div>
                <h2 class="section-title">Log In or Sign Up</h2>
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
                            with st.spinner("Logging in..."):
                                user = verify_login(email, password)
                            if user:
                                user["is_admin"] = False
                                st.session_state.user = user
                                st.success(f"Welcome back, {user['name']}!")
                                st.query_params["page"] = "Book Now"
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
                    referral_input = st.text_input(
                        "Referral Code (optional)",
                        placeholder="Got a code from a friend? You'll both get $10 credit",
                        key="signup_referral",
                    )
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
                            with st.spinner("Creating your account..."):
                                ok, msg = create_user(name, email, phone, password, referral_input)
                            if ok:
                                user = verify_login(email, password)
                                user["is_admin"] = False
                                st.session_state.user = user
                                st.success(
                                    "Account created! You're now signed in. "
                                    "Check your inbox for a welcome email - if it's not there, "
                                    "look in Spam/Junk and mark it 'Not Spam' so future booking "
                                    "confirmations land in your inbox."
                                )
                                st.query_params["page"] = "Book Now"
                                st.rerun()
                            else:
                                st.error(msg)

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)


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
            raw_html(
                """
                <div class="appt-card" style="flex-direction:column; align-items:center; text-align:center; gap:6px; padding:36px 24px;">
                    <div class="appt-service">You'll need an account to book</div>
                    <p style="margin:6px 0 4px 0; color:#847f72;">
                        It's free and only takes a minute — it also keeps your appointment
                        history in one place and makes rebooking quick.
                    </p>
                </div>
                """
            )
            st.button(
                "Log In / Sign Up →",
                key="book_now_go_login",
                type="primary",
                use_container_width=True,
                on_click=go_to,
                args=("Log In",),
            )

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

            # Not wrapped in st.form on purpose: the Time dropdown needs to
            # refresh the moment the Date changes, so it only ever offers
            # slots nobody else has already taken that day.
            with st.container(key="booking_widget"):
                raw_html('<div class="booking-step-label"><span class="step-num">1</span>Choose Your Service</div>')

                # Visual service cards (image + price + duration) instead of
                # a plain dropdown. Reuses the Pricing page's already-cached
                # images, so this costs nothing extra to load.
                SERVICE_CARDS = [
                    ("Fade or Trim - $10 (30 min)", IMG_PRICE_10, "$10", "30 min"),
                    ("Full Haircut - $15 (1 hour)", IMG_PRICE_15, "$15", "1 hour"),
                ]
                preselected = st.session_state.pop("preselect_service", None)
                if "booking_service_choice" not in st.session_state or preselected:
                    st.session_state.booking_service_choice = preselected or SERVICE_CARDS[0][0]
                service_key = st.session_state.booking_service_choice

                card_cols = st.columns(2)
                for (skey, simg, sprice, sdur), scol in zip(SERVICE_CARDS, card_cols):
                    selected = skey == service_key
                    with scol:
                        raw_html(
                            f"""
                            <div class="service-card{' selected' if selected else ''}">
                                <div class="service-card-img" style="background-image:url('{simg}');"></div>
                                <div class="service-card-body">
                                    {'<div class="service-card-check">✓</div>' if selected else ''}
                                    <div class="service-card-name">{SERVICES[skey]['label']}</div>
                                    <div class="service-card-price">{sprice}</div>
                                    <span class="chip">{sdur}</span>
                                </div>
                            </div>
                            """
                        )
                        st.button(
                            "Selected ✓" if selected else "Choose This",
                            key=f"pick_{skey}",
                            type="primary" if selected else "secondary",
                            use_container_width=True,
                            on_click=set_booking_service,
                            args=(skey,),
                        )

                raw_html('<div class="booking-step-label"><span class="step-num">2</span>Pick a Date &amp; Time</div>')
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
                    day_slots = time_slots_for_date(appt_date)
                    available_times = [t for t in day_slots if t not in booked_times]
                    if not day_slots:
                        appt_time = None
                        st.selectbox(
                            "Time",
                            ["Closed that day - pick another date"],
                            disabled=True,
                            key="booking_time_closed",
                        )
                    elif available_times:
                        appt_time = st.selectbox("Time", available_times, key="booking_time")
                    else:
                        appt_time = None
                        st.selectbox(
                            "Time",
                            ["Fully booked - pick another day"],
                            disabled=True,
                            key="booking_time_full",
                        )
                if day_slots:
                    raw_html(
                        f'<div class="slots-caption">{len(available_times)} of {len(day_slots)} slots open that day</div>'
                    )

                raw_html('<div class="booking-step-label"><span class="step-num">3</span>Anything We Should Know?</div>')
                notes = st.text_area("Notes (optional)", placeholder="Anything the barber should know", key="booking_notes", label_visibility="collapsed")

                credit_cents = get_credit_cents(user["id"]) if user["id"] else 0
                credit_to_apply = 0
                if credit_cents > 0 and service_key:
                    service_price_cents = SERVICE_PRICE_CENTS[service_key]
                    max_applicable = min(credit_cents, service_price_cents)
                    apply_credit = st.checkbox(
                        f"Apply my {format_cents(credit_cents)} referral credit to this booking",
                        key="apply_credit_checkbox",
                        value=True,
                    )
                    if apply_credit:
                        credit_to_apply = max_applicable

                if appt_time is not None:
                    pretty_selected_date = appt_date.strftime("%a, %b %d, %Y")
                    final_price_cents = max(0, SERVICE_PRICE_CENTS[service_key] - credit_to_apply)
                    price_line = (
                        f"<span style='text-decoration:line-through; color:#847f72; margin-right:6px;'>{SERVICES[service_key]['price']}</span>{format_cents(final_price_cents)}"
                        if credit_to_apply
                        else SERVICES[service_key]['price']
                    )
                    raw_html(
                        f"""
                        <div class="booking-summary">
                            <div class="booking-summary-label">You're About To Book</div>
                            <div class="booking-summary-line">{SERVICES[service_key]['label']} · {price_line} — {pretty_selected_date} at {appt_time}</div>
                        </div>
                        """
                    )

                if st.button("Confirm Appointment", key="booking_confirm_btn", type="primary", use_container_width=True):
                    if appt_time is None:
                        st.error("That day is fully booked - please choose another date.")
                    else:
                        with st.spinner("Booking your appointment..."):
                            ok, msg = create_appointment(
                                user["id"], service_key, appt_date, appt_time, notes or "",
                                credit_cents_to_apply=credit_to_apply,
                            )
                        if ok:
                            st.success("Appointment booked! See it below.")
                            st.rerun()
                        else:
                            st.error(msg)

            appts = get_appointments(user["id"])
            if not appts:
                raw_html('<div class="appt-group-label">Your Appointments</div>')
                st.markdown(
                    '<p style="color:#847f72;">No appointments yet - book your first one above.</p>',
                    unsafe_allow_html=True,
                )
            else:
                if "editing_appt_id" not in st.session_state:
                    st.session_state.editing_appt_id = None

                def render_appt_row(appt):
                    appt_id, service, price, appt_date_str, appt_time_str, appt_notes, status = appt
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
                            btn_a, btn_b, btn_c = st.columns(3)
                            with btn_a:
                                if st.button("Change Time", key=f"change_{appt_id}"):
                                    st.session_state.editing_appt_id = (
                                        None if st.session_state.editing_appt_id == appt_id else appt_id
                                    )
                                    st.rerun()
                            with btn_b:
                                if st.button("Cancel", key=f"cancel_{appt_id}"):
                                    with st.spinner("Cancelling..."):
                                        cancel_appointment(appt_id, user["id"])
                                    st.rerun()
                            with btn_c:
                                st.download_button(
                                    "📅 Add to Calendar",
                                    data=build_ics_bytes(
                                        f"{service} - FADEDFORLESS",
                                        appt_date_str,
                                        appt_time_str,
                                        price,
                                        description=f"Appointment notes: {appt_notes}" if appt_notes else "",
                                    ),
                                    file_name=f"fadedforless-{appt_date_str}-{appt_time_str.replace(':', '').replace(' ', '')}.ics",
                                    mime="text/calendar",
                                    key=f"ics_{appt_id}",
                                    use_container_width=True,
                                )

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
                                    available_times = [t for t in time_slots_for_date(new_date) if t not in booked_times]
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
                                        with st.spinner("Saving new time..."):
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

                # Split into Upcoming (confirmed, today or later) vs Past/Cancelled
                # so the list reads cleanly instead of one long undifferentiated
                # stack - purely a client-side split of data already fetched,
                # so it costs nothing extra.
                today_iso = date.today().isoformat()
                upcoming = [a for a in appts if a[3] >= today_iso and a[6] == "Confirmed"]
                past = [a for a in appts if not (a[3] >= today_iso and a[6] == "Confirmed")]

                raw_html('<div class="appt-group-label">Upcoming</div>')
                if upcoming:
                    for appt in upcoming:
                        render_appt_row(appt)
                else:
                    st.markdown(
                        '<p style="color:#847f72;">No upcoming appointments - book one above.</p>',
                        unsafe_allow_html=True,
                    )

                if past:
                    raw_html('<div class="appt-group-label">Past &amp; Cancelled</div>')
                    for appt in past:
                        render_appt_row(appt)

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# INSTAGRAM PAGE
# ----------------------------------------------------------------------------
def render_rewards():
    user = st.session_state.user
    if not user or user.get("is_admin"):
        st.warning("Log in with a customer account to see your Rewards.")
        return

    raw_html(
        """
        <div class="section" style="padding-bottom:20px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">Rewards</div>
                <h2 class="section-title">Your Loyalty &amp; Referrals</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
            </div>
        </div>
        """
    )

    left, mid, right = st.columns([1, 2.2, 1])
    with mid:
        # ---------- LOYALTY PUNCH CARD ----------
        completed, punches, free_earned = get_loyalty_progress(user["id"])
        punch_html = "".join(
            f'<div class="punch{" filled" if i < punches else ""}">{"✓" if i < punches else ""}</div>'
            for i in range(LOYALTY_CYCLE)
        )
        remaining = LOYALTY_CYCLE - punches if punches else LOYALTY_CYCLE
        if free_earned:
            plural = "s" if free_earned != 1 else ""
            progress_html = (
                f'<div class="reward-banner">🎉 You have {free_earned} free haircut{plural} earned '
                "- mention it next time you're in the chair!</div>"
            )
        else:
            plural = "s" if remaining != 1 else ""
            progress_html = (
                f'<div style="color:#847f72; font-size:0.88rem;">{remaining} more cut{plural} '
                "until your next free one.</div>"
            )
        raw_html(
            f"""
            <div class="rewards-card">
                <div class="rewards-card-title">Loyalty Punch Card</div>
                <div class="rewards-card-sub">Every {LOYALTY_CYCLE}th cut is on us. {completed} cut{'s' if completed != 1 else ''} completed so far.</div>
                <div class="punch-row">{punch_html}</div>
                {progress_html}
            </div>
            """
        )

        # ---------- REFERRAL PROGRAM ----------
        my_code = get_referral_code(user["id"]) or "—"
        credit_cents = get_credit_cents(user["id"])
        credit_hint = (
            '<p style="color:#847f72; font-size:0.85rem; margin-top:10px;">Credit is applied '
            "automatically as an option when you book - look for the checkbox on the Book Now page.</p>"
            if credit_cents else ""
        )
        raw_html(
            f"""
            <div class="rewards-card">
                <div class="rewards-card-title">Refer a Friend, Get $10</div>
                <div class="rewards-card-sub">Share your code — when a friend signs up with it, you BOTH get $10 in credit toward a cut.</div>
                <div class="referral-code-box">
                    <div class="referral-code">{my_code}</div>
                    <span class="chip">Share this at signup</span>
                </div>
                <div class="rewards-card-sub" style="margin-bottom:6px;">Your Available Credit</div>
                <div class="credit-balance-line">{format_cents(credit_cents)}</div>
                {credit_hint}
            </div>
            """
        )

    st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)


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
                    btn_a, btn_b, btn_c = st.columns(3)
                    with btn_a:
                        if st.button("Change Time", key=f"admin_change_{appt_id}"):
                            st.session_state.admin_editing_appt_id = (
                                None if st.session_state.admin_editing_appt_id == appt_id else appt_id
                            )
                            st.rerun()
                    with btn_b:
                        if st.button("Cancel", key=f"admin_cancel_{appt_id}"):
                            with st.spinner("Cancelling..."):
                                admin_cancel_appointment(appt_id)
                            st.rerun()
                    with btn_c:
                        st.download_button(
                            "📅 Add to Calendar",
                            data=build_ics_bytes(
                                f"{service} - {cust_name} - FADEDFORLESS",
                                appt_date_str,
                                appt_time_str,
                                price,
                                description=f"Customer: {cust_name} ({contact})" if contact else f"Customer: {cust_name}",
                            ),
                            file_name=f"fadedforless-{appt_date_str}-{appt_time_str.replace(':', '').replace(' ', '')}.ics",
                            mime="text/calendar",
                            key=f"admin_ics_{appt_id}",
                            use_container_width=True,
                        )

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
                            available_times = [t for t in time_slots_for_date(new_date) if t not in booked_times]
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
                                with st.spinner("Saving new time..."):
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

    if st.session_state.pop("avail_just_saved", False):
        st.success("Availability saved ✓")

    left, mid, right = st.columns([1, 2.2, 1])
    with mid:
        if user.get("is_admin"):
            st.markdown("#### Database Status")
            st.markdown(
                '<p style="color:#847f72; margin-top:-6px;">Confirms the app is actually '
                'saving to Turso — not just that the site loaded.</p>',
                unsafe_allow_html=True,
            )
            recheck_clicked = st.button("Re-check Connection", key="turso_recheck_btn")
            if recheck_clicked:
                st.session_state.pop("turso_status_cache", None)
            if "turso_status_cache" not in st.session_state:
                st.session_state.turso_status_cache = check_turso_status()
            turso_ok, turso_msg = st.session_state.turso_status_cache
            if turso_ok:
                st.success(f"✅ {turso_msg}")
            else:
                st.error(f"❌ {turso_msg}")

            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
            st.markdown("#### Availability")
            st.markdown(
                '<p style="color:#847f72; margin-top:-6px;">Set the hours customers are allowed '
                'to book or reschedule into — pick different hours for each day, or mark a day '
                'closed entirely.</p>',
                unsafe_allow_html=True,
            )
            day_inputs = {}
            for wd_key, wd_label in WEEKDAYS:
                cur_start, cur_end, cur_closed = get_day_hours(wd_key)
                with st.container(key=f"avail_row_{wd_key}"):
                    day_a, day_b, day_c = st.columns([1.1, 1.1, 0.8])
                    with day_a:
                        start_idx = FULL_DAY_SLOTS.index(cur_start) if cur_start in FULL_DAY_SLOTS else 0
                        d_start = st.selectbox(
                            f"{wd_label} opens",
                            FULL_DAY_SLOTS,
                            index=start_idx,
                            key=f"avail_{wd_key}_start_select",
                            disabled=cur_closed,
                        )
                    with day_b:
                        end_idx = (
                            FULL_DAY_SLOTS.index(cur_end) if cur_end in FULL_DAY_SLOTS else len(FULL_DAY_SLOTS) - 1
                        )
                        d_end = st.selectbox(
                            f"{wd_label} closes",
                            FULL_DAY_SLOTS,
                            index=end_idx,
                            key=f"avail_{wd_key}_end_select",
                            disabled=cur_closed,
                        )
                    with day_c:
                        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
                        d_closed = st.checkbox("Closed", value=cur_closed, key=f"avail_{wd_key}_closed_check")
                day_inputs[wd_key] = (d_start, d_end, d_closed)

            if st.button("Save Availability", key="avail_save_btn"):
                errors = []
                for wd_key, wd_label in WEEKDAYS:
                    d_start, d_end, d_closed = day_inputs[wd_key]
                    if not d_closed and datetime.strptime(d_end, "%I:%M %p") <= datetime.strptime(d_start, "%I:%M %p"):
                        errors.append(wd_label)
                if errors:
                    st.error(f"Closing time has to be after opening time for: {', '.join(errors)}.")
                else:
                    for wd_key, wd_label in WEEKDAYS:
                        d_start, d_end, d_closed = day_inputs[wd_key]
                        set_setting(f"avail_{wd_key}_start", d_start)
                        set_setting(f"avail_{wd_key}_end", d_end)
                        set_setting(f"avail_{wd_key}_closed", "1" if d_closed else "0")
                    st.session_state.avail_just_saved = True
                    st.rerun()

            st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)
            st.markdown("#### Email Notifications")
            if email_is_configured():
                st.markdown(
                    f'<p style="color:#847f72;">Sending as <strong style="color:#EDEAE2;">{GMAIL_ADDRESS}</strong> &middot; '
                    f'Owner alerts go to <strong style="color:#EDEAE2;">{OWNER_EMAIL}</strong></p>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<p style="color:#e06666;">Not configured — the GMAIL_APP_PASSWORD secret is missing or empty.</p>',
                    unsafe_allow_html=True,
                )
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
# STYLE PAGE — customers take one photo and get a haircut/fade recommendation
# (auto-shared with Freddie); the owner gets a separate 3-photo (back/side/
# top) cutting-plan tool. Both can keep chatting with the AI afterward.
# ----------------------------------------------------------------------------
def render_style_chat():
    """Shared AI-chat follow-up, shown under a recommendation for both
    customers and the owner — lets them keep asking Gemini questions about
    the cut without retaking photos."""
    if "style_chat_history" not in st.session_state or not st.session_state.style_chat_history:
        return

    st.markdown("<div style='height:22px;'></div>", unsafe_allow_html=True)
    st.markdown("**Keep talking about it**")
    for msg in st.session_state.style_chat_history[1:]:  # skip the initial photo turn
        if msg["role"] == "user":
            raw_html(
                f"""
                <div class="appt-card" style="background:rgba(212,175,55,0.08);">
                    <p style="margin:0; color:#EDEAE2;">{msg['text']}</p>
                </div>
                """
            )
        else:
            raw_html(
                f"""
                <div class="appt-card" style="flex-direction:column; align-items:flex-start;">
                    <p style="margin:0; color:#EDEAE2;">{msg['text']}</p>
                </div>
                """
            )

    with st.form("style_chat_form", clear_on_submit=True):
        follow_up = st.text_input("Ask a follow-up question", key="style_chat_input")
        sent = st.form_submit_button("Send")
    if sent and follow_up.strip():
        st.session_state.style_chat_history.append({"role": "user", "text": follow_up.strip()})
        with st.spinner("Thinking..."):
            ok, reply = style_chat_reply(st.session_state.style_chat_history)
        if ok:
            st.session_state.style_chat_history.append({"role": "model", "text": reply})
        else:
            st.error(reply)
            st.session_state.style_chat_history.pop()
        st.rerun()


def photo_input_widget(key_prefix, cam_label):
    """Lets the customer or owner either take a live photo or upload one
    already saved on their device. Returns (image_bytes, mime_type) or None
    if nothing has been captured/chosen yet."""
    mode = st.radio(
        "Photo source",
        ["Take Photo", "Upload Photo"],
        key=f"{key_prefix}_mode",
        horizontal=True,
        label_visibility="collapsed",
    )
    if mode == "Take Photo":
        photo = st.camera_input(cam_label, key=f"{key_prefix}_camera")
        if photo is not None:
            return photo.getvalue(), photo.type or "image/jpeg"
        return None
    else:
        uploaded = st.file_uploader(cam_label, type=["png", "jpg", "jpeg"], key=f"{key_prefix}_upload")
        if uploaded is not None:
            ext = uploaded.name.rsplit(".", 1)[-1].lower()
            mime = "image/png" if ext == "png" else "image/jpeg"
            return uploaded.getvalue(), mime
        return None


def render_style():
    user = st.session_state.user
    if not user:
        st.warning("Please log in to use Style AI.")
        return

    is_owner = bool(user.get("is_admin"))

    raw_html(
        f"""
        <div class="section" style="padding-bottom:10px;">
            <div class="booking-head">
                <div class="eyebrow" style="justify-content:center;">Virtual AI Consultation</div>
                <h2 class="section-title">{"Virtual AI Consultation — Owner Tool" if is_owner else "Your Virtual AI Consultation"}</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
                <p class="section-sub" style="margin:14px auto 0 auto;">
                    {"Upload three angles of a customer's head and get a precise cutting plan — top, fade or not, which fade, and whether it's sides only." if is_owner else "Snap a photo and get a fade and haircut recommendation before you sit in the chair."}
                </p>
            </div>
        </div>
        """
    )

    with st.container(key="style_photo_widget"):
        left, mid, right = st.columns([1, 3.4, 1])
        with mid:
            if is_owner:
                # Three separate st.camera_input widgets mounted on the page
                # at once was the actual bug some phones hit (only the last
                # one could ever get a live camera stream — the other two
                # stayed stuck on the "would like to use your camera" prompt
                # forever). Rendering exactly one camera_input at a time,
                # one step at a time, avoids that entirely.
                OWNER_STEPS = [
                    ("back", "Back", "Back of the head"),
                    ("side", "Side", "Side of the head"),
                    ("top", "Top / Front", "Top or front of the head"),
                ]
                if "owner_photo_step" not in st.session_state:
                    st.session_state.owner_photo_step = 0
                if "owner_photos" not in st.session_state:
                    st.session_state.owner_photos = {}

                step = st.session_state.owner_photo_step

                for i, (pkey, plabel, _) in enumerate(OWNER_STEPS[:step]):
                    data = st.session_state.owner_photos.get(pkey)
                    if data:
                        thumb_col, info_col = st.columns([1, 3])
                        with thumb_col:
                            st.image(data[0], width=90)
                        with info_col:
                            st.markdown(f"**{plabel}** captured ✓")
                            if st.button(f"Retake {plabel}", key=f"retake_owner_{pkey}"):
                                st.session_state.owner_photo_step = i
                                st.session_state.owner_photos.pop(pkey, None)
                                st.rerun()

                if step < len(OWNER_STEPS):
                    pkey, plabel, cam_label = OWNER_STEPS[step]
                    st.markdown(f"**{plabel}**")
                    photo_data = photo_input_widget(f"style_photo_{pkey}", cam_label)
                    if photo_data is not None:
                        if st.button("Use This Photo", key=f"confirm_owner_{pkey}"):
                            st.session_state.owner_photos[pkey] = photo_data
                            st.session_state.owner_photo_step += 1
                            st.rerun()
                else:
                    st.success("All three photos captured.")
                    if st.button("Retake All", key="retake_all_owner"):
                        st.session_state.owner_photo_step = 0
                        st.session_state.owner_photos = {}
                        st.session_state.style_result_text = None
                        st.session_state.pop("style_chat_history", None)
                        st.rerun()
                    if st.button("Get Cutting Plan", key="style_analyze_btn_owner"):
                        with st.spinner("Analyzing the three photos..."):
                            photos = [
                                st.session_state.owner_photos["back"],
                                st.session_state.owner_photos["side"],
                                st.session_state.owner_photos["top"],
                            ]
                            ok, result = analyze_style_photos_owner(photos)
                        if ok:
                            st.session_state.style_result_text = result
                            st.session_state.style_chat_history = [{"role": "model", "text": result}]
                        else:
                            st.session_state.style_result_text = None
                            st.session_state.pop("style_chat_history", None)
                            st.error(result)

                if st.session_state.get("style_result_text"):
                    raw_html(
                        f"""
                        <div class="appt-card" style="flex-direction:column; align-items:flex-start; gap:10px;">
                            <div class="appt-service">Cutting Plan</div>
                            <p style="margin:0; color:#EDEAE2; font-size:1.08rem; line-height:1.65; white-space:pre-line;">{st.session_state.style_result_text}</p>
                        </div>
                        """
                    )
                    render_style_chat()

            else:
                photo_data = photo_input_widget("style_photo_customer", "Take a photo")
                if photo_data is not None:
                    if st.button("Get My Recommendation", key="style_analyze_btn"):
                        with st.spinner("Analyzing your photo..."):
                            ok, result = analyze_style_photo(photo_data[0], mime_type=photo_data[1])
                        if ok:
                            # Automatically shared with Freddie the moment it's
                            # generated — no extra step for the customer.
                            save_style_note(user["id"], result)
                            st.session_state.style_result_text = result
                            st.session_state.style_chat_history = [{"role": "model", "text": result}]
                        else:
                            st.session_state.style_result_text = None
                            st.session_state.pop("style_chat_history", None)
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
                    st.success("Sent to Freddie ✓ - he'll have this before your appointment.")
                    render_style_chat()

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
elif current_page == "What You Get":
    render_what_you_get()
elif current_page == "Book Now":
    render_book_now()
elif current_page == "Log In":
    render_login()
elif current_page == "Your Appointments":
    render_my_schedule()
elif current_page == "Customers":
    render_customers()
elif current_page == "Settings":
    render_settings()
elif current_page == "Style":
    render_style()
elif current_page == "Rewards":
    render_rewards()

# ----------------------------------------------------------------------------
# GENERIC SCROLL-REVEAL (any element with class="reveal" on the current page)
# ----------------------------------------------------------------------------
# One small iframe that watches every .reveal element on whichever page just
# rendered and fades/rises each one in as it's scrolled into view - same
# IntersectionObserver technique already used for the "What You Get" step
# cards, generalized so price cards, style-showcase cards, and feature
# pillars get it too without duplicating this script per page. Height=0
# iframe, no visible footprint, negligible cost.
components.html(
    """
    <script>
    (function() {
        const doc = window.parent.document;
        const els = Array.from(doc.querySelectorAll('.reveal'));
        const unbound = els.filter(el => !el.dataset.revealBound);
        if (!unbound.length) return;
        unbound.forEach(el => { el.dataset.revealBound = "1"; });

        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15, root: null, rootMargin: "0px 0px -40px 0px" });

        unbound.forEach(el => observer.observe(el));
    })();
    </script>
    """,
    height=0,
)

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