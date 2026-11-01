"""SMTP delivery for email verification and one-time password recovery.

The package sends no telemetry or mail unless the operator configures SMTP.
"""
from email.message import EmailMessage
import os
import smtplib


def configured():
    return bool(os.getenv('AI_APP_SERVER_SMTP_HOST') and os.getenv('AI_APP_SERVER_SMTP_FROM'))


def send_mail(to: str, subject: str, body: str):
    if not configured():
        return False
    message = EmailMessage()
    message['From'] = os.environ['AI_APP_SERVER_SMTP_FROM']
    message['To'] = to
    message['Subject'] = subject
    message.set_content(body)
    host = os.environ['AI_APP_SERVER_SMTP_HOST']
    ssl_mode = os.getenv('AI_APP_SERVER_SMTP_SSL') == '1'
    port = int(os.getenv('AI_APP_SERVER_SMTP_PORT') or (465 if ssl_mode else 587))
    connection = smtplib.SMTP_SSL(host, port, timeout=10) if ssl_mode else smtplib.SMTP(host, port, timeout=10)
    with connection as smtp:
        if not ssl_mode:
            smtp.ehlo()
            smtp.starttls()  # Reject mail delivery if TLS cannot be established.
            smtp.ehlo()
        user = os.getenv('AI_APP_SERVER_SMTP_USER')
        if user:
            smtp.login(user, os.getenv('AI_APP_SERVER_SMTP_PASSWORD', ''))
        smtp.send_message(message)
    return True
