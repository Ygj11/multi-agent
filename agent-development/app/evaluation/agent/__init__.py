"""端到端 Agent 行为级 Eval。

cases/*.yaml
    ↓
schemas.py
校验 Case 数据格式
    ↓
runner.py
运行真实 MainGraph，构建 Trace
    ↓
assertions.py
比较 expected 和 trace
    ↓
AgentEvalCaseResult
记录 PASS / FAIL
    ↓
report.py
计算整体指标
    ↓
baseline.py
做 CI 门禁和历史回归比较
"""

from app.evaluation.agent.runner import AgentEvalRunner

__all__ = ["AgentEvalRunner"]
