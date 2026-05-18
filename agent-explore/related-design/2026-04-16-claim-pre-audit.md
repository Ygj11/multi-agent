# AI 理赔预审 Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于 LangGraph 的混合型理赔预审 Agent，支持图片/PDF/文字多模态输入，通过 YAML 规则引擎 + LLM 推理自动校验理赔材料完整性，并在缺失材料时主动追问用户。

**Architecture:** LangGraph 状态机驱动 6 个节点（Router、ParseNode、RuleNode、AskNode、ReasonNode、ReportNode）的预审工作流。规则引擎基于 YAML 配置，确定性检查程序化执行，模糊判断交 LLM 推理。多模态处理优先使用 LLM 视觉能力直接提取图片信息，PDF 使用 PyMuPDF 解析。前端使用 Streamlit 快速出原型。

**Tech Stack:** Python 3.11+, LangGraph, LangChain, FastAPI, Streamlit, PyMuPDF, Pydantic, PyYAML, pytest

**Design Spec:** `docs/superpowers/specs/2026-04-16-claim-pre-audit-design.md`

---

## File Map

### 新建文件

| 文件 | 职责 |
|------|------|
| `pyproject.toml` | 项目依赖与构建配置 |
| `.env.example` | 环境变量模板 |
| `app/__init__.py` | 包初始化 |
| `app/config.py` | pydantic-settings 配置管理 |
| `app/models/__init__.py` | 模型包 |
| `app/models/schemas.py` | Pydantic 数据模型（PreAuditState, ExtractedDocument, RuleCheckResult 等） |
| `app/services/__init__.py` | 服务包 |
| `app/services/llm.py` | LLM 统一调用封装（ChatOpenAI 兼容） |
| `app/services/rule_engine.py` | YAML 规则加载 + 程序化校验 |
| `app/services/document_parser.py` | 多模态文档解析（图片/PDF/文本） |
| `app/agent/__init__.py` | Agent 包 |
| `app/agent/state.py` | LangGraph Agent State 定义 |
| `app/agent/nodes/__init__.py` | 节点包 |
| `app/agent/nodes/router.py` | 路由节点 — 判断输入类型 |
| `app/agent/nodes/parser.py` | 材料解析节点 — OCR/PDF 提取 |
| `app/agent/nodes/rule_checker.py` | 规则校验节点 — 逐条校验 |
| `app/agent/nodes/asker.py` | 追问节点 — 生成追问消息 |
| `app/agent/nodes/reasoner.py` | LLM 推理节点 — 综合分析 |
| `app/agent/nodes/reporter.py` | 报告生成节点 — 输出预审报告 |
| `app/agent/graph.py` | LangGraph 状态机组装 |
| `app/web/__init__.py` | Web 包 |
| `app/web/chat.py` | Streamlit 聊天界面 |
| `app/web/api.py` | FastAPI REST API 路由 |
| `app/main.py` | 应用入口 |
| `rules/medical_claim.yaml` | 医疗险理赔规则 |
| `rules/_template.yaml` | 新险种规则模板 |
| `tests/unit/__init__.py` | 测试包 |
| `tests/unit/test_config.py` | 配置测试 |
| `tests/unit/test_schemas.py` | 模型测试 |
| `tests/unit/test_rule_engine.py` | 规则引擎测试 |
| `tests/unit/test_document_parser.py` | 文档解析测试 |
| `tests/unit/test_llm_service.py` | LLM 服务测试 |
| `tests/integration/__init__.py` | 集成测试包 |
| `tests/integration/test_agent_graph.py` | Agent 图集成测试 |
| `tests/fixtures/rules/test_medical.yaml` | 测试用规则文件 |

---

### Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/models/__init__.py`
- Create: `app/services/__init__.py`
- Create: `app/agent/__init__.py`
- Create: `app/agent/nodes/__init__.py`
- Create: `app/web/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`

- [ ] **Step 1: 创建目录结构**

```bash
cd D:/agentworkspace/PythonProject/claim_pre_audit_agent
mkdir -p app/models app/services app/agent/nodes app/web
mkdir -p tests/unit tests/integration tests/fixtures/rules
mkdir -p rules
```

- [ ] **Step 2: 写 pyproject.toml**

```toml
[project]
name = "claim-pre-audit-agent"
version = "0.1.0"
description = "AI 理赔预审 Agent"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2.0",
    "langchain>=0.3.0",
    "langchain-openai>=0.2.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "streamlit>=1.38.0",
    "pymupdf>=1.24.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.5.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
    "python-multipart>=0.0.9",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]

[build-system]
requires = ["setuptools>=75.0"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: 写 .env.example**

```
# LLM 配置
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# 多模态模型（图片理解）
VISION_LLM_MODEL=qwen-vl-plus
VISION_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_LLM_API_KEY=sk-your-vision-api-key-here

# 备用模型（降级用）
FALLBACK_LLM_MODEL=qwen-plus
FALLBACK_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
FALLBACK_LLM_API_KEY=sk-your-fallback-api-key-here
```

- [ ] **Step 4: 创建所有 __init__.py**

每个 `__init__.py` 为空文件：

```bash
touch app/__init__.py app/models/__init__.py app/services/__init__.py
touch app/agent/__init__.py app/agent/nodes/__init__.py app/web/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 5: 安装依赖**

```bash
pip install -e ".[dev]"
```

Expected: 依赖安装成功

- [ ] **Step 6: 验证环境**

```bash
python -c "import langgraph; import langchain; import fastapi; import streamlit; print('OK')"
```

Expected: 输出 `OK`

- [ ] **Step 7: 提交**

```bash
git init
git add pyproject.toml .env.example app/ tests/
git commit -m "feat: project scaffolding with dependencies"
```

---

### Task 2: 配置管理 + 数据模型

**Files:**
- Create: `app/config.py`
- Create: `app/models/schemas.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_schemas.py`

- [ ] **Step 1: 写 config 测试**

```python
# tests/unit/test_config.py
import os
import pytest


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.test.com/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    from app.config import Settings

    s = Settings()
    assert s.llm_api_key == "sk-test-123"
    assert s.llm_base_url == "https://api.test.com/v1"
    assert s.llm_model == "test-model"


def test_settings_has_defaults():
    from app.config import Settings

    s = Settings(llm_api_key="sk-test")
    assert s.llm_provider == "deepseek"
    assert s.llm_timeout == 30
    assert s.max_ask_rounds == 3
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: 实现 config.py**

```python
# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # LLM 主模型
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout: int = 30

    # 多模态模型
    vision_llm_model: str = ""
    vision_llm_base_url: str = ""
    vision_llm_api_key: str = ""

    # 备用模型（降级）
    fallback_llm_model: str = ""
    fallback_llm_base_url: str = ""
    fallback_llm_api_key: str = ""

    # 业务配置
    max_ask_rounds: int = 3
    rules_dir: str = "rules"


settings = Settings()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_config.py -v
```

Expected: PASS

- [ ] **Step 5: 写 schemas 测试**

```python
# tests/unit/test_schemas.py
import pytest
from app.models.schemas import (
    ExtractedDocument,
    RuleCheckResult,
    AuditReport,
    CheckStatus,
    RiskLevel,
)


def test_extracted_document_creation():
    doc = ExtractedDocument(
        doc_type="发票",
        source_file="invoice.jpg",
        confidence=0.95,
        fields={"患者姓名": "张三", "金额": 1500.00},
        raw_text="某医院发票...",
    )
    assert doc.doc_type == "发票"
    assert doc.confidence == 0.95
    assert doc.fields["患者姓名"] == "张三"


def test_rule_check_result_pass():
    result = RuleCheckResult(
        rule_type="field_present",
        field="发票号码",
        status=CheckStatus.PASS,
        message="",
    )
    assert result.status == CheckStatus.PASS


def test_rule_check_result_fail():
    result = RuleCheckResult(
        rule_type="field_present",
        field="医院公章",
        status=CheckStatus.FAIL,
        message="发票缺少医院公章",
    )
    assert result.status == CheckStatus.FAIL


