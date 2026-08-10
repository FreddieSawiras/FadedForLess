"""
reminder_worker.py — sends the "1 hour before your appointment" reminder
email to customers.

WHY THIS IS A SEPARATE SCRIPT
------------------------------
app.py only runs code when someone is actively loading a page in their
browser. There's no built-in way for a Streamlit app to wake itself up on
a timer and send an email while nobody is visiting the site. So this
reminder has to live in its own small script that you run on a repeating
schedule (every 5-10 minutes) outside of Streamlit, using your operating
system's task scheduler. It shares the same database file as app.py, so
it sees the exact same appointments.

WHAT IT DOES EACH TIME IT RUNS
-------------------------------
1. Looks at every Confirmed appointment starting between 55 and 65 minutes
   from right now (a 10-minute window, so it can't be missed even if the
   scheduler runs every 5-10 min instead of exactly once a minute).
2. Skips any appointment that's already had its reminder sent
   (reminder_sent = 1), so nobody gets double-emailed.
3. Sends the customer a reminder email and marks reminder_sent = 1.

SETUP
-----
1. Put this file in the SAME FOLDER as app.py (it needs fadedforless.db
   to be right next to it, same as app.py expects) — and make sure the
   assets/ folder (with email_logo.png in it) is there too, since the
   reminder email includes the logo just like the other emails.
2. Set the Gmail App Password as an environment variable (the sending and
   owner addresses are already fixed below, same as app.py):
   GMAIL_APP_PASSWORD
   (See the "EMAIL NOTIFICATIONS" comment block near the top of app.py's
   ADMIN LOGIN section for how to get a Gmail App Password.)
3. Schedule it to run every 5-10 minutes:

   -- macOS / Linux (cron) --
   Run `crontab -e` and add a line like:
       */5 * * * * cd /full/path/to/your/app/folder && /usr/bin/python3 reminder_worker.py >> reminder.log 2>&1

   -- Windows (Task Scheduler) --
   Task Scheduler -> Create Task -> Trigger: "Repeat task every 5 minutes"
   indefinitely -> Action: "Start a program" ->
       Program: python.exe
       Arguments: reminder_worker.py
       Start in: (the full path to your app folder)

That's it — leave it running and reminders will go out on their own.
"""

import os
import sqlite3
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timedelta

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "fadedforless.db")
EMAIL_LOGO_PATH = os.path.join(APP_DIR, "assets", "email_logo.png")

GMAIL_ADDRESS = "faded.for.less@gmail.com"
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
OWNER_EMAIL = "freddiesawiras2@gmail.com"


def email_wrapper(inner_html):
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


def send_email(to_email, subject, html_body):
    if not GMAIL_APP_PASSWORD or not to_email:
        print("[reminder_worker] Email not configured (GMAIL_APP_PASSWORD missing) — skipping send.")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"FADEDFORLESS <{GMAIL_ADDRESS}>"
        msg["To"] = to_email
        msg.set_content("This email requires an HTML-capable email client to view.")
        msg.add_alternative(html_body, subtype="html")
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
        print(f"[reminder_worker] Failed to send to {to_email}: {e}")
        return False


def main():
    if not os.path.exists(DB_PATH):
        print(f"[reminder_worker] No database found at {DB_PATH} — is this file in the same folder as app.py?")
        return

    conn = sqlite3.connect(DB_PATH)
    now = datetime.now()
    window_start = now + timedelta(minutes=55)
    window_end = now + timedelta(minutes=65)

    rows = conn.execute(
        "SELECT a.id, a.service, a.appt_date, a.appt_time, u.name, u.email "
        "FROM appointments a JOIN users u ON u.id = a.user_id "
        "WHERE a.status = 'Confirmed' AND a.reminder_sent = 0"
    ).fetchall()

    sent_count = 0
    for appt_id, service, appt_date, appt_time, name, email in rows:
        try:
            appt_dt = datetime.strptime(f"{appt_date} {appt_time}", "%Y-%m-%d %I:%M %p")
        except ValueError:
            continue  # skip anything with an unexpected time format rather than crash the whole run

        if window_start <= appt_dt <= window_end:
            pretty = f"{service} today at {appt_time}" if appt_dt.date() == now.date() else f"{service} on {appt_dt.strftime('%b %d')} at {appt_time}"
            ok = send_email(
                email,
                "Reminder: Your appointment is in 1 hour - FADEDFORLESS",
                email_wrapper(
                    f"<p>Hey {name},</p>"
                    f"<p>Just a heads up, your appointment is coming up:<br><strong>{pretty}</strong></p>"
                    "<p>See you soon!</p>"
                    "<p>- FADEDFORLESS</p>"
                ),
            )
            if ok:
                conn.execute("UPDATE appointments SET reminder_sent = 1 WHERE id = ?", (appt_id,))
                conn.commit()
                sent_count += 1

    print(f"[reminder_worker] Checked {len(rows)} upcoming appointment(s), sent {sent_count} reminder(s).")
    conn.close()


if __name__ == "__main__":
    main()
