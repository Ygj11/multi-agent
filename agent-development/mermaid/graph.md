```mermaid
flowchart TD
    A([/api/chat 请求进入]) --> B[load_session<br/>加载最近消息和短期摘要]
    B --> C[save_user_message<br/>保存用户消息]
    C --> D[query_rewrite<br/>问题改写 / 实体抽取 / 追问判断]

    D -->|需要澄清| E[build_clarification_answer<br/>构造澄清问题]
    D -->|继续| F[intent_recognition<br/>意图识别 / 子意图 / 实体合并]

    F -->|需要澄清| E
    F -->|继续| G[build_orchestrator_context<br/>构建主编排上下文]

    G --> H[discover_agents<br/>发现可用子 Agent]
    H --> I[select_agent<br/>选择最合适的子 Agent]

    I -->|需要澄清| E
    I -->|继续| J[assemble_task<br/>组装 AgentTaskEnvelope]

    J --> K[dispatch_agent<br/>调用子 Agent 执行任务]
    K --> L[check_human_approval_required<br/>检查是否需要人工审批]

    L -->|需要审批| M[create_approval_request<br/>创建审批单]
    M --> N[submit_approval_request<br/>提交审批系统]
    N --> O[pause_for_approval<br/>暂停等待审批]
    O --> P[final_compliance_check<br/>最终合规检查]

    L -->|不需要审批| P
    E --> P

    P -->|通过| Q[save_assistant_message<br/>保存助手回复]
    P -->|需要重试| R[regenerate_compliant_answer<br/>重新生成合规回答]
    R --> P

    P -->|兜底| S[fallback_answer<br/>生成兜底回答]
    S --> Q

    Q --> T[compress_short_memory<br/>压缩短期记忆]
    T --> U[finalize_response<br/>整理最终响应]
    U --> V([END])
    ```