def test_audit_report():
    report = AuditReport(
        claim_type="medical_claim",
        overall_status=CheckStatus.FAIL,
        risk_level=RiskLevel.MEDIUM,
        check_results=[],
        summary="缺少公章",
        suggestions=["请补充医院盖章"],
    )
    assert report.risk_level == RiskLevel.MEDIUM
    assert len(report.suggestions) == 1
```

- [ ] **Step 6: 运行测试确认失败**

```bash
pytest tests/unit/test_schemas.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 7: 实现 schemas.py**

```python
# app/models/schemas.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    MISSING = "missing"
    SKIP = "skip"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ExtractedDocument:
    doc_type: str
    source_file: str
    confidence: float
    fields: dict[str, Any]
    raw_text: str


@dataclass
class RuleCheckResult:
    rule_type: str
    field: str
    status: CheckStatus
    message: str
    detail: str = ""


@dataclass
class AuditReport:
    claim_type: str
    overall_status: CheckStatus
    risk_level: RiskLevel
    check_results: list[RuleCheckResult]
    summary: str
    suggestions: list[str] = field(default_factory=list)
```

- [ ] **Step 8: 运行测试确认通过**

```bash
pytest tests/unit/test_schemas.py -v
```

Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add app/config.py app/models/schemas.py tests/unit/test_config.py tests/unit/test_schemas.py
git commit -m "feat: add config management and data models"
```

---

### Task 3: LLM 服务

**Files:**
- Create: `app/services/llm.py`
- Create: `tests/unit/test_llm_service.py`

- [ ] **Step 1: 写 LLM 服务测试**

```python
# tests/unit/test_llm_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_get_chat_llm():
    from app.services.llm import LLMServer
    from app.config import Settings

    s = Settings(llm_api_key="sk-test", llm_base_url="https://api.test.com/v1", llm_model="test-model")
    server = LLMServer(s)
    llm = server.get_chat_llm()
    assert llm is not None
    assert llm.model_name == "test-model"


def test_get_vision_llm_falls_back_to_chat():
    from app.services.llm import LLMServer
    from app.config import Settings

    s = Settings(
        llm_api_key="sk-test",
        llm_base_url="https://api.test.com/v1",
        llm_model="test-model",
        vision_llm_model="",
    )
    server = LLMServer(s)
    llm = server.get_vision_llm()
    assert llm.model_name == "test-model"


def test_get_vision_llm_uses_separate_model():
    from app.services.llm import LLMServer
    from app.config import Settings

    s = Settings(
        llm_api_key="sk-test",
        llm_base_url="https://api.test.com/v1",
        llm_model="test-model",
        vision_llm_model="qwen-vl-plus",
        vision_llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        vision_llm_api_key="sk-vision",
    )
    server = LLMServer(s)
    llm = server.get_vision_llm()
    assert llm.model_name == "qwen-vl-plus"


