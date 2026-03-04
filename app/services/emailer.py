import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings
import logging

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send plain-text email. Returns True if sent, False if misconfigured (dev mode)."""
    if not settings.SMTP_HOST:
        logger.info(f"[DEV EMAIL] To: {to} | Subject: {subject}\n{body}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to
        msg.attach(MIMEText(body, "plain", "utf-8"))

        smtp_cls = smtplib.SMTP_SSL if not settings.SMTP_TLS else smtplib.SMTP
        with smtp_cls(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASS:
                server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.sendmail(settings.EMAIL_FROM, [to], msg.as_string())
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False
