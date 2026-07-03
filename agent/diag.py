from agent.Adapter import OpenAIAdapter
from agent.models import ModelRequest
from agent.messages import Message
import agent.tools

ad = OpenAIAdapter()
tools = [t.tool_spec for t in agent.tools.registry.list_tools()]
user = Message(role="user", content="现在是几点")

def show(label, r):
    print(label, "| text=", repr(r.text)[:60], "| tool_calls=", r.tool_calls,
          "| stop=", r.stop_reason, "| out_tokens=", r.usage.output_tokens)

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
