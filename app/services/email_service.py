"""
Email service for sending verification and password reset emails.

Supports multiple email providers:
- SMTP (aiosmtplib)
- SendGrid API
- Resend API

Part of OSP-14 implementation.
"""

import logging
import random
import string
from abc import ABC, abstractmethod

from app.core.config import settings

logger = logging.getLogger("agent_chassis.email")

# Conditional imports for email providers
try:
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    import aiosmtplib

    SMTP_AVAILABLE = True
except ImportError:
    SMTP_AVAILABLE = False

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send an email."""
        pass


class SMTPProvider(EmailProvider):
    """SMTP email provider using aiosmtplib."""

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send email via SMTP."""
        if not SMTP_AVAILABLE:
            logger.warning("aiosmtplib not installed, cannot send SMTP emails")
            return False

        if not settings.SMTP_HOST:
            logger.warning("SMTP_HOST not configured")
            return False

        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = settings.EMAIL_FROM
            message["To"] = to

            if text_body:
                message.attach(MIMEText(text_body, "plain"))
            message.attach(MIMEText(html_body, "html"))

            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                start_tls=True,
            )
            return True
        except Exception as e:
            logger.error("SMTP email error: %s", e)
            return False


class SendGridProvider(EmailProvider):
    """SendGrid API email provider."""

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send email via SendGrid API."""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not installed, cannot use SendGrid API")
            return False

        if not settings.SENDGRID_API_KEY:
            logger.warning("SENDGRID_API_KEY not configured")
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "personalizations": [{"to": [{"email": to}]}],
                        "from": {"email": settings.EMAIL_FROM},
                        "subject": subject,
                        "content": [
                            {"type": "text/plain", "value": text_body or html_body},
                            {"type": "text/html", "value": html_body},
                        ],
                    },
                )
                return response.status_code in (200, 202)
        except Exception as e:
            logger.error("SendGrid email error: %s", e)
            return False


class ResendProvider(EmailProvider):
    """Resend API email provider."""

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send email via Resend API."""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not installed, cannot use Resend API")
            return False

        if not settings.RESEND_API_KEY:
            logger.warning("RESEND_API_KEY not configured")
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": settings.EMAIL_FROM,
                        "to": [to],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                )
                return response.status_code == 200
        except Exception as e:
            logger.error("Resend email error: %s", e)
            return False


class ConsoleProvider(EmailProvider):
    """Console email provider for development/testing."""

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Print email to console (for development)."""
        print(f"\n{'=' * 60}")
        print(f"EMAIL TO: {to}")
        print(f"SUBJECT: {subject}")
        print(f"{'=' * 60}")
        print(text_body or html_body)
        print(f"{'=' * 60}\n")
        return True


class EmailService:
    """
    Service for sending verification and password reset emails.

    Automatically selects the appropriate provider based on configuration.
    """

    def __init__(self):
        self._provider: EmailProvider | None = None

    def _get_provider(self) -> EmailProvider:
        """Get the configured email provider."""
        if self._provider is None:
            provider_type = settings.EMAIL_PROVIDER.lower()

            if provider_type == "sendgrid" and settings.SENDGRID_API_KEY:
                self._provider = SendGridProvider()
            elif provider_type == "resend" and settings.RESEND_API_KEY:
                self._provider = ResendProvider()
            elif provider_type == "smtp" and settings.SMTP_HOST:
                self._provider = SMTPProvider()
            else:
                # Fallback to console for development
                logger.warning("No email provider configured, using console output")
                self._provider = ConsoleProvider()

        return self._provider

    @staticmethod
    def generate_verification_code() -> str:
        """Generate a 6-digit verification code."""
        return "".join(random.choices(string.digits, k=6))

    async def send_verification_email(self, email: str, code: str) -> bool:
        """
        Send an email verification code.

        Args:
            email: Recipient email address.
            code: 6-digit verification code.

        Returns:
            True if email sent successfully, False otherwise.
        """
        subject = f"Verify your email - {settings.PROJECT_NAME}"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px;
                         text-align: center; padding: 20px; background: #f5f5f5;
                         border-radius: 8px; margin: 20px 0; }}
                .footer {{ font-size: 12px; color: #666; margin-top: 30px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Verify your email address</h2>
                <p>Thanks for signing up! Please use the following code to verify your email:</p>
                <div class="code">{code}</div>
                <p>This code will expire in {settings.VERIFICATION_CODE_EXPIRE_MINUTES} minutes.</p>
                <p>If you didn't create an account, you can safely ignore this email.</p>
                <div class="footer">
                    <p>This email was sent by {settings.PROJECT_NAME}</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_body = f"""
Verify your email address

Thanks for signing up! Please use the following code to verify your email:

{code}

This code will expire in {settings.VERIFICATION_CODE_EXPIRE_MINUTES} minutes.

If you didn't create an account, you can safely ignore this email.

---
This email was sent by {settings.PROJECT_NAME}
        """

        return await self._get_provider().send_email(email, subject, html_body, text_body)

    async def send_password_reset_email(self, email: str, code: str) -> bool:
        """
        Send a password reset code.

        Args:
            email: Recipient email address.
            code: 6-digit reset code.

        Returns:
            True if email sent successfully, False otherwise.
        """
        subject = f"Reset your password - {settings.PROJECT_NAME}"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px;
                         text-align: center; padding: 20px; background: #f5f5f5;
                         border-radius: 8px; margin: 20px 0; }}
                .warning {{ color: #e74c3c; }}
                .footer {{ font-size: 12px; color: #666; margin-top: 30px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Reset your password</h2>
                <p>We received a request to reset your password. Use this code:</p>
                <div class="code">{code}</div>
                <p>This code will expire in {settings.VERIFICATION_CODE_EXPIRE_MINUTES} minutes.</p>
                <p class="warning"><strong>If you didn't request a password reset, please ignore this email
                   and ensure your account is secure.</strong></p>
                <div class="footer">
                    <p>This email was sent by {settings.PROJECT_NAME}</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_body = f"""
Reset your password

We received a request to reset your password. Use this code:

{code}

This code will expire in {settings.VERIFICATION_CODE_EXPIRE_MINUTES} minutes.

If you didn't request a password reset, please ignore this email and ensure your account is secure.

---
This email was sent by {settings.PROJECT_NAME}
        """

        return await self._get_provider().send_email(email, subject, html_body, text_body)


# Global instance
email_service = EmailService()
