"""业务服务层

刻意不在包 __init__ 里 re-export：那会让「导入一个纯逻辑模块」顺带拉起
DB 引擎与 ORM（甚至和 tasks 下的队列模块形成循环导入）。
调用方一律直接 `from app.services.xxx import yyy`。
"""
