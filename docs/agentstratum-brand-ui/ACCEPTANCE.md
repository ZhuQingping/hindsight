# 验证与审查合同

原设计交接时均为 `NOT_RUN`。本次实施的实际状态见文末结果表；完整证据及当前阻塞见 RESULT.md。

## 验收矩阵

| ID | 必须证明的行为 | 建议证据 |
| --- | --- | --- |
| A01 | 分支基于 origin/main；没有旧多用户/Key、hosted 管理或 schema 隔离代码 | merge-base、路径清单、完整 diff、禁止依赖扫描 |
| A02 | 无管理服务配置时，原生 API + UI 可启动并使用 | 独立启动配置；UI 原生数据读取；没有 management URL 请求 |
| A03 | 导航/接入页没有无法使用的访问管理、创建用户/Key 入口 | 桌面/移动浏览器；路由与链接检查 |
| A04 | 同一 API/UI 制品重启为 agentstratum 与第二名称，UI/metadata/图表导出/API/OpenAPI/MCP 名称一致 | 两次启动记录、构建哈希、DOM、OpenAPI、真实 MCP initialize |
| A05 | 非法名称在 Python/TS 同样拒绝，不 trim/lowercase | 空值、大小写、空格、换行、中文、路径、超长的负例测试 |
| A06 | API/CP 名称错配、旧页签请求和服务故障不转发业务写入；输入保留、不自动提交 | guard 单测及有界浏览器/请求观测 |
| A07 | UI 无有效会话不能访问动态数据；点号 ID 仍受保护；退出撤销生效，Host/Origin 拒绝反例有效 | auth/proxy/session 测试 + 真实会话最小故事 |
| A08 | 中文/英文术语和品牌完整；其他 locale 明确英文回落；切语言不丢 query/hash | 文案测试 + 三种 locale 的实际浏览器 |
| A09 | Workspace 对应原生 bank；含特殊字符 ID 的选择、直达和 SDK/MCP 路径保持正确 | 原生 SDK create/list/delete、UI 接入代码、编码测试 |
| A10 | 品牌补丁不改变原生引擎、数据库迁移、Worker、授权扩展或客户端协议 | 基线逐路径对比；API diff 仅命名与新增非秘密配置端点 |
| A11 | 原生文件下载/传输、页面导航及图表修复没有拆分回归 | 已迁入 unit tests，代表性 browser 检查 |
| A12 | OpenAPI/SDK 与本分支 API 一致；生成物没有旧权限字段；模板字节一致 | spec 结构差异、生成器/输入哈希、TS build、Python import，Go/Rust 视工具可用性单列 |
| A13 | frontend tests/typecheck/production build、Python 命名测试与全仓必需 lint 实际执行 | 退出码、日志、资源记录；TZ=UTC 固定时间测试 |
| A14 | Hook 状态准确：原生 integration 代码保持；未做的新品牌 Hook 改造不冒充完成 | integration diff、接入边界说明；实际 Hook 宿主运行未做则 NOT_RUN |
| A15 | 无 Must fix 审查项，提交与报告可复核，主干未合并 | code-review 结果、提交 SHAs、remote 分支/draft PR |

## 执行顺序与资源

1. 先源码纯度和配置合同静态检查，再准备独立依赖，先跑定位清晰的 unit tests。
2. 补齐/生成接口产物后跑 SDK/类型检查；修复失败，再 production build。
3. 最小独立原生 backend + 生产 UI 验证，不要求重跑与此变更无关的整套模型基准。命名测试不调用真实模型。
4. 重型命令统一经 `/home/cimon/code/hindsight/.local/hosted-single-tenant/development/runs/m2-access-ui-delivery/run-bounded.py`，复用共享 `resource-heavy.lock`。每项串行；锁被占用就等待，不停止其他任务或复制运行器绕过。
5. 日志/制品/数据库及临时文件统一放主仓 `.local/product-brand-ui`。仅清理本任务创建的资源；记录归属、端口、PID/容器 ID、创建和清理状态。

## 报告标准

