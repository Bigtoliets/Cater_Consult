"""Milvus 向量库初始化 —— 创建 gold_collection 和 standard_collection

运行一次即可：python init_milvus.py
"""
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility

from app.config import agent_settings

HOST = agent_settings.MILVUS_HOST
PORT = agent_settings.MILVUS_PORT
DIM = 1024  # text-embedding-v4 维度（阿里云 DashScope）


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

    for name in ("standard_collection", "gold_collection"):
        if utility.has_collection(name):
            print(f"集合 {name} 已存在，跳过")
            continue
        col = Collection(name=name, schema=schema)
        col.create_index(
            field_name="vector",
            index_params={
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128},
            },
        )
        print(f"集合 {name} 创建完成 (dim={DIM}, metric=IP)")

    connections.disconnect("default")
    print("初始化完成。")


if __name__ == "__main__":
    create_collections()
