"""core Session 抽象测试(2026-08-08):CLI REPL / web 三端共用的会话机制。

验证:
- Session.create 装配会话(persister/tracer/event_store 按 run_id 建在 PERSIST_ROOT,events.jsonl 可写)
- run_turn 内部持 turn_lock:两个并发 turn 串行(用户 turn vs 自动 turn 互斥,
  共享 messages 不并发写)——原 test_session_loop_waits_for_turn_lock 的锁语义上收于此
- notification_input 构造通知消息格式(对齐 CC 通知)
- close 幂等(正常退出带 run_end / 异常路径兜底重复 close 都不崩)
不依赖真实 LLM(同 test_events_messages 的 mock 模式)。
运行(从 code/,3.12 venv): python -m pytest tests/test_session.py -v
"""
import asyncio

import pytest

import agent.persist.paths as paths
from agent.session import Session
from agent.config.config import AgentConfig
from agent.streaming.sink import NullSink


def test_session_create_wires_persistables():
    """Session.create 按 run_id 建 Persister/Tracer/EventStore,events.jsonl 能写(落盘链路通)。"""
    sess = Session.create(
        registry=None, model_adapter=object(), tool_executor=None, config=AgentConfig(max_steps=3),
    )
    try:
        assert sess.persister is not None and sess.tracer is not None and sess.event_store is not None
        from agent.streaming.events import RunStart
        sess.event_store.emit(RunStart(run_id=sess.run_id))
        p = paths.PERSIST_ROOT / sess.run_id / "events.jsonl"
        assert p.exists()   # EventStore 惰性建文件,首条 web 事件即落
    finally:
        sess.close()


def test_notification_input_format():
    """通知消息格式(对齐 CC 通知):主 agent 读子 agent 结果。"""
    assert Session.notification_input("subagent", "结果文本", "completed") == \
        "[task-notification] subagent 完成(status=completed):\n结果文本"


def test_run_turn_serializes_on_turn_lock(monkeypatch):
    """run_turn 内部持 turn_lock:两个并发 turn 严格串行(用户 turn 与自动 turn 互斥,
    共享 messages 不并发写)。等价旧 _session_loop 的锁语义,上收到 Session。"""
    import agent.session as session_mod

    order: list[str] = []

    async def fake_run_turn(user_input, state, ctx, persister):
        order.append("start-" + user_input)
        await asyncio.sleep(0.05)
        order.append("end-" + user_input)
        return state

    monkeypatch.setattr(session_mod, "_run_turn", fake_run_turn)
    sess = Session(run_id="lock-sess", config=AgentConfig(max_steps=3), model_adapter=object())

    async def _run():
        t1 = asyncio.create_task(sess.run_turn("A", NullSink()))
        for _ in range(100):
            if "start-A" in order:
                break
            await asyncio.sleep(0.01)
        assert order == ["start-A"], "t1 应先拿到锁并开始"
        t2 = asyncio.create_task(sess.run_turn("B", NullSink()))
        await asyncio.sleep(0.02)
        assert order == ["start-A"], "B 应在 A 持锁时等待(run_turn 内持锁)"
        await asyncio.gather(t1, t2)

    asyncio.run(_run())
    # 严格串行:start-A -> end-A -> start-B -> end-B(绝不交错)
    assert order == ["start-A", "end-A", "start-B", "end-B"]


def test_close_idempotent():
    """close 幂等:裸 Session(全 None)异常路径兜底 + 重复 close 都不崩。"""
    sess = Session(run_id="close-idem", persister=None, tracer=None, config=AgentConfig(max_steps=3))
    sess.close()
    sess.close()
