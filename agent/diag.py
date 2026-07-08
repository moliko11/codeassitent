from agent.adapters.openai_compat import OpenAICompatibleAdapter
from agent.config.provider import load_provider_config
from agent.core.messages import Message
from agent.core.models import ModelRequest
import agent.tools

pc = load_provider_config("openai_compatible")
ad = OpenAICompatibleAdapter(pc.api_key, pc.base_url, pc.model)
tools = [t.tool_spec for t in agent.tools.registry.list_tools()]
user = Message(role="user", content="现在是几点")

def show(label, r):
    out = r.usage.output_tokens if r.usage else 0
    print(label, "| text=", repr(r.text)[:60], "| tool_calls=", r.tool_calls,
          "| stop=", r.stop_reason, "| out_tokens=", out)

# D) 换 deepseek-v4-pro + 工具（pro 可能支持工具，flash 不支持）
r = ad.call_llm(ModelRequest(messages=[user], tools=tools, model="deepseek-v4-pro",
                            temperature=0.7, max_tokens=512))
show("D) v4-pro +tools", r)

# E) deepseek-chat + 工具 + tool_choice=auto
r = ad.call_llm(ModelRequest(messages=[user], tools=tools, model="deepseek-chat",
                            temperature=0.7, max_tokens=512, meta={"tool_choice": "auto"}))
show("E) chat +tools +tc=auto", r)

# F) deepseek-chat + 工具 + tool_choice=required（强制调工具）
r = ad.call_llm(ModelRequest(messages=[user], tools=tools, model="deepseek-chat",
                            temperature=0.7, max_tokens=512, meta={"tool_choice": "required"}))
show("F) chat +tools +tc=required", r)
