"""探针:看豆包(ark)provider 返回的 usage 原始字段,确认有没有缓存命中相关字段。

发 2 次相同 prompt(第 2 次理论上命中 prompt cache),打印:
- 解析后的 TokenUsage(含 cached_tokens,经 _extract_cached_tokens)
- raw usage dict(豆包 SDK response.model_dump()["usage"] 的全部字段)

运行(从 code/,3.12 venv):python probe_ark_usage.py
需 .env 配 VOLCANO_ENGINE_API_KEY / VOLCANO_ENGINE_MODEL 等。
"""
import asyncio
import json

from agent.config.provider import load_provider_config, make_adapter
from agent.core.models import ModelRequest
from agent.core.messages import Message

# 长前缀:豆包 prompt cache 通常要求前缀够长(>=1024 token 量级才易命中),重复造长 system
SYS = "你是资深 Python 工程师,回答准确简洁。" * 300
USER = "用一句话解释 Python 的 GIL"


async def main():
    pc = load_provider_config("ark")
    if not pc.api_key:
        print("未配置 VOLCANO_ENGINE_API_KEY(检查 code/.env 的 VOLCANO_ENGINE_* )")
        return
    adapter = make_adapter(pc)
    print(f"provider=ark  model={pc.model}  base_url={pc.base_url}")
    print(f"system 长度={len(SYS)} 字符(造长前缀促缓存命中)")

    msgs = [Message(role="system", content=SYS), Message(role="user", content=USER)]
    for i in range(2):
        resp = await adapter.call_llm(ModelRequest(messages=msgs, model=pc.model))
        print(f"\n=== 第 {i + 1} 次 call ===")
        print("text:", (resp.text or "")[:80])
        u = resp.usage
        if u:
            print(f"解析后 TokenUsage: input={u.input_tokens} output={u.output_tokens} "
                  f"total={u.total_tokens} cached={u.cached_tokens}")
        else:
            print("解析后 TokenUsage: None(provider 没返回 usage)")
        # raw = 豆包 SDK response.model_dump(),看原始 usage 全字段
        raw = resp.raw
        ru = raw.get("usage") if isinstance(raw, dict) else getattr(raw, "usage", None)
        if ru is None:
            print("raw usage: (无)")
        elif isinstance(ru, dict):
            print("raw usage dict:", json.dumps(ru, ensure_ascii=False, indent=2))
            print("raw usage keys:", list(ru.keys()))
        else:
            print("raw usage obj:", ru)
            print("  fields:", [a for a in dir(ru) if not a.startswith("_")])

    print("\n结论看上面 raw usage keys:有 cached_tokens/prompt_cache_hit_tokens 即支持缓存上报;")
    print("若没有,说明该 model/endpoint 不返回缓存字段(cached_tokens 恒 0 是 provider 侧限制,非 bug)。")


if __name__ == "__main__":
    asyncio.run(main())
