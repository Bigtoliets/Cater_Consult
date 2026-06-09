"""点餐机后台数据接口连接器"""
from datetime import datetime
from app.connectors.base import BaseConnector, RawReview


class POSConnector(BaseConnector):
    """点餐机后台接口对接 (需在 .env 配置 POS_API_URL / POS_API_KEY)"""
    source_name = "pos"

    def __init__(self, api_url: str = "", api_key: str = ""):
        self.api_url = api_url or ""
        self.api_key = api_key or ""
        self._enabled = bool(api_url)

    async def health_check(self) -> bool:
        return self._enabled

    async def fetch(self, start_date: datetime, end_date: datetime) -> list[RawReview]:
        if not self._enabled:
            return []

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.api_url}/api/reviews",
                    params={
                        "from": start_date.strftime("%Y-%m-%d"),
                        "to": end_date.strftime("%Y-%m-%d"),
                    },
                    headers={"X-API-Key": self.api_key},
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                reviews = []
                for item in data.get("reviews", []):
                    reviews.append(RawReview(
                        raw_text=item.get("comment", ""),
                        source="pos",
                        dish_name_raw=item.get("dish_name"),
                        rating=int(item.get("rating", 0)),
                        meal_time=item.get("period"),
                        reviewed_at=datetime.fromisoformat(item.get("time", datetime.now().isoformat())),
                        external_id=f"pos_{item.get('id')}",
                        stall_name=item.get("counter_name"),
                    ))
                return reviews
        except Exception:
            return []
