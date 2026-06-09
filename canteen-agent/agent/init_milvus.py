"""Milvus 向量库初始化 v3.0 — 五 Collection

运行: python init_milvus.py
"""
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility

from app.config import agent_settings

HOST = agent_settings.MILVUS_HOST
PORT = agent_settings.MILVUS_PORT
DIM = 1024  # text-embedding-v4 维度


COLLECTION_CONFIGS = {
    "gold_collection": "金标经验库（管理层认证的标杆整改方案）",
    "standard_collection": "普通经验库（自动沉淀的历史决策）",
    "sop_collection": "标准工艺库（菜品标准操作流程）",
    "pattern_collection": "问题模式库（问题→根因→方案映射）",
    "cycle_collection": "周期规律库（季节/周度/时段品控规律）",
}


def create_collections():
    connections.connect(alias="default", host=HOST, port=str(PORT))
    print(f"已连接 Milvus: {HOST}:{PORT}")

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="decision_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=DIM),
    ]
    schema = CollectionSchema(fields, description="Canteen Agent 向量库")

    for name, description in COLLECTION_CONFIGS.items():
        if utility.has_collection(name):
            print(f"  [{name}] 已存在 ({description})，跳过")
            continue
        col = Collection(name=name, schema=schema, description=description)
        col.create_index(
            field_name="vector",
            index_params={
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128},
            },
        )
        col.load()
        print(f"  [{name}] 创建完成 ({description})")

    connections.disconnect("default")
    print(f"\n✅ 初始化完成: {len(COLLECTION_CONFIGS)} 个 Collection")


if __name__ == "__main__":
    create_collections()
