from dataclasses import dataclass, field
from typing import Any, Optional

from .Adapter import OpenAIAdapter
from .models import ModelRequest
from .messages import Message
from .tools import ToolExecutor
from .tools import ToolRegistry

def agentloop(
    user_input: str,
    registry: ToolRegistry,
    model_adapter: OpenAIAdapter,
    tool_executor: ToolExecutor,
    max_steps: int = 5,
):
    """
    运行 Agent 主循环。

    流程：
    1. 接收用户输入，并封装成初始 Message。
    2. 从 ToolRegistry 中导出当前可用工具的 ToolSpec。
    3. 进入最多 max_steps 轮 Agent 循环。
    4. 每一轮都把当前 messages 和 tools 发送给模型。
    5. 如果模型没有返回 tool_calls，说明模型已经生成最终回答，直接返回。
    6. 如果模型返回 tool_calls，则由 ToolExecutor 执行这些工具调用。
    7. 将 assistant 的工具调用信息和工具执行结果一起回填到 messages。
    8. 进入下一轮，让模型基于工具结果继续推理。
    9. 如果超过 max_steps 仍未结束，则抛出异常，防止死循环。
    """

    # 1. 初始化对话消息
    messages = [
        Message(role="user", content=user_input)
    ]

    # 2. 从 registry 导出工具定义
    # 这里假设每个 Tool 内部都有 tool_spec 字段
    tools = [
        tool.tool_spec
        for tool in registry.list_tools()
    ]

    # 3. 多轮 Agent Loop
    for step in range(max_steps):
        # 4. 构造本轮模型请求
        model_request = ModelRequest(
            messages=messages,
            tools=tools,
            model="deepseek-v4-pro",
            temperature=0.7,
            max_tokens=500,
        )

        # 5. 调用模型
        model_response = model_adapter.call_llm(model_request)

        # 6. 如果模型没有请求工具调用，说明已经得到最终回答
        if not model_response.tool_calls:
            return model_response

        # 7. 执行当前轮模型返回的所有工具调用
        tool_results = []

        for tool_call in model_response.tool_calls:
            tool_result = tool_executor.execute(tool_call)
            tool_results.append(tool_result)

        # 8. 将本轮 assistant tool_calls 和 tool_results 回填到 messages
        # 注意：具体怎么组织 OpenAI / Claude / DeepSeek 的消息格式，
        # 应该交给 model_adapter.append_tool_results 处理
        messages = model_adapter.append_tool_results(
            messages=messages,
            model_response=model_response,
            tool_results=tool_results,
        )

    # 9. 超过最大步数仍然没有最终回答，说明可能陷入工具调用循环
    raise RuntimeError(f"Agent exceeded max_steps={max_steps}")


def run_agent_loop(registry: ToolRegistry, model_adapter: OpenAIAdapter, tool_executor: ToolExecutor):
    while True:
        user_input = input("User: ")
        if user_input.lower() in ["exit", "quit"]:
            print("Exiting agent loop.")
            break
        final_response = agentloop(user_input, registry, model_adapter, tool_executor)
        print(f"Agent: {final_response}")
        print(f"Agent: {final_response.text}")

def main():
    # 用 tools.py 模块级的 registry：@tool 装饰器把 getnowtime 注册到了那里
    import agent.tools
    registry = agent.tools.registry
    model_adapter = OpenAIAdapter()
    tool_executor = ToolExecutor(registry)

    # 运行Agent循环
    run_agent_loop(registry, model_adapter, tool_executor)


if __name__ == "__main__":
    main()