@pytest.mark.asyncio
async def test_analyze_claim_returns_dict():
    from app.services.llm import LLMServer
    from app.config import Settings

    s = Settings(
        llm_api_key="sk-test",
        llm_base_url="https://api.test.com/v1",
        llm_model="test-model",
    )
    server = LLMServer(s)

    mock_response = MagicMock()
    mock_response.content = '{"risk": "low", "summary": "材料齐全"}'

    with patch.object(server, "get_chat_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await server.analyze_claim("测试上下文", ["规则1"])
        assert isinstance(result, dict)
        assert result["risk"] == "low"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_llm_service.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: 实现 llm.py**

```python
# app/services/llm.py
import json
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMServer:
    """统一 LLM 调用，支持多模型切换和降级"""

    def __init__(self, settings: Settings):
        self._settings = settings

    def get_chat_llm(self) -> ChatOpenAI:
        return ChatOpenAI(
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url,
            model=self._settings.llm_model,
            timeout=self._settings.llm_timeout,
        )

    def get_vision_llm(self) -> ChatOpenAI:
        if self._settings.vision_llm_model:
            return ChatOpenAI(
                api_key=self._settings.vision_llm_api_key or self._settings.llm_api_key,
                base_url=self._settings.vision_llm_base_url or self._settings.llm_base_url,
                model=self._settings.vision_llm_model,
                timeout=self._settings.llm_timeout,
            )
        return self.get_chat_llm()

    def get_fallback_llm(self) -> ChatOpenAI | None:
        if not self._settings.fallback_llm_model:
            return None
        return ChatOpenAI(
            api_key=self._settings.fallback_llm_api_key or self._settings.llm_api_key,
            base_url=self._settings.fallback_llm_base_url or self._settings.llm_base_url,
            model=self._settings.fallback_llm_model,
            timeout=self._settings.llm_timeout,
        )

    async def analyze_claim(self, context: str, rules: list[str]) -> dict[str, Any]:
        llm = self.get_chat_llm()
        messages = [
            SystemMessage(content="你是理赔审核专家。请根据提供的材料和规则进行分析，返回 JSON 格式结果。"),
            HumanMessage(content=f"规则：\n{chr(10).join(rules)}\n\n材料：\n{context}"),
        ]
        response = await llm.ainvoke(messages)
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return {"risk": "unknown", "summary": response.content}

    async def extract_from_image(self, image_data: str, prompt: str) -> dict[str, Any]:
        llm = self.get_vision_llm()
        messages = [
            SystemMessage(content="请从图片中提取结构化信息，返回 JSON 格式。"),
            HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data}},
            ]),
        ]
        response = await llm.ainvoke(messages)
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return {"raw_text": response.content, "confidence": 0.5}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_llm_service.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/llm.py tests/unit/test_llm_service.py
git commit -m "feat: add LLM service with multi-model support"
```

---

### Task 4: 规则引擎

**Files:**
- Create: `rules/medical_claim.yaml`
- Create: `rules/_template.yaml`
- Create: `tests/fixtures/rules/test_medical.yaml`
- Create: `app/services/rule_engine.py`
- Create: `tests/unit/test_rule_engine.py`

- [ ] **Step 1: 写规则 YAML 文件**

```yaml
# rules/medical_claim.yaml
claim_type: medical_claim
display_name: 医疗险理赔

required_documents:
  - name: 医疗费用发票
    checks:
      - type: field_present
        field: "发票号码"
        message: "发票缺少发票号码"
      - type: field_present
        field: "医院公章"
        message: "发票缺少医院公章"
      - type: field_present
        field: "金额"
        message: "发票缺少金额"
      - type: date_in_range
        field: "发票日期"
        within_coverage: true
        message: "发票日期不在保障期内"

  - name: 诊断证明
    checks:
      - type: field_present
        field: "诊断描述"
        message: "诊断证明缺少诊断描述"
      - type: field_present
        field: "医生签名"
        message: "诊断证明缺少医生签名"
      - type: field_present
        field: "医院盖章"
        message: "诊断证明缺少医院盖章"

  - name: 费用清单
    checks:
      - type: field_present
        field: "费用明细"
        message: "费用清单缺少明细"
      - type: amount_consistent
        field: "总金额"
        match_with: "发票.金额"
        message: "费用清单总金额与发票不一致"

cross_document_checks:
  - type: name_consistency
    fields: ["患者姓名"]
    across: ["医疗费用发票", "诊断证明"]
    message: "各材料中患者姓名不一致"
```

```yaml
# rules/_template.yaml
# 新险种规则模板 — 复制此文件并修改
claim_type: _template
display_name: 新险种名称

required_documents:
  - name: 材料名称
    checks:
      - type: field_present
        field: "字段名"
        message: "缺少字段名"

cross_document_checks: []
```

```yaml
# tests/fixtures/rules/test_medical.yaml
claim_type: test_medical
display_name: 测试医疗险

required_documents:
  - name: 发票
    checks:
      - type: field_present
        field: "金额"
        message: "发票缺少金额"
  - name: 诊断书
    checks:
      - type: field_present
        field: "诊断"
        message: "诊断书缺少诊断描述"

cross_document_checks: []
```

- [ ] **Step 2: 写规则引擎测试**

```python
# tests/unit/test_rule_engine.py
import pytest
from pathlib import Path

from app.services.rule_engine import RuleEngine
from app.models.schemas import ExtractedDocument, CheckStatus


@pytest.fixture
def engine():
    rules_dir = Path("tests/fixtures/rules")
    return RuleEngine(rules_dir=rules_dir)


def test_load_rules(engine):
    rules = engine.load_rules("test_medical")
    assert rules["claim_type"] == "test_medical"
    assert len(rules["required_documents"]) == 2


def test_load_rules_not_found(engine):
    rules = engine.load_rules("nonexistent")
    assert rules is None


def test_check_field_present_pass():
    engine = RuleEngine()
    doc = ExtractedDocument(
        doc_type="发票",
        source_file="invoice.jpg",
        confidence=0.9,
        fields={"金额": "1500.00"},
        raw_text="",
    )
    result = engine._check_field_present(doc, {"field": "金额"})
    assert result.status == CheckStatus.PASS


def test_check_field_present_fail():
    engine = RuleEngine()
    doc = ExtractedDocument(
        doc_type="发票",
        source_file="invoice.jpg",
        confidence=0.9,
        fields={},
        raw_text="",
    )
    result = engine._check_field_present(doc, {"field": "金额"})
    assert result.status == CheckStatus.FAIL


def test_check_name_consistency_pass():
    engine = RuleEngine()
    docs = [
        ExtractedDocument("发票", "a.jpg", 0.9, {"患者姓名": "张三"}, ""),
        ExtractedDocument("诊断书", "b.jpg", 0.9, {"患者姓名": "张三"}, ""),
    ]
    results = engine._check_name_consistency(docs, {"fields": ["患者姓名"], "across": ["发票", "诊断书"]})
    assert all(r.status == CheckStatus.PASS for r in results)


def test_check_name_consistency_fail():
    engine = RuleEngine()
    docs = [
        ExtractedDocument("发票", "a.jpg", 0.9, {"患者姓名": "张三"}, ""),
        ExtractedDocument("诊断书", "b.jpg", 0.9, {"患者姓名": "李四"}, ""),
    ]
    results = engine._check_name_consistency(docs, {"fields": ["患者姓名"], "across": ["发票", "诊断书"]})
    assert any(r.status == CheckStatus.FAIL for r in results)


def test_check_documents_against_rules(engine):
    docs = [
        ExtractedDocument("发票", "a.jpg", 0.9, {"金额": "1500.00"}, ""),
        ExtractedDocument("诊断书", "b.jpg", 0.9, {"诊断": "感冒"}, ""),
    ]
    results = engine.check_documents("test_medical", docs)
    assert all(r.status == CheckStatus.PASS for r in results)


def test_check_documents_missing_field(engine):
    docs = [
        ExtractedDocument("发票", "a.jpg", 0.9, {}, ""),
        ExtractedDocument("诊断书", "b.jpg", 0.9, {"诊断": "感冒"}, ""),
    ]
    results = engine.check_documents("test_medical", docs)
    assert any(r.status == CheckStatus.FAIL for r in results)
```

- [ ] **Step 3: 运行测试确认失败**

```bash
pytest tests/unit/test_rule_engine.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 4: 实现 rule_engine.py**

```python
# app/services/rule_engine.py
import logging
from pathlib import Path
from typing import Any

import yaml

from app.models.schemas import CheckStatus, ExtractedDocument, RuleCheckResult

logger = logging.getLogger(__name__)


class RuleEngine:
    """YAML 规则加载 + 程序化校验"""

    def __init__(self, rules_dir: Path | str | None = None):
        if rules_dir is None:
            from app.config import settings
            rules_dir = settings.rules_dir
        self._rules_dir = Path(rules_dir)

    def load_rules(self, claim_type: str) -> dict[str, Any] | None:
        path = self._rules_dir / f"{claim_type}.yaml"
        if not path.exists():
            logger.warning("规则文件不存在: %s", path)
            return None
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def check_documents(
        self, claim_type: str, documents: list[ExtractedDocument]
    ) -> list[RuleCheckResult]:
        rules = self.load_rules(claim_type)
        if rules is None:
            return []

        results: list[RuleCheckResult] = []

        # 逐文档校验
        for doc_rule in rules.get("required_documents", []):
            doc_name = doc_rule["name"]
            doc = self._find_doc_by_name(documents, doc_name)
            if doc is None:
                for check in doc_rule.get("checks", []):
                    results.append(RuleCheckResult(
                        rule_type=check["type"],
                        field=check.get("field", ""),
                        status=CheckStatus.MISSING,
                        message=f"缺少材料: {doc_name}",
                    ))
                continue

            for check in doc_rule.get("checks", []):
                result = self._run_check(doc, check, documents)
                results.append(result)

        # 跨文档校验
        for cross_check in rules.get("cross_document_checks", []):
            cross_results = self._run_cross_check(documents, cross_check)
            results.extend(cross_results)

        return results

    def _find_doc_by_name(
        self, documents: list[ExtractedDocument], name: str
    ) -> ExtractedDocument | None:
        name_lower = name.lower()
        for doc in documents:
            if name_lower in doc.doc_type.lower():
                return doc
        return None

    def _run_check(
        self, doc: ExtractedDocument, check: dict, all_docs: list[ExtractedDocument]
    ) -> RuleCheckResult:
        check_type = check["type"]
        message = check.get("message", "")

        if check_type == "field_present":
            return self._check_field_present(doc, check, message)
        elif check_type == "amount_consistent":
            return self._check_amount_consistent(doc, check, all_docs, message)
        else:
            return RuleCheckResult(
                rule_type=check_type,
                field=check.get("field", ""),
                status=CheckStatus.SKIP,
                message=f"未知规则类型: {check_type}",
            )

    def _check_field_present(
        self, doc: ExtractedDocument, check: dict, message: str = ""
    ) -> RuleCheckResult:
        field_name = check["field"]
        value = doc.fields.get(field_name)
        if value is not None and str(value).strip():
            return RuleCheckResult(
                rule_type="field_present",
                field=field_name,
                status=CheckStatus.PASS,
                message="",
            )
        return RuleCheckResult(
            rule_type="field_present",
            field=field_name,
            status=CheckStatus.FAIL,
            message=message or f"缺少字段: {field_name}",
        )

    def _check_amount_consistent(
        self,
        doc: ExtractedDocument,
        check: dict,
        all_docs: list[ExtractedDocument],
        message: str = "",
    ) -> RuleCheckResult:
        field = check.get("field", "")
        match_path = check.get("match_with", "")
        current_val = doc.fields.get(field)

        # match_with 格式: "发票.金额" — 解析目标文档和字段
        if "." in match_path:
            target_doc_name, target_field = match_path.split(".", 1)
            target_doc = self._find_doc_by_name(all_docs, target_doc_name)
            if target_doc:
                target_val = target_doc.fields.get(target_field)
            else:
                target_val = None
        else:
            target_val = None

        if current_val is not None and target_val is not None:
            try:
                if float(str(current_val).replace(",", "")) == float(
                    str(target_val).replace(",", "")
                ):
                    return RuleCheckResult(
                        rule_type="amount_consistent",
                        field=field,
                        status=CheckStatus.PASS,
                        message="",
                    )
            except ValueError:
                pass

        return RuleCheckResult(
            rule_type="amount_consistent",
            field=field,
            status=CheckStatus.FAIL,
            message=message or f"{field} 不一致",
        )

    def _run_cross_check(
        self, documents: list[ExtractedDocument], check: dict
    ) -> list[RuleCheckResult]:
        check_type = check.get("type", "")
        if check_type == "name_consistency":
            return self._check_name_consistency(documents, check)
        return []

    def _check_name_consistency(
        self, documents: list[ExtractedDocument], check: dict
    ) -> list[RuleCheckResult]:
        fields_to_check = check.get("fields", [])
        message = check.get("message", "姓名不一致")

        results = []
        for field_name in fields_to_check:
            values = set()
            for doc in documents:
                val = doc.fields.get(field_name)
                if val:
                    values.add(str(val).strip())

            if len(values) <= 1:
                results.append(RuleCheckResult(
                    rule_type="name_consistency",
                    field=field_name,
                    status=CheckStatus.PASS,
                    message="",
                ))
            else:
                results.append(RuleCheckResult(
                    rule_type="name_consistency",
                    field=field_name,
                    status=CheckStatus.FAIL,
                    message=message,
                ))
        return results
```

- [ ] **Step 5: 运行测试确认通过**

```bash
pytest tests/unit/test_rule_engine.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/services/rule_engine.py rules/ tests/unit/test_rule_engine.py tests/fixtures/
git commit -m "feat: add rule engine with YAML config and field checks"
```

---

### Task 5: 文档解析服务

**Files:**
- Create: `app/services/document_parser.py`
- Create: `tests/unit/test_document_parser.py`

- [ ] **Step 1: 写文档解析测试**

```python
# tests/unit/test_document_parser.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import ExtractedDocument
from app.services.document_parser import DocumentParser


def test_detect_file_type_image():
    parser = DocumentParser()
    assert parser.detect_file_type("invoice.jpg") == "image"
    assert parser.detect_file_type("photo.png") == "image"
    assert parser.detect_file_type("scan.jpeg") == "image"


def test_detect_file_type_pdf():
    parser = DocumentParser()
    assert parser.detect_file_type("report.pdf") == "pdf"


def test_detect_file_type_unknown():
    parser = DocumentParser()
    assert parser.detect_file_type("data.csv") == "unknown"


def test_parse_pdf_text(tmp_path):
    parser = DocumentParser()
    pdf_path = tmp_path / "test.txt"
    pdf_path.write_text("患者：张三，金额：1500元", encoding="utf-8")
    # PyMuPDF 需要 .pdf 格式，这里只测试文本提取的辅助逻辑
    text = parser._clean_extracted_text("患者：张三，金额：1500元")
    assert "张三" in text


@pytest.mark.asyncio
async def test_parse_image_with_llm():
    parser = DocumentParser()

    mock_llm_server = MagicMock()
    mock_llm_server.extract_from_image = AsyncMock(return_value={
        "doc_type": "发票",
        "fields": {"患者姓名": "张三", "金额": "1500.00"},
    })

    result = await parser.parse_image(
        llm_server=mock_llm_server,
        image_data="data:image/jpeg;base64,/9j/...",
        filename="invoice.jpg",
    )
    assert isinstance(result, ExtractedDocument)
    assert result.doc_type == "发票"
    assert result.fields["患者姓名"] == "张三"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_document_parser.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: 实现 document_parser.py**

```python
# app/services/document_parser.py
import base64
import logging
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from app.models.schemas import ExtractedDocument

logger = logging.getLogger(__name__)

# 发票/诊断书等常见文档的提取 prompt
EXTRACTION_PROMPT = """请从这份文档图片中提取以下信息，返回 JSON 格式：
{
    "doc_type": "文档类型（如：发票、诊断证明、费用清单）",
    "fields": {
        "患者姓名": "",
        "金额": "",
        "日期": "",
        "医院名称": "",
        "诊断描述": "",
        "发票号码": "",
        "是否有公章": true/false,
        "是否有医生签名": true/false,
        "是否有医院盖章": true/false
    }
}
只提取图片中能明确识别的字段，无法识别的不返回。"""


class DocumentParser:
    """多模态文档解析：图片（LLM视觉）/ PDF（PyMuPDF + LLM）"""

    SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

    def detect_file_type(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext in self.SUPPORTED_IMAGE_EXTENSIONS:
            return "image"
        elif ext == ".pdf":
            return "pdf"
        return "unknown"

    async def parse_image(
        self, llm_server: Any, image_data: str, filename: str
    ) -> ExtractedDocument:
        """使用 LLM 多模态能力从图片提取结构化信息"""
        result = await llm_server.extract_from_image(image_data, EXTRACTION_PROMPT)

        return ExtractedDocument(
            doc_type=result.get("doc_type", Path(filename).stem),
            source_file=filename,
            confidence=result.get("confidence", 0.8),
            fields=result.get("fields", {}),
            raw_text=result.get("raw_text", str(result)),
        )

    def parse_pdf(self, pdf_path: str | Path) -> str:
        """使用 PyMuPDF 提取 PDF 文本"""
        doc = fitz.open(str(pdf_path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return self._clean_extracted_text("\n".join(text_parts))

    async def parse_pdf_with_llm(
        self, llm_server: Any, pdf_path: str | Path, filename: str
    ) -> ExtractedDocument:
        """PDF 文本提取 + LLM 结构化"""
        text = self.parse_pdf(pdf_path)
        result = await llm_server.analyze_claim(
            context=text,
            rules=["请从以下医疗文档文本中提取结构化字段信息，返回 JSON 格式，包含 doc_type 和 fields"],
        )

        return ExtractedDocument(
            doc_type=result.get("doc_type", Path(filename).stem),
            source_file=filename,
            confidence=result.get("confidence", 0.7),
            fields=result.get("fields", {}),
            raw_text=text,
        )

    def encode_image_to_base64(self, image_bytes: bytes) -> str:
        """将图片字节编码为 base64 data URL"""
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def _clean_extracted_text(self, text: str) -> str:
        """清理提取的文本"""
        return text.strip()

    def parse_image_sync(self, llm_server: Any, image_data: str, filename: str) -> ExtractedDocument:
        """同步版本的图片解析（供 Streamlit 调用）"""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.parse_image(llm_server, image_data, filename)
        )

    def parse_pdf_sync(self, llm_server: Any, pdf_path: str | Path, filename: str) -> ExtractedDocument:
        """同步版本的 PDF 解析（供 Streamlit 调用）"""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.parse_pdf_with_llm(llm_server, pdf_path, filename)
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_document_parser.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/document_parser.py tests/unit/test_document_parser.py
git commit -m "feat: add document parser for images and PDFs"
```

---

### Task 6: Agent 状态 + 路由节点

**Files:**
- Create: `app/agent/state.py`
- Create: `app/agent/nodes/router.py`
- Create: `tests/unit/test_router.py`

- [ ] **Step 1: 实现 state.py**

```python
# app/agent/state.py
from typing import Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.schemas import AuditReport, ExtractedDocument, RuleCheckResult


class PreAuditState(dict):
    """LangGraph Agent 状态"""

    # 会话信息
    session_id: str
    messages: Annotated[list[BaseMessage], add_messages]

    # 用户输入
    documents: list[ExtractedDocument]
    claim_type: str
    user_input: str

    # 各节点产出
    extracted_info: dict
    rule_check_results: list[RuleCheckResult]
    llm_analysis: dict

    # 流程控制
    missing_items: list[str]
    needs_clarification: bool
    ask_round: int  # 当前追问轮次
    audit_report: AuditReport | None
    is_complete: bool
    input_type: str  # "text" / "file" / "claim_start"
```

- [ ] **Step 2: 写路由节点测试**

```python
# tests/unit/test_router.py
import pytest
from app.agent.nodes.router import router_node, InputType


def test_router_detects_text_input():
    state = {
        "user_input": "我想咨询一下理赔流程",
        "documents": [],
        "input_type": "",
    }
    result = router_node(state)
    assert result["input_type"] == InputType.TEXT


def test_router_detects_file_input():
    state = {
        "user_input": "这是我的发票",
        "documents": [{"doc_type": "发票", "source_file": "inv.jpg"}],
        "input_type": "",
    }
    result = router_node(state)
    assert result["input_type"] == InputType.FILE


def test_router_detects_claim_start():
    state = {
        "user_input": "开始医疗险理赔预审",
        "documents": [],
        "input_type": "",
        "claim_type": "",
    }
    result = router_node(state)
    assert result["input_type"] == InputType.CLAIM_START
```

- [ ] **Step 3: 运行测试确认失败**

```bash
pytest tests/unit/test_router.py -v
```

Expected: FAIL

- [ ] **Step 4: 实现 router.py**

```python
# app/agent/nodes/router.py
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class InputType(str, Enum):
    TEXT = "text"
    FILE = "file"
    CLAIM_START = "claim_start"


# 理赔相关关键词
CLAIM_KEYWORDS = ["理赔", "预审", "审核", "报案", "申请"]


def router_node(state: dict) -> dict:
    """路由节点：判断用户输入类型"""
    user_input = state.get("user_input", "")
    documents = state.get("documents", [])
    claim_type = state.get("claim_type", "")

    # 已有材料上传 → 走文件处理流程
    if documents:
        return {"input_type": InputType.FILE}

    # 包含理赔关键词且尚未开始 → 开始预审流程
    if any(kw in user_input for kw in CLAIM_KEYWORDS) and not claim_type:
        return {"input_type": InputType.CLAIM_START}

    # 默认纯文字对话
    return {"input_type": InputType.TEXT}
```

- [ ] **Step 5: 运行测试确认通过**

```bash
pytest tests/unit/test_router.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/agent/state.py app/agent/nodes/router.py tests/unit/test_router.py
git commit -m "feat: add agent state and router node"
```

---

### Task 7: 材料解析节点

**Files:**
- Create: `app/agent/nodes/parser.py`
- Create: `tests/unit/test_parser_node.py`

- [ ] **Step 1: 写解析节点测试**

```python
# tests/unit/test_parser_node.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.nodes.parser import parser_node
from app.models.schemas import ExtractedDocument


@pytest.mark.asyncio
async def test_parser_extracts_from_documents():
    mock_llm = MagicMock()
    mock_llm.extract_from_image = AsyncMock(return_value={
        "doc_type": "发票",
        "fields": {"患者姓名": "张三", "金额": "1500.00"},
    })

    state = {
        "documents": [ExtractedDocument(
            doc_type="unknown",
            source_file="invoice.jpg",
            confidence=0.0,
            fields={},
            raw_text="",
        )],
        "extracted_info": {},
    }
    result = await parser_node(state, llm_server=mock_llm)
    assert "发票" in result["extracted_info"]


@pytest.mark.asyncio
async def test_parser_skips_already_extracted():
    mock_llm = MagicMock()
    state = {
        "documents": [ExtractedDocument(
            doc_type="发票",
            source_file="invoice.jpg",
            confidence=0.95,
            fields={"患者姓名": "张三"},
            raw_text="已提取",
        )],
        "extracted_info": {},
    }
    result = await parser_node(state, llm_server=mock_llm)
    # 已提取的高置信度文档不应再次调用 LLM
    mock_llm.extract_from_image.assert_not_called()
    assert "发票" in result["extracted_info"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_parser_node.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 parser.py**

```python
# app/agent/nodes/parser.py
import logging

from app.models.schemas import ExtractedDocument

logger = logging.getLogger(__name__)

# 置信度阈值，高于此值视为已提取
CONFIDENCE_THRESHOLD = 0.7


async def parser_node(state: dict, llm_server=None) -> dict:
    """材料解析节点：对上传文档进行 OCR/结构化提取"""
    documents: list[ExtractedDocument] = state.get("documents", [])
    extracted_info: dict = dict(state.get("extracted_info", {}))
    results: list[ExtractedDocument] = []

    for doc in documents:
        # 高置信度文档跳过
        if doc.confidence >= CONFIDENCE_THRESHOLD and doc.fields:
            results.append(doc)
            continue

        # 需要重新提取
        if llm_server and doc.source_file:
            try:
                extracted = await _extract_with_llm(llm_server, doc)
                results.append(extracted)
            except Exception as e:
                logger.error("提取失败 %s: %s", doc.source_file, e)
                results.append(doc)
        else:
            results.append(doc)

    # 按文档类型组织提取结果
    for doc in results:
        key = doc.doc_type or doc.source_file
        extracted_info[key] = doc.fields

    return {
        "documents": results,
        "extracted_info": extracted_info,
    }


async def _extract_with_llm(llm_server, doc: ExtractedDocument) -> ExtractedDocument:
    """使用 LLM 重新提取文档信息"""
    from app.services.document_parser import DocumentParser

    parser = DocumentParser()
    file_type = parser.detect_file_type(doc.source_file)

    if file_type == "image":
        # 实际使用时 image_data 来自文件上传
        return doc  # 占位：在 Web 层已预处理为 base64
    elif file_type == "pdf":
        return doc  # 占位：PDF 在上传时已解析
    return doc
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_parser_node.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/agent/nodes/parser.py tests/unit/test_parser_node.py
git commit -m "feat: add parser node for document extraction"
```

---

### Task 8: 规则校验节点 + 追问节点

**Files:**
- Create: `app/agent/nodes/rule_checker.py`
- Create: `app/agent/nodes/asker.py`
- Create: `tests/unit/test_rule_checker_node.py`
- Create: `tests/unit/test_asker_node.py`

- [ ] **Step 1: 写规则校验节点测试**

```python
# tests/unit/test_rule_checker_node.py
import pytest
from pathlib import Path

from app.agent.nodes.rule_checker import rule_checker_node
from app.models.schemas import ExtractedDocument, CheckStatus


def test_rule_checker_all_pass():
    state = {
        "claim_type": "test_medical",
        "documents": [
            ExtractedDocument("发票", "a.jpg", 0.9, {"金额": "1500"}, ""),
            ExtractedDocument("诊断书", "b.jpg", 0.9, {"诊断": "感冒"}, ""),
        ],
        "rule_check_results": [],
        "missing_items": [],
        "needs_clarification": False,
    }
    result = rule_checker_node(state, rules_dir=Path("tests/fixtures/rules"))
    assert result["needs_clarification"] is False
    assert len(result["missing_items"]) == 0


def test_rule_checker_has_missing():
    state = {
        "claim_type": "test_medical",
        "documents": [
            ExtractedDocument("发票", "a.jpg", 0.9, {}, ""),
        ],
        "rule_check_results": [],
        "missing_items": [],
        "needs_clarification": False,
    }
    result = rule_checker_node(state, rules_dir=Path("tests/fixtures/rules"))
    assert result["needs_clarification"] is True
    assert len(result["missing_items"]) > 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_rule_checker_node.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 rule_checker.py**

```python
# app/agent/nodes/rule_checker.py
import logging
from pathlib import Path
from typing import Any

from app.models.schemas import CheckStatus, ExtractedDocument, RuleCheckResult
from app.services.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


def rule_checker_node(state: dict, rules_dir: Path | str | None = None) -> dict:
    """规则校验节点：加载规则文件并逐条校验材料"""
    claim_type = state.get("claim_type", "")
    documents: list[ExtractedDocument] = state.get("documents", [])

    engine = RuleEngine(rules_dir=rules_dir)
    results = engine.check_documents(claim_type, documents)

    # 收集缺失项
    missing_items = []
    for r in results:
        if r.status in (CheckStatus.FAIL, CheckStatus.MISSING):
            missing_items.append(r.message or f"{r.field} 不通过")

    needs_clarification = len(missing_items) > 0

    return {
        "rule_check_results": results,
        "missing_items": missing_items,
        "needs_clarification": needs_clarification,
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_rule_checker_node.py -v
```

Expected: PASS

- [ ] **Step 5: 写追问节点测试**

```python
# tests/unit/test_asker_node.py
import pytest
from langchain_core.messages import AIMessage

from app.agent.nodes.asker import asker_node
from app.models.schemas import CheckStatus, RuleCheckResult


def test_asker_generates_clarification():
    state = {
        "messages": [],
        "missing_items": ["发票缺少医院公章", "缺少费用清单"],
        "ask_round": 0,
        "rule_check_results": [
            RuleCheckResult("field_present", "公章", CheckStatus.FAIL, "发票缺少医院公章"),
        ],
    }
    result = asker_node(state)
    assert len(result["messages"]) > 0
    assert any("公章" in str(m.content) or "费用清单" in str(m.content) for m in result["messages"])


def test_asker_stops_after_max_rounds():
    state = {
        "messages": [],
        "missing_items": ["发票缺少医院公章"],
        "ask_round": 3,
        "rule_check_results": [],
    }
    result = asker_node(state)
    # 超过最大轮次，应强制完成
    assert result["needs_clarification"] is False
    assert result["is_complete"] is False  # 还需走推理和报告
```

- [ ] **Step 6: 运行测试确认失败**

```bash
pytest tests/unit/test_asker_node.py -v
```

Expected: FAIL

- [ ] **Step 7: 实现 asker.py**

```python
# app/agent/nodes/asker.py
import logging

from langchain_core.messages import AIMessage

from app.config import settings

logger = logging.getLogger(__name__)


def asker_node(state: dict) -> dict:
    """追问节点：向用户确认缺失材料"""
    missing_items: list[str] = state.get("missing_items", [])
    ask_round = state.get("ask_round", 0)
    messages = list(state.get("messages", []))

    max_rounds = settings.max_ask_rounds

    # 超过最大追问轮次，强制继续
    if ask_round >= max_rounds:
        return {
            "needs_clarification": False,
            "ask_round": ask_round,
        }

    # 生成追问消息
    if missing_items:
        items_text = "\n".join(f"  - {item}" for item in missing_items)
        clarification = f"预审发现以下问题，请您补充：\n{items_text}\n\n您可以上传补充材料或提供更多说明。"
        messages.append(AIMessage(content=clarification))

    return {
        "messages": messages,
        "needs_clarification": True,
        "ask_round": ask_round + 1,
    }
```

- [ ] **Step 8: 运行测试确认通过**

```bash
pytest tests/unit/test_asker_node.py -v
```

Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add app/agent/nodes/rule_checker.py app/agent/nodes/asker.py tests/unit/test_rule_checker_node.py tests/unit/test_asker_node.py
git commit -m "feat: add rule checker and asker nodes"
```

---

### Task 9: 推理节点 + 报告节点

**Files:**
- Create: `app/agent/nodes/reasoner.py`
- Create: `app/agent/nodes/reporter.py`
- Create: `tests/unit/test_reasoner_node.py`
- Create: `tests/unit/test_reporter_node.py`

- [ ] **Step 1: 写推理节点测试**

```python
# tests/unit/test_reasoner_node.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.nodes.reasoner import reasoner_node
from app.models.schemas import CheckStatus, RuleCheckResult


@pytest.mark.asyncio
async def test_reasoner_analyzes_documents():
    mock_llm = MagicMock()
    mock_llm.analyze_claim = AsyncMock(return_value={
        "risk": "low",
        "summary": "材料齐全，符合保障范围",
        "suggestions": [],
    })

    state = {
        "claim_type": "medical_claim",
        "extracted_info": {"发票": {"金额": "1500", "患者姓名": "张三"}},
        "rule_check_results": [
            RuleCheckResult("field_present", "金额", CheckStatus.PASS, ""),
        ],
        "llm_analysis": {},
        "missing_items": [],
    }
    result = await reasoner_node(state, llm_server=mock_llm)
    assert result["llm_analysis"]["risk"] == "low"


@pytest.mark.asyncio
async def test_reasoner_handles_empty_documents():
    mock_llm = MagicMock()
    mock_llm.analyze_claim = AsyncMock(return_value={
        "risk": "high",
        "summary": "无材料可供审核",
        "suggestions": ["请上传理赔材料"],
    })

    state = {
        "claim_type": "medical_claim",
        "extracted_info": {},
        "rule_check_results": [],
        "llm_analysis": {},
        "missing_items": ["缺少所有材料"],
    }
    result = await reasoner_node(state, llm_server=mock_llm)
    assert result["llm_analysis"]["risk"] == "high"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_reasoner_node.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 reasoner.py**

```python
# app/agent/nodes/reasoner.py
import json
import logging

from app.models.schemas import CheckStatus, RuleCheckResult

logger = logging.getLogger(__name__)


async def reasoner_node(state: dict, llm_server=None) -> dict:
    """LLM 推理节点：综合分析材料与保障范围的匹配度"""
    extracted_info = state.get("extracted_info", {})
    check_results: list[RuleCheckResult] = state.get("rule_check_results", [])
    claim_type = state.get("claim_type", "")

    # 如果没有 LLM，使用规则引擎结果直接判断
    if llm_server is None:
        has_failures = any(r.status in (CheckStatus.FAIL, CheckStatus.MISSING) for r in check_results)
        return {
            "llm_analysis": {
                "risk": "medium" if has_failures else "low",
                "summary": "基于规则引擎的初步判断",
                "suggestions": [r.message for r in check_results if r.status != CheckStatus.PASS],
            }
        }

    # 构建 LLM 上下文
    context = json.dumps(extracted_info, ensure_ascii=False, indent=2)
    rules_summary = [
        f"[{r.status.value}] {r.rule_type}: {r.field} — {r.message or 'OK'}"
        for r in check_results
    ]

    result = await llm_server.analyze_claim(context=context, rules=rules_summary)

    return {
        "llm_analysis": result,
    }
```

- [ ] **Step 4: 运行推理节点测试确认通过**

```bash
pytest tests/unit/test_reasoner_node.py -v
```

Expected: PASS

- [ ] **Step 5: 写报告节点测试**

```python
# tests/unit/test_reporter_node.py
import pytest

from app.agent.nodes.reporter import reporter_node
from app.models.schemas import CheckStatus, RiskLevel, RuleCheckResult


def test_reporter_generates_report():
    state = {
        "claim_type": "medical_claim",
        "rule_check_results": [
            RuleCheckResult("field_present", "金额", CheckStatus.PASS, ""),
            RuleCheckResult("field_present", "公章", CheckStatus.FAIL, "缺少公章"),
        ],
        "llm_analysis": {
            "risk": "medium",
            "summary": "材料基本完整，但缺少公章",
            "suggestions": ["请补充医院公章"],
        },
        "missing_items": ["缺少公章"],
        "audit_report": None,
        "is_complete": False,
    }
    result = reporter_node(state)
    report = result["audit_report"]
    assert report is not None
    assert report.claim_type == "medical_claim"
    assert report.risk_level == RiskLevel.MEDIUM
    assert len(report.check_results) == 2
    assert len(report.suggestions) >= 1
    assert result["is_complete"] is True


def test_reporter_all_pass():
    state = {
        "claim_type": "medical_claim",
        "rule_check_results": [
            RuleCheckResult("field_present", "金额", CheckStatus.PASS, ""),
        ],
        "llm_analysis": {
            "risk": "low",
            "summary": "材料齐全",
            "suggestions": [],
        },
        "missing_items": [],
        "audit_report": None,
        "is_complete": False,
    }
    result = reporter_node(state)
    assert result["audit_report"].risk_level == RiskLevel.LOW
    assert result["audit_report"].overall_status == CheckStatus.PASS
```

- [ ] **Step 6: 运行测试确认失败**

```bash
pytest tests/unit/test_reporter_node.py -v
```

Expected: FAIL

- [ ] **Step 7: 实现 reporter.py**

```python
# app/agent/nodes/reporter.py
import logging

from app.models.schemas import AuditReport, CheckStatus, RiskLevel, RuleCheckResult

logger = logging.getLogger(__name__)


def reporter_node(state: dict) -> dict:
    """报告生成节点：汇总校验结果，输出预审报告"""
    claim_type = state.get("claim_type", "unknown")
    check_results: list[RuleCheckResult] = state.get("rule_check_results", [])
    llm_analysis: dict = state.get("llm_analysis", {})
    missing_items: list[str] = state.get("missing_items", [])

    # 判断整体状态
    has_failures = any(r.status == CheckStatus.FAIL for r in check_results)
    has_missing = any(r.status == CheckStatus.MISSING for r in check_results)

    if has_missing:
        overall_status = CheckStatus.MISSING
    elif has_failures:
        overall_status = CheckStatus.FAIL
    else:
        overall_status = CheckStatus.PASS

    # 风险等级：优先用 LLM 判断，否则从规则结果推断
    risk_str = llm_analysis.get("risk", "")
    if risk_str == "high" or (has_missing and has_failures):
        risk_level = RiskLevel.HIGH
    elif risk_str == "medium" or has_failures or has_missing:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW

    # 建议列表
    suggestions = llm_analysis.get("suggestions", [])
    if missing_items:
        suggestions = list(missing_items) + suggestions

    summary = llm_analysis.get("summary", "")
    if not summary:
        pass_count = sum(1 for r in check_results if r.status == CheckStatus.PASS)
        fail_count = len(check_results) - pass_count
        summary = f"共 {len(check_results)} 项检查，{pass_count} 项通过，{fail_count} 项不通过"

    report = AuditReport(
        claim_type=claim_type,
        overall_status=overall_status,
        risk_level=risk_level,
        check_results=check_results,
        summary=summary,
        suggestions=suggestions,
    )

    return {
        "audit_report": report,
        "is_complete": True,
    }
```

- [ ] **Step 8: 运行测试确认通过**

```bash
pytest tests/unit/test_reporter_node.py -v
```

Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add app/agent/nodes/reasoner.py app/agent/nodes/reporter.py tests/unit/test_reasoner_node.py tests/unit/test_reporter_node.py
git commit -m "feat: add reasoner and reporter nodes"
```

---

### Task 10: Agent Graph 组装

**Files:**
- Create: `app/agent/graph.py`
- Create: `tests/integration/test_agent_graph.py`

- [ ] **Step 1: 写 Agent Graph 集成测试**

```python
# tests/integration/test_agent_graph.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.graph import build_pre_audit_graph


def test_graph_builds_successfully():
    graph = build_pre_audit_graph()
    assert graph is not None


def test_graph_has_expected_nodes():
    graph = build_pre_audit_graph()
    # LangGraph 编译后的图应包含我们的节点
    node_names = set(graph.nodes.keys())
    assert "router" in node_names
    assert "parse" in node_names
    assert "rule_check" in node_names
    assert "ask" in node_names
    assert "reason" in node_names
    assert "report" in node_names
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/integration/test_agent_graph.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 graph.py**

```python
# app/agent/graph.py
import logging
from typing import Any

from langgraph.graph import StateGraph, END

from app.agent.nodes.router import InputType, router_node
from app.agent.nodes.parser import parser_node
from app.agent.nodes.rule_checker import rule_checker_node
from app.agent.nodes.asker import asker_node
from app.agent.nodes.reasoner import reasoner_node
from app.agent.nodes.reporter import reporter_node
from app.config import settings

logger = logging.getLogger(__name__)


def route_after_router(state: dict) -> str:
    """路由后条件分支"""
    input_type = state.get("input_type", "")
    if input_type == InputType.TEXT:
        return "direct_reply"
    elif input_type == InputType.CLAIM_START:
        return "parse"
    elif input_type == InputType.FILE:
        return "parse"
    return "direct_reply"


def route_after_rule_check(state: dict) -> str:
    """规则校验后条件分支"""
    needs_clarification = state.get("needs_clarification", False)
    ask_round = state.get("ask_round", 0)

    if needs_clarification and ask_round < settings.max_ask_rounds:
        return "ask"
    return "reason"


def build_pre_audit_graph(llm_server: Any = None) -> StateGraph:
    """构建预审 Agent 状态机"""

    workflow = StateGraph(dict)

    # 添加节点
    workflow.add_node("router", router_node)
    workflow.add_node("parse", lambda state: _async_wrap(parser_node, state, llm_server))
    workflow.add_node("rule_check", rule_checker_node)
    workflow.add_node("ask", asker_node)
    workflow.add_node("reason", lambda state: _async_wrap(reasoner_node, state, llm_server))
    workflow.add_node("report", reporter_node)

    # 入口
    workflow.set_entry_point("router")

    # 条件边：路由后分支
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "parse": "parse",
            "direct_reply": END,
        },
    )

    # 线性边
    workflow.add_edge("parse", "rule_check")

    # 条件边：规则校验后分支
    workflow.add_conditional_edges(
        "rule_check",
        route_after_rule_check,
        {
            "ask": "ask",
            "reason": "reason",
        },
    )

    # 追问后回到解析（用户补充材料后）
    workflow.add_edge("ask", END)

    # 推理 → 报告 → 结束
    workflow.add_edge("reason", "report")
    workflow.add_edge("report", END)

    return workflow.compile()


def _async_wrap(coro_func, state, llm_server=None):
    """包装异步节点函数（同步调用场景）"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 已在异步上下文中，创建 task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro_func(state, llm_server=llm_server))
            return future.result()
    else:
        return asyncio.run(coro_func(state, llm_server=llm_server))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/integration/test_agent_graph.py -v
```

Expected: PASS

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 6: 提交**

```bash
git add app/agent/graph.py tests/integration/test_agent_graph.py
git commit -m "feat: wire up LangGraph state machine with all nodes"
```

---

### Task 11: Streamlit 聊天界面

**Files:**
- Create: `app/web/chat.py`

- [ ] **Step 1: 实现 Streamlit 聊天界面**

```python
# app/web/chat.py
import streamlit as st
from app.agent.graph import build_pre_audit_graph
from app.config import settings
from app.models.schemas import ExtractedDocument
from app.services.document_parser import DocumentParser
from app.services.llm import LLMServer


def init_session_state():
    """初始化会话状态"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "documents" not in st.session_state:
        st.session_state.documents = []
    if "agent_state" not in st.session_state:
        st.session_state.agent_state = {
            "session_id": "",
            "messages": [],
            "documents": [],
            "claim_type": "",
            "user_input": "",
            "extracted_info": {},
            "rule_check_results": [],
            "llm_analysis": {},
            "missing_items": [],
            "needs_clarification": False,
            "ask_round": 0,
            "audit_report": None,
            "is_complete": False,
            "input_type": "",
        }
    if "graph" not in st.session_state:
        llm_server = LLMServer(settings)
        st.session_state.graph = build_pre_audit_graph(llm_server=llm_server)


def render_chat_history():
    """渲染聊天历史"""
    for msg in st.session_state.messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        with st.chat_message(role):
            st.markdown(content)


def handle_file_upload(uploaded_files):
    """处理文件上传"""
    parser = DocumentParser()
    llm_server = LLMServer(settings)

    for f in uploaded_files:
        file_bytes = f.read()
        file_type = parser.detect_file_type(f.name)

        if file_type == "image":
            image_data = parser.encode_image_to_base64(file_bytes)
            doc = parser.parse_image_sync(llm_server, image_data, f.name)
        elif file_type == "pdf":
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_bytes)
                doc = parser.parse_pdf_sync(llm_server, tmp.name, f.name)
        else:
            st.warning(f"暂不支持 {f.name} 的格式，请上传 JPG/PNG/PDF")
            continue

        st.session_state.documents.append(doc)
        st.session_state.messages.append({
            "role": "user",
            "content": f"已上传: {f.name}",
        })


def main():
    st.set_page_config(page_title="理赔预审助手", page_icon="📋", layout="wide")
    st.title("📋 AI 理赔预审助手")
    st.caption("上传理赔材料，我来帮您提前检查是否齐全")

    init_session_state()

    # 理赔类型选择
    claim_type = st.selectbox(
        "请选择理赔类型",
        ["medical_claim", "accident_claim"],
        format_func=lambda x: {"medical_claim": "医疗险", "accident_claim": "意外险"}.get(x, x),
    )
    st.session_state.agent_state["claim_type"] = claim_type

    # 文件上传
    uploaded_files = st.file_uploader(
        "上传理赔材料（支持 JPG/PNG/PDF）",
        type=["jpg", "jpeg", "png", "pdf"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        handle_file_upload(uploaded_files)

    # 聊天历史
    render_chat_history()

    # 用户输入
    if prompt := st.chat_input("请输入消息或上传材料后点击发送..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.agent_state["user_input"] = prompt

        # 更新 agent state 中的文档列表
        st.session_state.agent_state["documents"] = [
            {"doc_type": d.doc_type, "source_file": d.source_file,
             "confidence": d.confidence, "fields": d.fields, "raw_text": d.raw_text}
            for d in st.session_state.documents
        ]

        # 执行 Agent
        result = st.session_state.graph.invoke(st.session_state.agent_state)

        # 处理结果
        if result.get("audit_report"):
            report = result["audit_report"]
            response = format_report(report)
        elif result.get("needs_clarification"):
            missing = result.get("missing_items", [])
            response = "预审发现以下问题：\n" + "\n".join(f"- {m}" for m in missing)
        else:
            response = "已收到您的消息，请上传理赔材料开始预审。"

        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()


def format_report(report) -> str:
    """格式化预审报告"""
    lines = [
        "## 预审报告",
        f"**理赔类型**: {report.claim_type}",
        f"**整体状态**: {'✅ 通过' if report.overall_status.value == 'pass' else '⚠️ 存在问题'}",
        f"**风险等级**: {report.risk_level.value}",
        "",
        f"**摘要**: {report.summary}",
        "",
        "### 检查结果",
    ]
    for r in report.check_results:
        icon = "✅" if r.status.value == "pass" else "❌"
        lines.append(f"{icon} {r.rule_type}: {r.field} — {r.message or 'OK'}")

    if report.suggestions:
        lines.append("")
        lines.append("### 建议")
        for s in report.suggestions:
            lines.append(f"- {s}")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手动验证 Streamlit 启动**

```bash
cd D:/agentworkspace/PythonProject/claim_pre_audit_agent
streamlit run app/web/chat.py
```

Expected: 浏览器打开 Streamlit 界面，显示"AI 理赔预审助手"标题和文件上传组件

- [ ] **Step 3: 提交**

```bash
git add app/web/chat.py
git commit -m "feat: add Streamlit chat interface for pre-audit"
```

---

### Task 12: FastAPI 路由 + 应用入口

**Files:**
- Create: `app/web/api.py`
- Create: `app/main.py`

- [ ] **Step 1: 实现 FastAPI 路由**

```python
# app/web/api.py
import json
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.agent.graph import build_pre_audit_graph
from app.config import settings
from app.models.schemas import ExtractedDocument
from app.services.document_parser import DocumentParser
from app.services.llm import LLMServer

router = APIRouter()

# 会话存储（生产环境应使用 Redis 或数据库）
sessions: dict[str, dict] = {}


class ChatRequest(BaseModel):
    session_id: str = ""
    message: str
    claim_type: str = "medical_claim"


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    report: dict | None = None
    missing_items: list[str] = []


def _get_or_create_session(session_id: str, claim_type: str) -> dict:
    if not session_id or session_id not in sessions:
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            "session_id": session_id,
            "messages": [],
            "documents": [],
            "claim_type": claim_type,
            "user_input": "",
            "extracted_info": {},
            "rule_check_results": [],
            "llm_analysis": {},
            "missing_items": [],
            "needs_clarification": False,
            "ask_round": 0,
            "audit_report": None,
            "is_complete": False,
            "input_type": "",
        }
    return sessions[session_id]


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """文字对话接口"""
    state = _get_or_create_session(request.session_id, request.claim_type)
    state["user_input"] = request.message
    state["documents"] = [
        ExtractedDocument(**d) if isinstance(d, dict) else d
        for d in state.get("documents", [])
    ]

    llm_server = LLMServer(settings)
    graph = build_pre_audit_graph(llm_server=llm_server)
    result = await graph.ainvoke(state)

    sessions[state["session_id"]] = result

    reply = ""
    report_dict = None
    missing = result.get("missing_items", [])

    if result.get("audit_report"):
        report = result["audit_report"]
        reply = report.summary
        report_dict = {
            "claim_type": report.claim_type,
            "overall_status": report.overall_status.value,
            "risk_level": report.risk_level.value,
            "summary": report.summary,
            "suggestions": report.suggestions,
            "check_results": [
                {
                    "rule_type": r.rule_type,
                    "field": r.field,
                    "status": r.status.value,
                    "message": r.message,
                }
                for r in report.check_results
            ],
        }
    elif result.get("needs_clarification"):
        reply = "预审发现问题：\n" + "\n".join(f"- {m}" for m in missing)
    else:
        reply = "已收到您的消息。"

    return ChatResponse(
        session_id=state["session_id"],
        reply=reply,
        report=report_dict,
        missing_items=missing,
    )


