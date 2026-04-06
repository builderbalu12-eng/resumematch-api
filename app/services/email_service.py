import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings


def _send_sync(to_email: str, subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from_email, to_email, msg.as_string())


async def send_email(to_email: str, subject: str, html_body: str) -> None:
    """Send an email asynchronously using a thread pool."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_sync, to_email, subject, html_body)


def _password_reset_html(reset_link: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px;background:#f9fafb;border-radius:12px;">
      <h2 style="color:#1e293b;margin-bottom:8px;">Reset your password</h2>
      <p style="color:#475569;font-size:15px;line-height:1.6;">
        We received a request to reset the password for your ResumeMatch account.
        Click the button below to choose a new password. This link expires in <strong>15 minutes</strong>.
      </p>
      <a href="{reset_link}"
         style="display:inline-block;margin:24px 0;padding:12px 28px;background:#6366f1;color:#fff;
                text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;">
        Reset Password
      </a>
      <p style="color:#94a3b8;font-size:13px;">
        If you didn't request this, you can safely ignore this email — your password won't change.
      </p>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;" />
      <p style="color:#cbd5e1;font-size:12px;">ResumeMatch &mdash; resume.zenlead.in</p>
    </div>
    """
