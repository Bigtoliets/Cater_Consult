"""问答会话记忆离线自测（不需要 Milvus / LLM / Redis）

    python tests/test_chat_memory.py

盯的是「记忆串味」这条线，都是会真出问题的点：

- 会话记忆写 memory_collection；写进 standard_collection 会被当成菜品经验检索，
  甚至能被 promote_to_gold 飞升成金标（Q/A 摘要混进品控知识库）
- id 形如 MEM-{会话标签}-{turn_id}：同一会话能过滤，不同会话互不可见，
  且 id 里不出现原始 session_id
- retrieve_relevant 必须带 expr，只召回本会话
- 向量库不可用时返回空串 / 不抛异常，别把问答链路带崩
- build_context：system + 压缩块 + 关键事实 + 滑动窗口；不传当前问题时不拼空消息
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


# ── 假 Milvus 客户端（manager 内部是延迟 import，所以桩要先进 sys.modules）──
_rows: list[tuple[str, str]] = []          # [(decision_id, content)]
_writes: list[tuple[str, str]] = []
_searches: list[dict] = []
_standard_writes: list[tuple] = []
_fail_write = {"on": False}
_fail_search = {"on": False}


async def _write_to_memory(decision_id, content):
    if _fail_write["on"]:
        raise RuntimeError("memory_collection 不存在")
    _writes.append((decision_id, content))
    _rows.append((decision_id, content))
    return {"status": "written"}


async def _search_with_score(collection_name, query, k=3, expr=None):
    if _fail_search["on"]:
        raise RuntimeError("Milvus 连不上")
    _searches.append({"collection": collection_name, "query": query, "k": k, "expr": expr})
    rows = list(_rows)
    if expr:
        # 只实现本测试用到的前缀过滤：decision_id like "PREFIX%"
        prefix = expr.split('"')[1].rstrip("%")
        rows = [r for r in rows if r[0].startswith(prefix)]
    return [{"content": c, "score": 1.0, "metadata": {"decision_id": d}} for d, c in rows[:k]]


async def _write_to_standard(*args, **kwargs):  # 不该再被调用
    _standard_writes.append((args, kwargs))
    return {"status": "written"}


_stub(
    "app.utils.milvus_client",
    search_with_score=_search_with_score,
    write_to_memory=_write_to_memory,
    write_to_standard=_write_to_standard,
    promote_to_gold=lambda *a, **k: None,
)

from app.memory.manager import CompressedMemory, MemoryManager, _session_tag  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  → {detail}" if detail and not condition else ""))


def reset():
    _rows.clear()
    _writes.clear()
    _searches.clear()
    _standard_writes.clear()
    _fail_write["on"] = False
    _fail_search["on"] = False


# ── [1] 写入隔离与 id 规则 ──────────────────────────────────


async def test_write_goes_to_memory_collection():
    print("\n[1] 会话记忆写入 memory_collection，id 带会话标签 + turn_id")
    reset()
    mem = MemoryManager(session_id="web-abc123")
    turn_id = "a" * 32
    await mem.store_episode("web-abc123", "红烧肉为什么咸？", "调味环节盐量波动", {"turn_id": turn_id})

    check("写了一次", len(_writes) == 1, f"实际: {len(_writes)}")
    decision_id, content = _writes[0]
    tag = _session_tag("web-abc123")
    check("id = MEM-{会话标签}-{turn_id}", decision_id == f"MEM-{tag}-{turn_id}", decision_id)
    check("id 里不含原始 session_id", "web-abc123" not in decision_id)
    check("内容是 Q/A 摘要", content.startswith("Q: 红烧肉为什么咸？") and "A: 调味环节盐量波动" in content)
    check("没有再往 standard_collection 写（那会被当菜品经验）", _standard_writes == [])

    await mem.store_episode("web-abc123", "q", "a")  # 没传 metadata
    check("无 turn_id 时仍带会话前缀", _writes[1][0].startswith(f"MEM-{tag}-"))
    check("两次写入 id 不同", _writes[0][0] != _writes[1][0])


# ── [2] 检索隔离 ────────────────────────────────────────────


async def test_retrieve_only_own_session():
    print("\n[2] 检索只召回本会话的记忆（A 的记忆不会串给 B）")
    reset()
    mem_a, mem_b = MemoryManager("web-a"), MemoryManager("web-b")
    await mem_a.store_episode("web-a", "A 的问题", "A 的答案：少放盐", {"turn_id": "1" * 32})
    await mem_b.store_episode("web-b", "B 的问题", "B 的答案：换供应商", {"turn_id": "2" * 32})

    text = await mem_a.retrieve_relevant("上次说的怎么改？", "web-a", k=3)
    check("只看到自己的记忆", "A 的答案" in text and "B 的答案" not in text, f"实际: {text}")
    check("检索打在 memory_collection", _searches[-1]["collection"] == "memory_collection")
    check("带会话过滤 expr", f'MEM-{_session_tag("web-a")}' in (_searches[-1]["expr"] or ""))
    check("结果是可读的记忆块", text.startswith("## 历史相关记忆") and "[1]" in text)
    check("空 session 不查库，直接返回空", await mem_a.retrieve_relevant("q", "") == "")


# ── [3] 容错 ────────────────────────────────────────────────


async def test_failures_are_quiet():
    print("\n[3] 向量库挂了：不抛异常，问答链路不受影响")
    reset()
    mem = MemoryManager("web-a")

    _fail_search["on"] = True
    check("检索失败返回空串", await mem.retrieve_relevant("q", "web-a") == "")
    _fail_search["on"] = False

    _fail_write["on"] = True
    raised = None
    try:
        await mem.store_episode("web-a", "q", "a")
    except Exception as exc:  # noqa: BLE001
        raised = exc
    check("写入失败不往上抛", raised is None)


# ── [4] 上下文拼装 ──────────────────────────────────────────


async def test_build_context():
    print("\n[4] build_context：压缩摘要 + 关键事实 + 滑动窗口")
    mem = MemoryManager("s1")
    mem.add_message("user", "问题1")
    mem.add_message("assistant", "答案1")

    ctx = mem.build_context("SYS", "问题2")
    check("system 提示词在最前", ctx[0] == {"role": "system", "content": "SYS"})
    check("滑动窗口按原顺序拼接",
          [m["content"] for m in ctx[1:]] == ["问题1", "答案1", "问题2"], f"实际: {ctx}")

    ctx2 = mem.build_context("SYS")
    check("不传当前问题时不会多出一条空 user", len(ctx2) == 3, f"实际: {len(ctx2)}")
    check("没有空内容消息", all(m["content"] for m in ctx2))

    mem.compressed_blocks.append(
        CompressedMemory(summary="早前聊过卫生问题", original_message_count=6, compressed_at=0)
    )
    mem.key_facts = ["盐量下调 10%"]
    ctx3 = mem.build_context("SYS")
    joined = "\n".join(m["content"] for m in ctx3)
    check("压缩摘要进上下文", "早前聊过卫生问题" in joined)
    check("关键事实进上下文", "盐量下调 10%" in joined)
    check("压缩块排在滑动窗口之前",
          joined.index("早前聊过卫生问题") < joined.index("问题1") if "问题1" in joined else True)


async def main():
    await test_write_goes_to_memory_collection()
    await test_retrieve_only_own_session()
    await test_failures_are_quiet()
    await test_build_context()
    print(f"\n{'=' * 46}\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
