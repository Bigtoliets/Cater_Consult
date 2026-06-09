"""企业微信 Bot 推送器"""
import httpx
from app.push.base import BasePusher, Alert, AlertLevel

LEVEL_COLORS = {
    AlertLevel.CRITICAL: "warning",
    AlertLevel.WARNING: "comment",
    AlertLevel.INFO: "info",
    AlertLevel.UPDATE: "info",
}

LEVEL_EMOJI = {
    AlertLevel.CRITICAL: "🚨",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.INFO: "📊",
    AlertLevel.UPDATE: "✅",
}


class WechatWorkPusher(BasePusher):
    """企业微信机器人推送 (Webhook Markdown 卡片)"""
    channel_name = "wechat_work"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def push(self, alert: Alert) -> bool:
        color = LEVEL_COLORS.get(alert.level, "info")
        emoji = LEVEL_EMOJI.get(alert.level, "📌")

        markdown = f"""## {emoji} {alert.title}
> 级别：<font color="{color}">{alert.level.value.upper()}</font>
> 时间：{alert.triggered_at.strftime('%Y-%m-%d %H:%M')}
{f'> 菜品：{alert.dish_name}' if alert.dish_name else ''}
{f'> 决策ID：{alert.decision_id}' if alert.decision_id else ''}

{alert.content}
"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json={
                    "msgtype": "markdown",
                    "markdown": {"content": markdown},
                })
                return resp.status_code == 200
        except Exception:
            return False
