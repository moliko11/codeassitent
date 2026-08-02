"""跑 mock golden dataset,输出评分表(test-plan §7 验收:输出评分表)。不依赖真实 LLM。
从 code/ 目录运行:
    python tests/eval/run_mock.py
"""
import os
import sys

_HERE = os.path.dirname(__file__)                  # tests/eval/
_CODE = os.path.dirname(os.path.dirname(_HERE))    # code/
sys.path.insert(0, _HERE)                          # from golden_dataset import
sys.path.insert(0, _CODE)                          # from agent... import

from golden_dataset import MOCK_DATASET, make_scripted_adapter  # noqa: E402
from agent.tools import registry  # noqa: E402
from agent.tracing.eval import Evaluator  # noqa: E402


def main():
    ev = Evaluator(registry)
    results = ev.run(MOCK_DATASET, make_scripted_adapter())
    hdr = f"{'input':<30} {'tools':<24} {'tool_acc':>8} {'grounded':>8} {'status':>10} {'score':>6}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(f"{r.case.input[:28]:<30} {str(r.actual_tools)[:22]:<24} "
              f"{r.tool_accuracy:>8.2f} {str(r.answer_grounded):>8} {r.status:>10} {r.score:>6.2f}")
    n = len(results) or 1
    print("-" * len(hdr))
    completed = sum(1 for r in results if r.status == "completed")
    print(f"avg_score={sum(r.score for r in results)/n:.3f}  "
          f"completed={completed}/{len(results)}  "
          f"avg_tool_acc={sum(r.tool_accuracy for r in results)/n:.3f}")


if __name__ == "__main__":
    main()
