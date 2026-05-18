import { Callout, Card, CardBody, CardHeader, Divider, Grid, H1, H2, H3, Pill, Row, Stack, Stat, Table, Text } from 'cursor/canvas';

const layers = [
  ['入口层', '企业微信、Web 控台、API、第三方 Agent', '统一身份、意图识别、多轮会话、权限上下文'],
  ['编排层', '主控 Agent、任务规划器、策略引擎', '拆解对接任务、选择工具、路由专家 Agent、生成交付件'],
  ['业务能力层', '方案 Agent、排查 Agent、咨询 Agent、合规 Agent', '健康险个险业务问答、接口映射、核保理赔流程解释、异常定位'],
  ['工具与知识层', 'API 网关、日志平台、文档库、测试沙箱、规则库', '查询接口、生成样例、读取链路日志、执行模拟交易'],
  ['治理层', '审计、风控、质量评估、技能市场', '留痕、脱敏、权限控制、技能发布审批、效果回归'],
];

const agents = [
  ['主控 Agent', '识别用户目标，拆分任务，调度其他 Agent 和工具', '必须保留最终决策权和审计链路'],
  ['对接方案 Agent', '输出个险健康险业务对接方案、接口清单、字段映射、测试计划', '基于产品、渠道、投保、核保、支付、承保、保全、理赔全链路建模'],
  ['对接排查 Agent', '定位接口失败、数据不一致、流程卡点、回调异常', '接入日志、报文、链路追踪、错误码知识库和沙箱重放'],
  ['业务咨询 Agent', '回答产品责任、投保规则、核保规则、理赔材料、渠道流程', '需要区分公开口径、内部口径和客户可见口径'],
  ['合规安全 Agent', '检查话术、数据使用、跨司通信、隐私脱敏、监管要求', '对高风险动作执行拦截或升级人工审批'],
  ['外部协作 Agent 适配器', '与保险公司、TPA、经代、体检机构、支付公司 Agent 互通', '使用标准协议、契约校验、权限令牌和消息签名'],
  ['技能学习 Agent', '沉淀排查案例、更新知识库、生成新工具调用模板', '通过评测、审批、灰度后才能发布新技能'],
];

const flows = [
  ['新公司接入', '收集公司产品与接口资料 -> 生成差异分析 -> 输出对接方案 -> 建立沙箱测试 -> 验收上线'],
  ['问题排查', '读取用户问题 -> 获取 traceId/保单号/投保单号 -> 查日志和报文 -> 复现 -> 给根因与修复建议'],
  ['业务咨询', '识别咨询对象和场景 -> 检索业务知识 -> 合规校验话术 -> 输出分角色答案和依据'],
  ['跨 Agent 协作', '建立会话契约 -> 交换能力清单 -> 发起任务委托 -> 验证响应签名与 schema -> 汇总结果'],
  ['技能升级', '发现高频问题 -> 形成候选技能 -> 离线评测 -> 人工审批 -> 灰度发布 -> 持续监控'],
];

const frameworkOptions = [
  ['推荐主框架', 'LangGraph', '适合有状态、多步骤、可回放的企业 Agent 编排。可把对接、排查、咨询、合规做成节点图，并支持人工审批节点。'],
  ['知识检索层', 'LlamaIndex / LangChain RAG', '负责产品条款、接口文档、错误码、案例库、监管规则的索引、召回、重排和引用溯源。'],
  ['业务服务层', 'Spring Boot / FastAPI', '承载企业 API、权限、审计、工具服务和与核心系统的集成。保险企业偏 Java 可优先 Spring Boot。'],
  ['工具协议层', 'MCP + OpenAPI Tools', '把日志查询、保单查询、沙箱重放、报文校验、知识库查询封装成标准工具，供 Agent 安全调用。'],
  ['跨公司协作', 'A2A 思路 + 自定义 Agent Gateway', '对外暴露 capability manifest、task envelope、签名验签、schema 校验、回调和审计。'],
  ['低代码运营', 'Dify / Coze / 自研运营台', '适合配置话术、知识库、FAQ、简单流程；不建议承载核心联调排查和跨司交易编排。'],
  ['观测评测', 'OpenTelemetry + LangSmith 类评测平台', '记录每次推理、工具调用、输入输出、命中知识、失败原因和回归评测结果。'],
];

const generationSteps = [
  ['定义 Agent 模板', '用 YAML/JSON 描述 agentId、role、allowedTools、knowledgeScopes、policies、handoffRules、evalCases。'],
  ['绑定业务知识', '按产品、公司、渠道、流程、接口、错误码、案例沉淀可引用知识，并给每类知识配置可见范围。'],
  ['注册工具能力', '把日志平台、API 网关、保单中心、投保单中心、沙箱、报文校验器注册为受权限控制的工具。'],
  ['生成运行图', '由 Agent Factory 把模板转换为 LangGraph 状态图：意图识别、检索、工具调用、合规检查、人工确认、输出。'],
  ['上线前评测', '执行业务问答、联调排查、错误码定位、越权访问、隐私脱敏和幻觉率评测，达标后灰度发布。'],
];

