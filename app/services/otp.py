"""Email OTP generation and delivery helpers."""

from email.message import EmailMessage
import hashlib
import hmac
import secrets
import smtplib
import ssl

from app.core.config import get_settings

settings = get_settings()


def generate_otp() -> str:
    """Return a cryptographically random six-digit OTP."""

    return f"{secrets.randbelow(1_000_000):06d}"


def otp_digest(username: str, otp: str) -> str:
    """Return a keyed digest for an OTP without storing the OTP itself."""

    value = f"{username}:{otp}".encode("utf-8")
    return hmac.new(settings.secret_key.encode("utf-8"), value, hashlib.sha256).hexdigest()


def send_otp_email(recipient: str, otp: str) -> None:
    """Send an OTP email using configured SMTP settings."""

    if not settings.smtp_host or not settings.smtp_from:
        raise RuntimeError("Email OTP is not configured. Set SMTP_HOST and SMTP_FROM.")

    message = EmailMessage()
    message["Subject"] = f"Your {settings.app_name} verification code"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        f"Your {settings.app_name} verification code is {otp}.\n\n"
        f"It expires in {settings.otp_expire_minutes} minutes. If you did not try to sign in, ignore this email."
    )

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_starttls:
                server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError("Unable to send the verification email. Check SMTP settings.") from exc