- `PASS` 必须关联当前候选来源和命令退出码；旧分支 PASS 不能移植。
- 测试未开始、工具链缺失、共享锁占用应与产品测试失败区分。
- 不能用测试 skip、mock 结果、静态通过代替原生服务、MCP、浏览器或发布 SDK 实测。
- 完成报告应区分本地拆分技术验证、用户产品验收、生产部署与模型质量。后两者不在本次范围。
- 若必需检查受环境阻塞，持续完成其他可执行工作，持久化准确恢复入口；不标记“可合并”或“全部通过”。

## 本次实施结果（2026-10-18）

判定：`LOCAL_ACCEPTANCE_PASS / INDEPENDENT_REVIEW_CLOSED / DRAFT_FOR_USER_REVIEW`。最终源码 14c2d60ea，原生最终运行 c12；独立初审 R1–R5 均已修复并复审关闭；未把历史 PASS 或未运行项移作当前证明。

| ID | 最终结果与范围 |
| --- | --- |
| A01 | PASS：独立 main 基线；禁止路径/依赖扫描；无其他开发线提交 |
| A02 | PASS：独立原生 API/Worker/PG + production UI 实际启动，无 management 服务；真实 SDK 与浏览器原生操作 |
| A03 | PASS：桌面/移动导航、接入与路由链接检查；无旧访问管理、用户或 Key 签发入口 |
| A04 | PASS：同一 production 制品双名称运行，UI/metadata/图表 SVG、两品牌 API/OpenAPI 与真实 MCP initialize/get_bank 一致 |
| A05 | PASS：Python/TS 合法值及空值、大小写、空白、换行、中文、路径、超长负例单测 |
| A06 | PASS：真实旧页签保留输入，Recall 仅一次拒绝、实际操作归档按钮 200/CRC 后，旧页签 409、零原生文件转发/保存/重发；品牌错配/离线不转发写入，无自动重发 |
| A07 | PASS：真实登录、动态点号路由 401、复制 Cookie、离线退出、重启撤销、Origin 403/Host 421；相应 unit 反例通过 |
| A08 | PASS：三种 locale 实际页面、真实菜单切换 query/hash，重复过滤器及 basePath cookie 隔离回归通过 |
| A09 | PASS 实测范围：含 %、中文、点号 ID 的原生 SDK 创建/列举/跨产品改名保留/删除与 MCP 读取、UI 接入代码；不扩张为所有斜杠 ID 端到端证明 |
| A10 | PASS：engine/worker/迁移/授权扩展等保护路径保持基线；原 API 路径和模型逐结构一致 |
| A11 | PASS：原生归档下载与 CRC、multipart 导入、SDK 文档回读、双品牌 SVG 导出与移动页面；unit 亦通过 |
| A12 | PASS 可用工具链范围：432个既有SDK公共模型/请求API与基线一致、566个SDK文件重复生成无漂移；本分支重生成、结构检查、TS 编译和 Python 两品牌 SDK 黑盒；Go/Rust 编译 NOT_RUN 无工具链 |
| A13 | PASS：最终 frontend 354、tsc、SDK build、全仓 lint、production build；未变化 Python 命名 11 项证据已核对 |
| A14 | PASS 边界：integration 代码未变，无可提取 Hook 品牌补丁；宿主运行 NOT_RUN，无完成 Hook 改造的声明 |
| A15 | PASS 本地交付与审查：没有未处理 Must fix，证据与源码已持久化，PR #5 保持 draft；不合主干 |

真实模型质量、生产部署、人工产品验收和远端 CI 均不作为本次通过结论。日志、资源、失败修复和剩余范围见 [RESULT.md](RESULT.md)、[VALIDATION.json](VALIDATION.json)。

独立审查边界澄清（2026-10-18）：A06 的旧页签拒绝覆盖携带页签标识的业务 API 及本分支归档入口；原生只读 inline attachment anchor/img 保持基线（含缓存），不是全部 asset 入口保护。操作详情实际 Download 的改名后拒绝以本轮 runtime 证据为准，不能由 c08 的手工带头 fetch 推断。
