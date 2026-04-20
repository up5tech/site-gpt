import os
from fastapi_mail import ConnectionConfig

# Email Configuration for fastapi-mail
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM", "noreply@example.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_TLS = os.getenv("MAIL_TLS", "true").lower() == "true"
MAIL_SSL = os.getenv("MAIL_SSL", "false").lower() == "true"

EmailSettings = ConnectionConfig(
    MAIL_USERNAME=MAIL_USERNAME,
    MAIL_PASSWORD=MAIL_PASSWORD,
    MAIL_FROM=MAIL_FROM,
    MAIL_PORT=MAIL_PORT,
    MAIL_SERVER=MAIL_SERVER,
    MAIL_TLS=MAIL_TLS,
    MAIL_SSL=MAIL_SSL,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)


def send_email(
    recipient: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
):
    from fastapi_mail import FastMail, MessageSchema

    fm = FastMail(EmailSettings)
    message = MessageSchema(
        subject=subject,
        recipients=[recipient],
        body=body,
        subtype="html",
        cc=cc,
        bcc=bcc,
    )
    fm.send_message(message)
