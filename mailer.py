"""Plain SMTP mail sender for transactional Evolum email (password reset etc).

Uses stdlib smtplib + email.mime — no extra dependencies. Reads:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM

Fails soft: if creds aren't set or send fails, logs and returns False so the
caller can still respond generically to the user ("if that account exists,
we sent a link") without leaking the error.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> bool:
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    sender = os.environ.get("MAIL_FROM") or user
    if not (host and user and password):
        print(f"⚠️  send_mail: SMTP not configured — would have sent {subject!r} to {to}", flush=True)
        return False

    msg = MIMEMultipart("alternative") if html else MIMEText(text, "plain", "utf-8")
    if html:
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(user, password)
            s.sendmail(sender, [to], msg.as_string())
        return True
    except Exception as e:
        print(f"⚠️  send_mail failed to {to}: {type(e).__name__}: {e}", flush=True)
        return False