@router.post("/upload")
async def upload_files(
    session_id: str = Form(""),
    claim_type: str = Form("medical_claim"),
    files: list[UploadFile] = File(...),
):
    """文件上传接口"""
    state = _get_or_create_session(session_id, claim_type)
    parser = DocumentParser()
    llm_server = LLMServer(settings)

    uploaded = []
    for f in files:
        file_bytes = await f.read()
        file_type = parser.detect_file_type(f.filename or "")

        if file_type == "image":
            image_data = parser.encode_image_to_base64(file_bytes)
            doc = await parser.parse_image(llm_server, image_data, f.filename or "")
        elif file_type == "pdf":
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp.flush()
                doc = await parser.parse_pdf_with_llm(llm_server, tmp.name, f.filename or "")
        else:
            continue

        uploaded.append({
            "doc_type": doc.doc_type,
            "source_file": doc.source_file,
            "confidence": doc.confidence,
            "fields": doc.fields,
            "raw_text": doc.raw_text,
        })

    state["documents"].extend(uploaded)
    sessions[state["session_id"]] = state

    return {
        "session_id": state["session_id"],
        "uploaded_count": len(uploaded),
        "documents": uploaded,
    }


@router.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: 实现应用入口**

```python
# app/main.py
import uvicorn
from fastapi import FastAPI

from app.web.api import router as api_router

app = FastAPI(
    title="AI 理赔预审助手",
    description="基于 LangGraph 的理赔材料预审 Agent",
    version="0.1.0",
)

app.include_router(api_router, prefix="/api/v1")


def run_api(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port)


def run_chat():
    import subprocess
    subprocess.run(["streamlit", "run", "app/web/chat.py"])


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "api"
    if mode == "chat":
        run_chat()
    else:
        run_api()
```

- [ ] **Step 3: 手动验证 API 启动**

```bash
cd D:/agentworkspace/PythonProject/claim_pre_audit_agent
python -m app.main api
```

然后另开终端测试：

```bash
curl http://localhost:8000/api/v1/health
```

Expected: `{"status":"ok"}`

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "我想咨询理赔流程", "claim_type": "medical_claim"}'
```

Expected: 返回 ChatResponse JSON

- [ ] **Step 4: 运行全部测试确认无回归**

```bash
pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add app/web/api.py app/main.py
git commit -m "feat: add FastAPI routes and app entry point"
```

---

### Task 13: 最终集成验证 + 清理

**Files:**
- Modify: `app/main.py`（确保入口干净）

- [ ] **Step 1: 运行全部测试**

```bash
pytest tests/ -v --tb=short
```

Expected: ALL PASS

- [ ] **Step 2: 验证 Streamlit 启动**

```bash
streamlit run app/web/chat.py --server.headless true
```

Expected: 无报错，可正常访问

- [ ] **Step 3: 验证 API 启动**

```bash
python -m app.main api
```

Expected: `Uvicorn running on http://0.0.0.0:8000`

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "chore: final integration verification and cleanup"
```
