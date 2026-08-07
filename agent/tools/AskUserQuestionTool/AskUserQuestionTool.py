"""AskUserQuestion 工具:多选问用户收集信息/澄清(对标 CC AskUserQuestion)。

- REPL 用 input()(CC 用 React UI + updatedInput 收集答案当入参;我们简化为 input 直接
  拿答案当 tool result 回灌,语义对齐 tool_result,见 docs/topics/hitl-approval-design.md §1)。
- web 端若要复用:把 input() 换成 async confirmer 同款 future 模式(推前端+await 回传),
  答案仍作 tool result 回灌。本工具不进 can_use_tool(它不是"批准"是"采集")。
- 不要用来问 plan 行不行(那是 ExitPlanMode)。
- multiSelect 支持多选(逗号分隔);回车默认第一项。
"""
from ..registry import tool

ASK_USER_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1, "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "header": {"type": "string", "maxLength": 12},
                    "options": {
                        "type": "array",
                        "minItems": 2, "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["label"],
                        },
                    },
                    "multiSelect": {"type": "boolean", "default": False},
                },
                "required": ["question", "header", "options"],
            },
        }
    },
    "required": ["questions"],
}


@tool(
    name="ask_user",
    description="多选问用户收集信息/澄清。不要用来问 plan 行不行(那是 ExitPlanMode)。",
    input_schema=ASK_USER_SCHEMA,
    mutates_external=False,
)
def ask_user(questions):
    answers = []
    for q in questions:
        print(f"\n[{q['header']}] {q['question']}")
        opts = q["options"]
        for i, opt in enumerate(opts):
            line = f"  {i + 1}. {opt['label']}"
            if opt.get("description"):
                line += f" - {opt['description']}"
            print(line)
        multi = q.get("multiSelect", False)
        prompt = "选择(逗号分隔多选,回车=第一项): " if multi else "选择(输入序号,回车=第一项): "
        choice = input(prompt).strip()
        if multi:
            idxs = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()] or [0]
            idxs = [i for i in idxs if 0 <= i < len(opts)] or [0]
            selected = [opts[i]["label"] for i in idxs]
        else:
            idx = (int(choice) - 1) if choice.isdigit() else 0
            idx = idx if 0 <= idx < len(opts) else 0
            selected = [opts[idx]["label"]]
        answers.append({"question": q["question"], "answer": selected})
    return answers
