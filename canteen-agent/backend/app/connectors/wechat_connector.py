"""微信小程序评价导出连接器"""
from datetime import datetime
from app.connectors.base import BaseConnector, RawReview


class WechatConnector(BaseConnector):
    """微信小程序评价 API 对接 (需在 .env 配置 WECHAT_APP_ID / WECHAT_APP_SECRET)"""
    source_name = "wechat"

    def __init__(self, app_id: str = "", app_secret: str = ""):
        self.app_id = app_id or ""
        self.app_secret = app_secret or ""
        self._enabled = bool(app_id and app_secret)

    async def health_check(self) -> bool:
        return self._enabled

    async def fetch(self, start_date: datetime, end_date: datetime) -> list[RawReview]:
        if not self._enabled:
            return []

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                # 1. 获取 access_token
                token_resp = await client.get(
                    "https://api.weixin.qq.com/cgi-bin/token",
                    params={
                        "grant_type": "client_credential",
                        "appid": self.app_id,
                        "secret": self.app_secret,
                    },
                )
                if token_resp.status_code != 200:
                    return []
                access_token = token_resp.json().get("access_token", "")

                # 2. 拉取评价数据（需替换为实际接口）
                resp = await client.post(
                    f"https://api.weixin.qq.com/wxa/business/getcommentlist",
                    params={"access_token": access_token},
                    json={
                        "begin_date": start_date.strftime("%Y-%m-%d"),
                        "end_date": end_date.strftime("%Y-%m-%d"),
                        "limit": 100,
                    },
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                reviews = []
                for item in data.get("comment_list", []):
                    reviews.append(RawReview(
                        raw_text=item.get("content", ""),
                        source="wechat",
                        dish_name_raw=item.get("dish"),
                        rating=int(item.get("score", 0)),
                        meal_time=item.get("time_slot"),
                        reviewed_at=datetime.fromtimestamp(item.get("create_time", 0)),
                        external_id=f"wx_{item.get('comment_id')}",
                    ))
                return reviews
        except Exception:
            return []
