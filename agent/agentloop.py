from dataclasses import dataclass, field
from typing import Any, Optional

from .config import AgentConfig

from .state import AgentState

from .Adapter import OpenAIAdapter
from .models import  ModelRequest
from .messages import Message
from .runtime import RuntimeContext
from .tools import ToolExecutor
from .tools import ToolRegistry

def agentloop(
    user_input: str,
    context: RuntimeContext,
) -> AgentState:
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
    config = context.config or AgentConfig()
    state = context.state or AgentState(max_steps=config.max_steps)

    # 1. 初始化对话消息（system prompt 放第一条，定义 Agent 的行为契约）
    state.messages = []
    if config.system_prompt:
        state.messages.append(
            Message(role="system", content=config.system_prompt)
        )
    state.messages.append(Message(role="user", content=user_input))

    # 2. 从 registry 导出工具定义
    # 这里假设每个 Tool 内部都有 tool_spec 字段
    tools = [
        tool.tool_spec
        for tool in context.registry.list_tools()
    ]

    # 3. 多轮 Agent Loop
    while state.should_continue():
        step=state.new_step()
        # 4. 构造本轮模型请求
        try:
            model_request = ModelRequest(
            messages=state.messages,
            tools=tools if context.config.enable_tools else [],
            model=context.config.model,
            temperature=context.config.temperature,
            max_tokens=context.config.max_tokens,)
            step.model_request = model_request
            # 5. 调用模型 
            model_response = context.model_adapter.call_llm(model_request)
            
            step.model_response = model_response
            # 6. 如果模型没有请求工具调用，说明已经得到最终回答
            if not model_response.tool_calls:
                state.complete(model_response)
                step.finish()
                return state

            # 7. 执行当前轮模型返回的所有工具调用
            tool_results = []

            for tool_call in model_response.tool_calls:
                tool_result = context.tool_executor.execute(tool_call)
                tool_results.append(tool_result)

            # 8. 将本轮 assistant tool_calls 和 tool_results 回填到 messages
            # 注意：具体怎么组织 OpenAI / Claude / DeepSeek 的消息格式，
            # 应该交给 model_adapter.append_tool_results 处理
            state.messages = context.model_adapter.append_tool_results(
                messages=state.messages,
                model_response=model_response,
                tool_results=tool_results,
            )
            state.reset_error()  # 记录本轮工具调用成功，连续失败计数清零
            step.finish()
        
        except Exception as e:
            error = {
                "type": type(e).__name__,
                "message": str(e),
                "source":"agentloop",
                "retryable": True,
            }
            step.error = error
            step.finish()

            state.record_error()  # 记录本轮工具调用失败，连续失败计数加1

            # 连续失败超过阈值
            if state.consecutive_tool_failures >= config.max_consecutive_tool_failures:
                state.fail(error)
                return state

            # 否则把错误信息回填给模型当observation，让模型决定下一步怎么做
            state.messages.append(
            Message(
                role="user",
                content=f"[系统提示] 上一步执行失败：{error['type']}: {error['message']}。"
                        f"请根据错误信息调整下一步，或直接给出最终答案。",
            )
        )

    state.exceed_max_steps()

    return state

def run_agent_loop(registry: ToolRegistry, model_adapter: OpenAIAdapter, tool_executor: ToolExecutor):
    while True:
        user_input = input("User: ")
        if user_input.lower() in ["exit", "quit"]:
            print("Exiting agent loop.")
            break
        context = RuntimeContext(
            registry=registry,
            model_adapter=model_adapter,
            tool_executor=tool_executor,
            config=AgentConfig(),
            state=AgentState()
        )
        state = agentloop(user_input, context)
        if state.error:
            print(f"Agent encountered an error: {state.error}")
        elif state.final_response is not None:
            print(f"Agent: {state.final_response.text}")

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