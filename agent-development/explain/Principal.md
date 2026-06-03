# principal的作用：

## 第一，作为身份可信源。

比如请求 body 里也有 tenant_id/user_id，但如果 header 里已经解析出了 Principal，系统会用 Principal 作为准绳。RequestAdapter 会校验 body 里的 tenant/user 是否和 Principal 匹配。

## 第二，作为Agent 级权限判断依据。

在 app/runtime/graph.py 的 agent selection 后，会把 principal 转回 Principal，然后调用：

AuthorizationService.check_agent_access(...)
代码在 app/auth/authorization_service.py。

也就是说，某个用户/机构能不能使用某个子 Agent，不交给 LLM 判断，而是由代码根据 Principal 判断。

## 第三，作为工具级权限判断依据。

ToolExecutor 执行工具前，会把 principal 传进工具执行 pipeline。然后校验：

工具 required_scopes
资源访问权限
pre_tool verification
比如某个工具需要 policy:read:sensitive，Principal 里没有这个 scope，就应该被拒绝。

## 第四，作为最终回答权限/脱敏依据。

VerificationService(pre_answer) 会拿到 principal/auth_context，例如 DataPermissionVerifier 会看用户有没有 policy.sensitive.read 这类 data permission，再决定敏感字段是否能返回。

## 所以 Principal 在这个项目里本质是：

用户/机构/权限的可信快照，用来贯穿 Agent 选择、工具调用、资源访问和最终回答校验。

