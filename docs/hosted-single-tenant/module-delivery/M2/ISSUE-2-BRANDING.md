# Issue #2：agentstratum 对外品牌改造

状态：IMPLEMENTED_WITH_PENDING_RELEASE_INPUTS / NOT_READY_FOR_CLOSURE。

对应 [Issue #2](https://github.com/RSIXDB/hindsight/issues/2)。本轮基于分支 hosted/p1-m2-product-v2_1、起始 HEAD c3d6eeacc，在工作区实现；未发布、部署或关闭 Issue。本报告不继承旧 M2 候选的验收结论。

## 确认的范围

- 产品标识为 agentstratum；覆盖 REST、Web API、Webhook、服务端 MCP、本地插件和引擎、模型出站请求、客户监控。
- SDK 包名、类名和公开接口不改；只适配嵌入模式的内部配置传递。
- Web 页面视觉由独立团队负责；接口消费方的 header/配置绑定必须同步，否则会破坏既有页面请求。
- 无旧品牌迁移、双协议兼容要求。客户输入、文件名、文件字节和成功业务内容中的同名词不替换。
- 本地引擎自动下载安装模式保留。生产域名、文档地址、发布命名空间和 CLI 可信发行源仍待定。

## 已实现的接口合同

| 边界 | 本轮行为 |
| --- | --- |
| REST / OpenAPI | agentstratum API 标题与说明；77 个路径的生成规范不含旧品牌；未新增 URL 前缀或改业务字段 |
| Web API | 代理失败诊断去除内部品牌；健康响应不暴露后端地址；登录、Cookie、重定向、下载原有鉴权与流式语义保留 |
| Webhook | X-Agentstratum-Event、X-Agentstratum-Signature、X-Agentstratum-Signature-V2；标准 X-Hub-Signature-256 保留；保留 HMAC 算法、时间戳及原始 body；保留 header 忽略大小写防覆盖保护 |
| MCP | 服务端身份 agentstratum-mcp-server；原中性服务端工具名不变；本地插件身份、带品牌工具/配置、注入标记和宿主注册同步修改 |
| 模型请求 | 产品 User-Agent、X-Agentstratum-Bank-Id、Claude 工具 MCP 前缀、Gemini batch 标识使用新品牌；客户 prompt/output 不替换 |
| 客户监控 | agentstratum 指标、span、scope、服务名和配套 Grafana/Prometheus 配置；异常文本与 stack 在诊断出口处理 |
| 本地运行 | agentstratum CLI/agentstratum-embed 命令、配置与缓存目录、日志、引擎启动参数和本地 control API 合同 |

已在 REST 内部错误、异步操作错误、失败 consolidation Webhook、MCP 错误、LLM trace 错误以及 Web 代理诊断处处理内部实现标识。过滤发生在明确的诊断字段，未对响应 body 或文件流做全局字符串替换。未知内部 500 返回固定通用诊断；内部异常仍可保留在运维专用日志。

客户 stdout formatter 不暴露 Python 堆栈；可选 AGENTSTRATUM_INTERNAL_LOG_FILE 保存原始日志供内部排障，该文件不是客户可导出日志。OTLP exporter 只复制/处理诊断属性和异常事件，保留客户内容、trace ID、关联信息与正常事件。

## 发行时必须提供的配置

| 配置 | 用途 |
| --- | --- |
| AGENTSTRATUM_API_URL / apiUrl | 插件连接实际服务；云模式无猜测的默认域名 |
| AGENTSTRATUM_CODING_AGENTS_PACKAGE | 经运营方确认的 npm 自动更新目标；未配置不查询 registry |
| AGENTSTRATUM_EMBED_PACKAGE | 本地 Python embed 发行 spec；开发可指定本地包路径 |
| AGENTSTRATUM_EMBED_API_PACKAGE | 本地自动下载的 API 发行 spec |
| AGENTSTRATUM_EMBED_CP_PACKAGE | 启用本地 Web 时的发行 spec |
| AGENTSTRATUM_API_* | 服务入口读取的公开配置前缀；内部映射到既有引擎实现 |

工作区 npm 名称为私有构建标识，不代表已在 npm 占用或发布。实际域名、文档站和分发地址未创建。

CLI 安装脚本的来源尚未确认，用户对是否改为强制预装也回复“待定”。因此 CLI_INSTALLER_URL 当前为 None，自动安装入口在任何网络请求或 shell 执行之前返回明确 pending 提示。没有填入虚构域名，没有恢复旧厂商安装源，也没有把预装要求视为已接受的最终产品方案。Python 本地引擎的已配置发行包自动下载逻辑仍保留。CI 从本仓库构建 Rust CLI 供测试，不代表面向用户的新安装方案。

## 验证记录

以下是本机本轮记录，各组存在交集，不能将数量直接相加。原始日志位于被忽略的 .local/issue-2/，不含在 Git 交接中。

| 验证 | 结果 | 本地证据 |
| --- | --- | --- |
| 根 scripts/hooks/lint.sh | PASS；已处理 Windows 类型检查及 Ruff 路径问题 | project-lint-final.log |
| 后端 tracing/metrics/MCP/模型 headers 等定向测试 | 245 passed、6 skipped | python-targeted.log |
| 最终品牌/Webhook/真实指标导出/内部500/PG0解析/Worker | 38 passed | backend-final.log |
| 独立后端基础复审测试 | 48 passed；另品牌9项通过 | backend-independent-review-tests.log、backend-independent-review-extra-tests.log |
| Web 测试 | TZ=UTC 下 333 passed；默认上海时区有原有相对日期测试失败 | web-tests.log |
| 真实 Next HTTP smoke | PASS：401、登录跳转、会话 Cookie、健康成功/失败、503诊断、客户文件名与字节保留 | web-http-smoke.log |
| coding-agents 全量 | 1312 passed、21 failed；21失败全部在原 HEAD 独立基线存在，未标全绿 | plugin-final-results.json、plugin-baseline-comparison.json |
| ZCode | 103 passed | zcode-tests.log |
| Claude 插件重点测试 | 156 passed；1个Windows符号链接权限用例未执行 | claude-plugin-tests.log |
| OpenAPI | 官方脚本重新生成成功；独立生成JSON一致、无旧品牌 | openapi-review.json |
| Python 本地引擎 | 263 passed、2 skipped、1 failed；唯一失败为沙箱拒绝查询当前进程命令行，该方法与原 HEAD 逐字一致 | embed-final-tests.log |
| 模板同步 | 9 passed，包括根/嵌入模板字节一致 | 引擎子任务记录 |
| Node 本地引擎 | 11 passed；打包通过 | 引擎子任务记录 |
| 原 Python SDK 嵌入配置 | 8 passed；SDK公开命名不变 | 引擎子任务记录 |
| Rust | cargo fmt 通过；cargo test 未完成 | rust-cli-tests.log |

独立复审已修复：失败 Webhook 的错误字段、启动 warning/Worker stdout 漏字、插件同名外部 MCP 注册覆盖风险、本地控制 API 消费方旧 header、Node/Rust 失败诊断泄露、Linux embed CI 未准备本仓库 CLI。

## 尚未完成的验收

1. 确定并实现受信任的 CLI 自动安装发行来源，再验证首次无 CLI 安装场景；当前不能声称完整本地自动安装链已交付。
2. 提供正式服务/文档地址和发布包配置，执行实际发行安装验证；本轮未发布任何包。
3. 在具备数据库条件的环境运行新增 test_98_public_brand.py 及 test_64_webhooks.py 系统故事，验证真实 API/MCP/原 SDK/异步数据库链。当前 Windows pg0 启动报 Could not determine data directory，Docker/WSL 不可用，系统测试未通过验收。
4. 在可访问 Rust registry 的环境完成 cargo test；当前在线下载因 Windows schannel 凭证错误失败，离线缺依赖。
5. Python embed 的进程查询测试需在允许该系统调用的环境复核；coding-agents 的21个原基线失败仍需在项目支持的测试环境消除或复核；不能以“原有失败”代替发布前全套回归。

现有根检查和边界测试足以审阅代码候选，但不构成生产发行或 Issue 关闭依据。旧 M2 原始验收证据及其 OBSERVED_LIMITATION 保持原归属。

## 2026-10-14 提交前复核

用户授权提交代码并创建 PR。品牌增量使用独立分支 `feat/issue-2-agentstratum-brand`，PR 目标为原工作基线分支 `hosted/p1-m2-product-v2_1`；原 M2 和其他 hosted 工作不作为本 PR 的新增内容。远端新增的产品体验审查文档继续保留。

- 按 `.claude/skills/code-review/SKILL.md` 复核核心接口、配置、诊断边界、CI 及测试覆盖，补齐新增 `customer_span` 的参数与返回类型标注。
- 本轮重新运行根 `scripts/hooks/lint.sh`：PASS（`.local/issue-2/pr-lint.log`）；`git diff --check`：PASS。
- 本轮品牌与 tracing 回归：53 passed、1 skipped、5 errors（`.local/issue-2/pr-tracing-tests.log`）。5 项错误均发生在 `test_tracing_spans_verification.py` 的 fixture 初始化阶段：模型镜像 `hf-mirror.com` 无法提供可下载的模型元数据，且本机无缓存；未进入这些用例的业务断言，不能标为通过。
- PR 保持 Draft，关联 Issue #2，不自动关闭 Issue；前述发行输入、实际安装验证、系统故事与 Rust/插件回归待办仍然有效。本次授权不涉及合并或发布。
