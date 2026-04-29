"""
Email assíncrono:
- Se aiosmtplib estiver instalado, usa-o (não bloqueia o event loop).
- Caso contrário, cai para smtplib via anyio.to_thread (thread separada).
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Envia e-mail sem bloquear o event loop. Retorna True se enviado."""
    if not settings.SMTP_HOST:
        logger.info(f"[DEV EMAIL] To: {to} | Subject: {subject}\n{body}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        import aiosmtplib  # type: ignore
        smtp_kwargs = dict(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            use_tls=not settings.SMTP_TLS,
            start_tls=settings.SMTP_TLS,
        )
        async with aiosmtplib.SMTP(**smtp_kwargs) as server:
            if settings.SMTP_USER and settings.SMTP_PASS:
                await server.login(settings.SMTP_USER, settings.SMTP_PASS)
            await server.send_message(msg)
        return True

    except ImportError:
        # Fallback: roda smtplib em thread separada para não bloquear
        import smtplib
        import anyio

        def _send_sync():
            smtp_cls = smtplib.SMTP_SSL if not settings.SMTP_TLS else smtplib.SMTP
            with smtp_cls(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                if settings.SMTP_TLS:
                    server.starttls()
                if settings.SMTP_USER and settings.SMTP_PASS:
                    server.login(settings.SMTP_USER, settings.SMTP_PASS)
                server.sendmail(settings.EMAIL_FROM, [to], msg.as_string())

        await anyio.to_thread.run_sync(_send_sync)
        return True

    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False
