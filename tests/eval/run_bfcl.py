"""BFCL 工具调用决策评测(本机,单轮 LLM function calling,不依赖 Docker)。

读 BFCL jsonl(exec_simple/multiple),给 LLM question+函数定义,
看返回的 tool_call 是否和 ground_truth exact_match(函数名+参数)。
从 code/ 运行:
    python tests/eval/run_bfcl.py G:/llq_dwd/BFCL_v3_exec_simple.json [limit]
"""
import os, sys, json, ast, re

_HERE = os.path.dirname(__file__)
_CODE = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _CODE)

from dotenv import load_dotenv
load_dotenv(os.path.join(_CODE, ".env"))
from openai import OpenAI

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _fix_schema(s):
    """BFCL 用 float/dict,OpenAI tools 要 number/object,递归修."""
    if isinstance(s, dict):
        t = s.get("type")
        if t == "float":
            s["type"] = "number"
        elif t == "dict":
            s["type"] = "object"
        for v in s.values():
            _fix_schema(v)
    elif isinstance(s, list):
        for x in s:
            _fix_schema(x)
    return s


def to_tools(functions):
    tools = []
    for f in functions:
        p = _fix_schema(dict(f.get("parameters", {})))
        tools.append({"type": "function", "function": {
            "name": f["name"], "description": f["description"],
            "parameters": p,
        }})
    return tools


def call_llm(question, tools):
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": question}],
        tools=tools,
    )
    tc = r.choices[0].message.tool_calls
    if not tc:
        return None, None
    try:
        return tc[0].function.name, json.loads(tc[0].function.arguments)
    except Exception:
        return tc[0].function.name, None


def parse_gt(gt):
    """用 ast.parse 正确解析 func(k=v,...),v 可能是 list/1/6 等."""
    tree = ast.parse(gt, mode="eval")
    call = tree.body
    name = call.func.id
    args = {}
    for kw in call.keywords:
        expr = ast.unparse(kw.value)
        try:
            args[kw.arg] = eval(expr, {"__builtins__": {}}, {})
        except Exception:
            args[kw.arg] = expr
    return name, args


def _val_eq(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-6
    return a == b


def match(pred_name, pred_args, gt_name, gt_args):
    if pred_name != gt_name or pred_args is None:
        return False
    if set(pred_args.keys()) != set(gt_args.keys()):
        return False
    return all(_val_eq(pred_args[k], gt_args[k]) for k in gt_args)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else r"G:/llq_dwd/BFCL_v3_exec_simple.json"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    data = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if limit:
        data = data[:limit]
    correct = 0
    for i, d in enumerate(data):
        q = d["question"][0][0]["content"] if isinstance(d["question"][0], list) else d["question"]
        tools = to_tools(d["function"])
        gt_name, gt_args = parse_gt(d["ground_truth"][0])
        try:
            pred_name, pred_args = call_llm(q, tools)
        except Exception as e:
            pred_name, pred_args = None, {"err": str(e)[:80]}
        ok = match(pred_name, pred_args, gt_name, gt_args)
        correct += ok
        if not ok:
            print(f"[{i}] {d.get('id','?')} pred={pred_name}({pred_args}) gt={gt_name}({gt_args})")
    print(f"\n{os.path.basename(path)}: {correct}/{len(data)} = {correct/len(data):.1%}")


if __name__ == "__main__":
    main()
