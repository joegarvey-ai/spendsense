"""Gmail SMTP sender using App Password authentication."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def send_email(
    to: str,
    subject: str,
    html_body: str,
    sender: str | None = None,
    app_password: str | None = None,
) -> bool:
    """Send an HTML email via Gmail SMTP with App Password.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        html_body: HTML content of the email.
        sender: Gmail address (defaults to GMAIL_SENDER env var).
        app_password: Gmail App Password (defaults to GMAIL_APP_PASSWORD env var).

    Returns:
        True if sent successfully, False otherwise.
    """
    sender = sender or os.getenv("GMAIL_SENDER")
    app_password = app_password or os.getenv("GMAIL_APP_PASSWORD")

    if not sender or not app_password:
        logger.error("GMAIL_SENDER or GMAIL_APP_PASSWORD not set in .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Monday Money Brief <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject

    plain = "This email requires an HTML-capable email client. View in Gmail or Outlook."
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, app_password)
            server.sendmail(sender, to, msg.as_string())

        logger.info("Email sent to %s: %s", to, subject)
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail authentication failed. Check GMAIL_APP_PASSWORD in .env")
        return False
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)
        return False


def send_digest(primary_email: str, secondary_email: str, primary_digest: dict, secondary_digest: dict) -> dict:
    """Send weekly digest emails to both recipients.

    Args:
        primary_email: Full digest recipient email.
        secondary_email: Summary digest recipient email.
        primary_digest: {"subject": str, "html": str}
        secondary_digest: {"subject": str, "html": str}

    Returns:
        {"primary": bool, "secondary": bool} indicating send success.
    """
    results = {}
    results["primary"] = send_email(primary_email, primary_digest["subject"], primary_digest["html"])
    results["secondary"] = send_email(secondary_email, secondary_digest["subject"], secondary_digest["html"])
    return results
