# AgentStratum 品牌与 UI 独立提交计划

创建：2026-10-16；定稿：2026-10-17。状态：`DESIGN_READY / IMPLEMENTATION_HANDOFF`。

最新用户指令：“方案设计你继续做，做完了请直接在新session开始方案实施”。因此本会话完成设计、固定草稿与交接；正式实施由新独立 session 承接，无需再次请求启动确认。

阅读顺序：[DESIGN.md](DESIGN.md) → [ACCEPTANCE.md](ACCEPTANCE.md) → [HANDOFF.md](HANDOFF.md) → [SOURCE-MAP.json](SOURCE-MAP.json)。本目录在主仓保留交接入口，实施权威副本位于独立 worktree 的同路径。

## 目标与交付边界

从 `origin/main` 建立独立分支 `product/agentstratum-brand-ui-20261016`，整理可以独立提交的 AgentStratum Web UI、API、MCP 产品适配，保留原生能力与客户端协议。多用户、多 API Key 方案继续保留在已有开发线，不进入本分支，不合并主干。

实施交付：本计划、可审查提交、来源清单、拆分说明、验证与审查结果。完成本地提交后推送此独立分支并准备 draft PR（若远端权限可用）；最终主干合并由用户审查决定。设计阶段的已有代码仅为 `DRAFT_UNVALIDATED`，不能据此宣称实施完成。

## 已核实的来源

| 来源 | 内容及处理 |
| --- | --- |
| `origin/main` / `f51b165a5165b1042ba0b6408fcffb5bc1a80fdb` | 当前主干基线；开始前重新查询远端 |
| `hosted/p1-m2-product-v2_1` / `74b522bd808f88371e012dc5fb3710127cacdd9e` | UI、导航、图表、动效、指南、接入页、原生下载修复及 UI 本地会话保护；按路径提取，不整体合并祖先中的 hosted manager/runtime |
| `hosted/m2-access-ui-20261014` / `c7b25a9ae` | 包含前一分支及多用户/Key 集成；只提取必要的通用修复，例如运行时 session 路径不进入构建追踪 |
| `hosted/follow-up-p-20261016` 未提交工作区 | F02/F03/F04：统一品牌配置、产品定位、Workspace 术语 |
| `hosted/follow-up-simplified-20261016` 未提交工作区 | 后续品牌修复、语言回落、语言切换保持 URL 状态、接口生成物；只以固定文件快照为来源，接口生成物从本分支重新生成 |

这不是两条互不相交的分支。后续品牌工作与访问管理、存储隔离存在同文件耦合；多个 follow-up 分支 HEAD 相同，但未提交文件不同。必须按功能拆分。

## 纳入

1. AgentStratum UI 布局、响应式导航、图表与动效、原生功能页、指南和 SDK/REST/MCP 接入说明。
2. `contextdb_name` 固定部署变量，默认 `agentstratum`，合法值 `[a-z][a-z0-9-]{0,39}`；UI 品牌/metadata/图标/导出和 API/OpenAPI、HTTP MCP 服务名一致。
3. 产品定位“Agent 数据底座”、Workspace/工作空间展示术语；底层 `bank_id`、API 路径、SDK 包名和 MCP 工具名保持协议身份。
4. 中文/英文产品文案，其他保留语言明确英文回落；切换语言保持查询参数和锚点。
5. 第一阶段已有的 UI 登录、会话撤销、可信 Origin/Host、服务端 API Key 保管与文件下载修复。
6. 对应测试、配置模板、使用文档与重新生成的 OpenAPI/SDK。

## 排除与解耦

- 不引入 `hindsight-extensions/hosted-single-tenant`、多 Key/Owner/User、访问管理页面/BFF、策略模型、恢复账本或权限迁移。
- 不引入 per-Workspace PostgreSQL schema、存储绑定、隔离 Worker、任务/制品权限与 hosted manager/runtime。
- `product-config-server.ts` 改为只消费原生数据 API 地址；不依赖 `lib/hosted/access-config` 或管理 API。
- 品牌不一致保护保留通用数据请求检查，删除访问管理专用错误合同/恢复例外；提示文案不引用不存在的操作记录页面。
- 导航、接入页、翻译文件删除本方案的访问管理入口和签发 Key 提示，恢复“向部署管理员获取凭证”的独立接入方式。
- `http.py`、`mcp.py` 仅移植命名相关代码片段；不复制后续整个后端文件。
- 原生记忆引擎、授权扩展、数据库迁移、Worker 与其他同事的实现保持独立。

## Hook 边界

已检查上述工作区的 `hindsight-integrations/`，没有相对主干的修改或未跟踪文件。当前不能宣称 Agent Hook 品牌改造已存在。此次提取不凭空新增插件协议重命名；保留原生 Hook 接入兼容性，并在交付文档记录覆盖边界。`scripts/hooks/lint.sh` 是开发检查脚本，不是 Agent Hook 适配。

## 执行顺序

1. 保存方案；建立独立 worktree，固定来源文件快照和 SHA-256 清单，避免修改其他工作区。
2. 提取早期产品改动，排除历史 hosted 部署设施和旧验收结论；保留相关测试。
3. 移植后续品牌、定位、术语与通用修复，解除访问管理依赖，清理构建产物路径等本机残留。
4. 重新生成接口产物，更新配置模板、独立使用说明和测试。
5. 运行 lint/typecheck、前端测试与 production build、品牌/API/MCP 测试，以及独立原生后端的有界黑盒与浏览器检查。验证两个合法品牌、非法配置、品牌错配、语言切换、无访问管理依赖与 UI 会话边界。
6. 按 `.claude/skills/code-review/SKILL.md` 审查功能、分支纯度、死代码、接口一致性及测试证据；修复必须解决项。
7. 持久化结果与限制，创建可审查提交，推送独立分支并准备 draft PR；不合并主干。

## 资源、证据与保护

- 新 worktree：主仓 `.local/product-brand-ui/worktree`；来源快照、运行日志与临时资源统一放主仓 `.local/product-brand-ui/`。
- 不修改、不 reset、不 stash、不提交已有 main/hosted/follow-up 工作区中的用户改动。
- 重型验证串行执行，复用现有 `run-bounded.py` 和共享资源锁；若锁被占用，不停止其他任务，不绕过锁。
- 测试使用独立临时目录/端口/数据库，仅清理由本任务创建的资源；不启动生产部署，不调用真实模型，不读取或输出业务凭证。
- 旧分支 PASS 仅作历史背景，不能替代拆分候选验证。实际未运行或受阻的检查明确记录 `NOT_RUN`/失败原因，不宣称生产验收完成。