const integrationAgentStack = [
  ['编排框架', 'LangGraph', '把“资料收集、差异分析、字段映射、方案生成、测试计划、合规复核”做成可回放状态图。'],
  ['服务框架', 'Spring Boot 优先，FastAPI 可选', '保险企业核心系统多为 Java 生态，Spring Boot 更利于接入 IAM、网关、审计、配置中心。'],
  ['知识检索', 'LlamaIndex / LangChain RAG + 向量库', '检索产品条款、接口文档、投保规则、核保规则、历史方案、联调案例，并输出引用依据。'],
  ['工具标准', 'MCP Server + OpenAPI', '把文档解析、schema 比对、字段映射、样例生成、沙箱校验封装为 Agent 工具。'],
  ['结构化输出', 'JSON Schema / Pydantic / Zod', '约束方案输出格式，便于生成 Word、Excel、Markdown、Confluence 或工单附件。'],
  ['质量评测', '离线 Eval + 人工评审', '检查字段遗漏、流程遗漏、接口顺序错误、合规风险、方案可执行性。'],
];

const integrationAgentModules = [
  ['需求理解模块', '识别接入对象、险种、渠道、业务范围、上线时间、已有资料缺口。'],
  ['资料解析模块', '解析接口文档、产品条款、字段字典、流程图、样例报文、历史工单。'],
  ['业务流程建模模块', '建立投保、核保、支付、承保、回执、保全、理赔、退保等流程模型。'],
  ['接口差异分析模块', '比对我方标准接口与对方接口，识别字段、枚举、时序、幂等、签名、回调差异。'],
  ['字段映射模块', '生成字段 mapping、转换规则、必填规则、默认值、枚举映射、脱敏规则。'],
  ['方案生成模块', '输出对接范围、系统交互、接口清单、流程说明、改造点、风险点和里程碑。'],
  ['测试设计模块', '生成联调用例、异常用例、回归用例、验收清单和上线检查项。'],
  ['合规复核模块', '检查隐私数据、客户可见表述、监管敏感点、跨公司数据边界。'],
];

const integrationGraphNodes = [
  ['collect_context', '收集接入公司、产品、渠道、资料、目标上线范围和缺失信息。'],
  ['retrieve_knowledge', '检索标准方案、历史案例、接口规范、产品条款和业务规则。'],
  ['parse_documents', '结构化解析接口文档、报文样例、字段说明和流程说明。'],
  ['build_process_model', '生成健康险个险标准业务流程与当前项目流程差异。'],
  ['compare_interfaces', '生成接口差异、字段差异、枚举差异、签名鉴权差异和回调差异。'],
  ['generate_solution', '生成完整对接方案、改造清单、接口清单、数据映射和风险清单。'],
  ['generate_test_plan', '生成联调、异常、回归、验收和上线检查方案。'],
  ['compliance_review', '执行隐私、合规、权限、数据出境或跨司传输检查。'],
  ['human_approval', '关键方案由架构师、业务专家或合规人员确认后定稿。'],
];

const risks = [
  ['隐私泄露', '最小化传输、字段脱敏、访问令牌分级、全链路审计'],
  ['错误业务建议', '答案附依据，关键结论由合规 Agent 复核，高风险场景转人工'],
  ['跨公司 Agent 不可信', '双向认证、消息签名、schema 校验、沙箱隔离、结果置信度标注'],
  ['技能自升级失控', '候选技能不可直接上线，必须通过评测、审批、灰度和回滚机制'],
  ['接口排查误操作', '生产只读优先，写操作必须工单授权和二次确认'],
];

