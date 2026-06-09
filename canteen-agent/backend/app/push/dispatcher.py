"""推送调度器 — 从 SystemConfig 读取规则，按级别/事件类型路由到对应通道"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.push.base import Alert, AlertLevel, BasePusher
from app.models.models import SystemConfig


# 默认推送规则（兜底）
DEFAULT_PUSH_RULES = {
    AlertLevel.CRITICAL.value: ["wechat_work", "dingtalk"],
    AlertLevel.WARNING.value: ["wechat_work"],
    AlertLevel.INFO.value: ["wechat_work"],
    AlertLevel.UPDATE.value: [],
}


class PushDispatcher:
    """按配置分发告警到多个推送通道"""

    def __init__(self, pushers: list[BasePusher] | None = None):
        self._pushers: dict[str, BasePusher] = {}
        if pushers:
            for p in pushers:
                self._pushers[p.channel_name] = p

    def register(self, pusher: BasePusher):
        """注册推送通道"""
        self._pushers[pusher.channel_name] = pusher

    @property
    def registered_channels(self) -> list[str]:
        return list(self._pushers.keys())

    async def load_rules(self, db: AsyncSession) -> dict:
        """从 SystemConfig 表读取推送规则配置"""
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.config_key == "push_rules")
        )
        config = result.scalar_one_or_none()
        if config and config.config_value:
            # 合并默认规则: 用户配置覆盖默认
            merged = {**DEFAULT_PUSH_RULES, **config.config_value}
            return merged
        return dict(DEFAULT_PUSH_RULES)

    async def dispatch(self, alert: Alert, db: AsyncSession | None = None) -> dict[str, bool]:
        """按配置分发到对应通道，返回各通道推送结果"""
        rules = DEFAULT_PUSH_RULES
        if db:
            rules = await self.load_rules(db)

        channels = rules.get(alert.level.value, ["wechat_work"])
        results = {}
        for ch_name in channels:
            pusher = self._pushers.get(ch_name)
            if pusher:
                results[ch_name] = await pusher.push(alert)
            else:
                results[ch_name] = False
        return results


# 全局单例（在 FastAPI lifespan 中初始化）
_dispatcher: PushDispatcher | None = None


def get_dispatcher() -> PushDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = PushDispatcher()
    return _dispatcher


def init_dispatcher(pushers: list[BasePusher]) -> PushDispatcher:
    global _dispatcher
    _dispatcher = PushDispatcher(pushers)
    return _dispatcher
