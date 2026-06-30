## 进入项目目录
- cd xx/agent-development

## 查看 python 版本
- cat .python-version
- uv run python --version

## 重新同步依赖
- uv sync

## 建立报告目录
- mkdir -p reports/agent-eval/aftercare-first-pass

## 执行
```text
uv run python scripts/run_agent_evals.py \
  --suite verify_repair_core \
  --case aftercare_first_pass \
  --report-dir reports/agent-eval/aftercare-first-pass
```

## 执行结束后查看退出码
- echo $?
- 0代表成功