export default function HealthInsuranceAgentArchitecture() {
  return (
    <Stack gap={22}>
      <Stack gap={8}>
        <H1>健康险个险业务对接 Agent 架构方案</H1>
        <Text tone="secondary">
          目标是建设一个面向健康险个险业务的复合型 Agent：能产出对接方案、辅助联调排查、回答业务咨询、与外部公司 Agent 协作，并在治理约束下持续升级技能。
        </Text>
        <Row gap={8} wrap>
          <Pill tone="info" active>方案生成</Pill>
          <Pill tone="warning" active>联调排查</Pill>
          <Pill tone="success" active>业务咨询</Pill>
          <Pill>跨公司协作</Pill>
          <Pill>技能进化</Pill>
        </Row>
      </Stack>

      <Grid columns={4} gap={14}>
        <Stat value="7" label="核心 Agent 角色" tone="info" />
        <Stat value="5" label="关键业务流程" tone="success" />
        <Stat value="3" label="强治理边界" tone="warning" />
        <Stat value="1" label="主控编排中心" />
      </Grid>

      <Callout tone="info" title="推荐总体形态">
        使用「主控 Agent + 专家 Agent + 工具执行层 + 治理闭环」架构。主控 Agent 负责意图理解和任务编排，专家 Agent 负责健康险个险领域能力，工具层连接真实系统，治理层控制安全、合规、审计和技能发布。
      </Callout>

      <H2>Agent 生成框架选型</H2>
      <Callout tone="success" title="推荐技术路线">
        核心 Agent 编排建议使用 LangGraph；企业系统集成用 Spring Boot 或 FastAPI；知识检索用 LlamaIndex 或 LangChain RAG；工具协议用 MCP 和 OpenAPI；外部公司协作用 Agent Gateway 封装能力发现、任务委托、签名验签和审计。
      </Callout>
      <Table
        headers={['模块', '推荐框架', '使用理由']}
        rows={frameworkOptions}
        rowTone={['success', undefined, undefined, undefined, 'warning', 'info', undefined]}
        striped
      />

      <H2>Agent 不是手写一个类，而是由 Agent Factory 生成</H2>
      <Text>
        建议建设 Agent Factory：把角色定义、工具权限、知识范围、流程图、合规策略和评测集配置化，再生成可运行的 Agent。这样新增保险公司、新产品、新渠道时，不需要复制代码，只需要新增配置、知识和工具契约。
      </Text>
      <Table
        headers={['步骤', '说明']}
        rows={generationSteps}
        striped
      />

      <Divider />

      <H2>对接方案 Agent 技术框架</H2>
      <Callout tone="success" title="核心定位">
        对接方案 Agent 是“方案架构师 + 业务分析师 + 接口设计师 + 测试设计师”的组合体。它不直接修改生产系统，主要产出结构化对接方案、字段映射、接口差异、改造清单、测试计划和上线检查表。
      </Callout>
      <Table
        headers={['层面', '推荐技术', '设计理由']}
        rows={integrationAgentStack}
        rowTone={['success', undefined, undefined, undefined, 'info', undefined]}
        striped
      />

      <Grid columns="1fr 1fr" gap={16}>
        <Card>
          <CardHeader trailing={<Pill tone="success" size="sm">Modules</Pill>}>内部功能模块</CardHeader>
          <CardBody>
            <Stack gap={10}>
              {integrationAgentModules.map(([name, desc]) => (
                <Stack gap={3} key={name}>
                  <Text weight="semibold" size="small">{name}</Text>
                  <Text tone="secondary" size="small">{desc}</Text>
                </Stack>
              ))}
            </Stack>
          </CardBody>
        </Card>

        <Card>
          <CardHeader trailing={<Pill tone="info" size="sm">LangGraph</Pill>}>推荐运行图节点</CardHeader>
          <CardBody>
            <Stack gap={10}>
              {integrationGraphNodes.map(([name, desc]) => (
                <Stack gap={3} key={name}>
                  <Text weight="semibold" size="small">{name}</Text>
                  <Text tone="secondary" size="small">{desc}</Text>
                </Stack>
              ))}
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <H2>分层架构</H2>
      <Table
        headers={['层级', '组成', '职责']}
        rows={layers}
        striped
        columnAlign={['left', 'left', 'left']}
      />

      <Grid columns="1fr 1fr" gap={16}>
        <Card>
          <CardHeader trailing={<Pill tone="info" size="sm">Agent Map</Pill>}>核心 Agent 角色</CardHeader>
          <CardBody>
            <Stack gap={12}>
              {agents.map(([name, duty, note]) => (
                <Stack gap={4} key={name}>
                  <Text weight="semibold">{name}</Text>
                  <Text size="small">{duty}</Text>
                  <Text tone="secondary" size="small">{note}</Text>
                </Stack>
              ))}
            </Stack>
          </CardBody>
        </Card>

        <Stack gap={14}>
          <H2>关键流程</H2>
          {flows.map(([name, flow]) => (
            <Stack gap={4} key={name}>
              <H3>{name}</H3>
              <Text size="small">{flow}</Text>
            </Stack>
          ))}
        </Stack>
      </Grid>

      <Divider />

      <H2>跨公司 Agent 交互协议</H2>
      <Grid columns={3} gap={14}>
        <Card>
          <CardHeader>能力发现</CardHeader>
          <CardBody>
            <Text size="small">外部 Agent 提供 capability manifest：支持的业务域、接口、输入输出 schema、权限范围、SLA 和联系人。</Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>任务委托</CardHeader>
          <CardBody>
            <Text size="small">使用标准 task envelope：taskId、intent、context、requiredEvidence、callback、expiry、signature。</Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>结果验收</CardHeader>
          <CardBody>
            <Text size="small">响应必须包含 structured result、依据、置信度、数据来源、可复现步骤和错误码映射。</Text>
          </CardBody>
        </Card>
      </Grid>

      <H2>技能升级闭环</H2>
      <Text>
        技能升级不能等同于模型自由学习。建议采用受控发布：从高频咨询、联调失败案例、人工专家处理记录中抽取候选技能，经离线评测、合规审核、灰度发布、线上监控和回滚机制后再进入正式技能库。
      </Text>

      <H2>主要风险与控制</H2>
      <Table
        headers={['风险', '控制措施']}
        rows={risks}
        rowTone={[undefined, 'warning', 'warning', 'danger', undefined]}
        striped
      />
    </Stack>
  );
}
