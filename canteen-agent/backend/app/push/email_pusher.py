"""邮件推送器 (SMTP)"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.push.base import BasePusher, Alert, AlertLevel


class EmailPusher(BasePusher):
    """邮件推送 (SMTP)"""
    channel_name = "email"

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        sender: str,
        password: str,
        recipients: list[str],
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.recipients = recipients

    async def push(self, alert: Alert) -> bool:
        subject = f"[{alert.level.value.upper()}] {alert.title}"

        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg["Subject"] = subject

        html_body = f"""
        <h2>{alert.title}</h2>
        <p><strong>级别：</strong>{alert.level.value.upper()}</p>
        <p><strong>时间：</strong>{alert.triggered_at.strftime('%Y-%m-%d %H:%M')}</p>
        {f'<p><strong>菜品：</strong>{alert.dish_name}</p>' if alert.dish_name else ''}
        <hr/>
        <pre style="white-space:pre-wrap;font-family:inherit;">{alert.content}</pre>
        """
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            return True
        except Exception:
            return False
