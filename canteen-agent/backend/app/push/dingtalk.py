"""钉钉 Bot 推送器"""
import httpx
import time
import hmac
import hashlib
import base64
from urllib.parse import quote_plus
from app.push.base import BasePusher, Alert, AlertLevel

LEVEL_EMOJI = {
    AlertLevel.CRITICAL: "🚨",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.INFO: "📊",
    AlertLevel.UPDATE: "✅",
}


def _sign(secret: str, timestamp: str) -> str:
    """钉钉加签"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return quote_plus(base64.b64encode(hmac_code))


class DingTalkPusher(BasePusher):
    """钉钉机器人推送 (Webhook + 加签)"""
    channel_name = "dingtalk"

    def __init__(self, webhook_url: str, secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret

    async def push(self, alert: Alert) -> bool:
        emoji = LEVEL_EMOJI.get(alert.level, "📌")
        title = f"{emoji} {alert.title}"

        text = f"**【{alert.level.value.upper()}】** {alert.title}\n\n"
        text += f"> 时间：{alert.triggered_at.strftime('%Y-%m-%d %H:%M')}\n"
        if alert.dish_name:
            text += f"> 菜品：{alert.dish_name}\n"
        text += f"\n{alert.content}"

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        }

        url = self.webhook_url
        if self.secret:
            ts = str(round(time.time() * 1000))
            url = f"{self.webhook_url}&timestamp={ts}&sign={_sign(self.secret, ts)}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False
