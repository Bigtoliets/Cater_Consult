"""数据连接器模块 v3.0 — 多源评价数据统一接入"""
from app.connectors.base import BaseConnector, RawReview
from app.connectors.csv_connector import CSVConnector
from app.connectors.scheduler import FetchScheduler

__all__ = ["BaseConnector", "RawReview", "CSVConnector", "FetchScheduler"]
