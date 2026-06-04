# 选择 子agent

## 意义
- 从 `app/agents/cards/*.yaml` 加载可使用的 `子agent`，形成 json格式存入 `state`
```python
payload = [card.model_dump() for card in cards]
```

## 入参
```python
intent=state.get("intent", "unknown"),
sub_intent=state.get("sub_intent"),
intent_confidence=state.get("confidence", 0.0),
entities=state.get("entities", {}),
query=state.get("rewritten_query", state["original_query"]),
is_follow_up=bool(state.get("is_follow_up")),
request_id=state.get("request_id"),
trace_id=state.get("trace_id"),
session_key=state.get("session_key"),
```

## 选择出 agent
```python
class AgentSelectionResult(BaseModel):
    """Final selection decision used by the orchestrator."""

    selected_agent: str
    confidence: float
    reason: str
    required_context: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    candidates: list[AgentCandidate] = Field(default_factory=list)
    fallback: bool = False
    selection_method: Literal["rule", "llm_router", "fallback"] = "rule"
    need_clarification: bool = False
    clarification_question: str | None = None
```
1. 对所有agent进行打分 - `match_candidates`，规则加分制度
    intent
    sub_intent
    required_entities
    capability
    query 在 card_text 中

2. 取 top-k agent - `top_candidates = candidates[: self.top_k]`

3. 使用llm（分数相差不大，则需要使用） - `_should_call_llm_router`

4. llm route

5. 规则兜底 - `_rule_selection`

6. 得到唯一 `agentcard`，检查是否有权限访问`self._check_agent_access(state, selected_card)`


```python
AuthorizationService.check_agent_access(*)
```

```text
AgentCard.access_policy = 配置/声明
check_agent_access = 执行/校验
Principal = 当前用户/机构/角色/权限
```

默认空，则直接通过 - `AuthorizationDecision(allowed=True)`

7. 结果返回




## 举例
```YAML
access_policy:
  required_roles:
    - policy_sensitive_operator
  required_scopes:
    - policy:read:sensitive
  allowed_org_types:
    - headquarter
```

```PYTHON
Principal(
    roles=["policy_sensitive_operator"],
    scopes=["policy:read:sensitive"],
    attributes={"org_type": "headquarter"}
)

```

## 思考
- _should_call_llm_router，只使用 top1 和 top2 ，合理吗？
- llm route 的提示词简单写，合理吗？
- agentCard中定义的 access_policy，需要和 Principal 强绑定，考虑Principal能有这些值取到吗？合理吗？


## !!
AgentAccessPolicy 是“按需声明约束”。不配置就不限制；配置哪项就检查哪项；配置多项时需要同时满足；denied_org_ids 是优先拒绝项。