"""美团商家开放平台连接器"""
from datetime import datetime
from app.connectors.base import BaseConnector, RawReview


class MeituanConnector(BaseConnector):
    """美团商家开放平台 API 对接 (需在 .env 配置 MEITUAN_APP_ID / MEITUAN_APP_SECRET)"""
    source_name = "meituan"

    def __init__(self, app_id: str = "", app_secret: str = "", shop_id: str = ""):
        self.app_id = app_id or ""
        self.app_secret = app_secret or ""
        self.shop_id = shop_id or ""
        self._enabled = bool(app_id and app_secret)

    async def health_check(self) -> bool:
        return self._enabled

    async def fetch(self, start_date: datetime, end_date: datetime) -> list[RawReview]:
        """从美团 API 拉取评价"""
        if not self._enabled:
            return []

        # 美团商家开放平台 API 对接（需替换为实际接口）
        # GET /api/v1/comment/list?shop_id={shop_id}&start_time={}&end_time={}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"https://api.meituan.com/comment/v1/list",
                    params={
                        "app_id": self.app_id,
                        "shop_id": self.shop_id,
                        "start_time": int(start_date.timestamp()),
                        "end_time": int(end_date.timestamp()),
                    },
                    headers={"Authorization": f"Bearer {self.app_secret}"},
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                reviews = []
                for item in data.get("data", {}).get("comments", []):
                    reviews.append(RawReview(
                        raw_text=item.get("content", ""),
                        source="meituan",
                        dish_name_raw=item.get("dish_name"),
                        rating=int(item.get("score", 0)),
                        meal_time=item.get("meal_period"),
                        reviewed_at=datetime.fromtimestamp(item.get("create_time", 0)),
                        external_id=f"mt_{item.get('comment_id')}",
                        metadata={"user_name": item.get("user_name", "")},
                    ))
                return reviews
        except Exception:
            return []
