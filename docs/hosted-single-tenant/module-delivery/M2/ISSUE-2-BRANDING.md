## 2026-10-15 错误展示与内部追踪收尾

用户确认：品牌名称在定义处修改，不通过扫描运行时错误内容去除商标。本节优先于下方历史快照；PR 保持 Draft，未合并、未发行。

- 删除 CLI、Claude Code、Coding Agents 和 Web 代理按 `hindsight` 关键词替换错误的逻辑。客户标识、服务端公开错误和状态码保留；Web 自身未知异常及后端未知内部异常仍返回通用提示。
- 删除 OTLP 的 `CustomerSpanExporter`、`customer_span` 和遥测字符串过滤，恢复原生异常记录、原因链、堆栈及源码路径；保留 agentstratum 指标/Span/服务标识。内部追踪按运营方诊断通道处理，不作为客户公开错误接口。
- 一并删除独立 ZCode 和内部本地引擎封装中的同类过滤，恢复异常 cause；不改变客户端发行范围，不启用本地引擎自动启动。
- 更新已有回归，新增真实 CLI/HTTP 客户端的 403 场景，覆盖大小写不同的客户 Bank 名。修改前对应 Web 7 项、Coding Agents 2 项、Claude Code 4 项、CLI 1 项、OTLP 1 项回归失败；修改后通过。

本轮验证：CLI 116 项单元和 13 项进程测试通过；Coding Agents 1,332 通过/6 跳过，类型检查通过；Claude Code 226 通过；Web API 定向 56 通过；后端错误与追踪定向 112 通过；独立 ZCode 105 通过，本地引擎 Node 封装 11 通过。各组有各自边界，不代表真实服务/宿主/华为云验收。

修改文件 Ruff、Prettier、Rustfmt 和差异检查通过，并按 code-review 规范复核。仓库总 lint 已尝试，但局部检出缺少 uv.lock，停在 frozen sync；不声明完整 CI 通过。追踪测试显式使用 always_on 采样，未改变生产采样配置。CLI 在 Linux 验证，保留两项既有 dead-code warning。

## 2026-10-15 R6–R8 修复与验证

用户已授权继续处理剩余审查问题。R1–R8 均已完成代码修复；PR #3 仍为 Draft，未合并、未发行，Issue #2 仍待完成发行与系统验收。本节的当前状态优先于下方历史快照。

- **R6**：Coding Agents 根入口改为导出实际存在的 `AgentstratumOpencode2Plugin`。在已有 HTTPS tarball 安装故事中增加安装后导入检查，分别按 OpenCode v1 的 package main 和 v2 的根 index.js 加载，验证导出形状；候选工作流已有步骤会执行此故事。
- **R7**：CLI 在构造通用 API client 前分发 fs；远端命令按显式参数、保存的挂载配置、Profile/环境/配置文件合并，最后校验实际 endpoint 与 bank。本地 logs/status/stop/unmount 无需远端配置；明确选择的无效 Profile 仍报告错误。换地址不继承其他地址的已存 token；显式 token 和独立环境 token 仍可使用。
- **R8**：手动 Hook 命令加入稳定的 `AGENTSTRATUM_HOOK_OWNER=agentstratum-memory` 归属标记，安装路径变化时替换本插件注册，卸载按归属删除。保留混合组中的其他 Hook、matcher、空组与其他设置；路径使用 shell quoting。当前目录原有的精确命令仍可识别，不按脚本名猜测其他目录中未标记命令的归属，不新增历史配置迁移。

验证：

- Rust CLI：**116 项单元 + 12 项进程回归全部通过**。新增 9 项 fs 回归驱动真实 CLI 及本地 HTTP 接收端；同一进程测试组在修复前为 4 通过、8 失败。覆盖明确地址、保存后 sync、Profile/环境回退、配置优先级、凭证目标、缺失/非法地址和本地命令。
- Claude Code：**224 项通过**。新增的换目录/混合组保留与特殊字符路径执行用例，在修复前均失败、修复后通过。
- Coding Agents：typecheck、ESM/DTS build、真实 npm tarball 经 HTTPS 安装及 OpenCode v1/v2 入口加载、Codex 配置注册/卸载通过。旧 tarball 在相同故事中复现根入口 SyntaxError。
- 按仓库 code-review 规范复核变更范围、错误传播、凭证边界、Hook 归属及测试。修改文件 Ruff、Prettier、Rustfmt 和 diff whitespace 检查通过；没有新增服务端协议或依赖。

限制：总 lint 在局部检出的 uv sync 阶段因缺少根 pyproject.toml 受阻。CLI 在本机 Linux 构建测试，沿用显式 OpenSSL 路径，保留两项既有 dead-code warning；未声明 macOS/Windows、真实宿主会话、华为云线上或数据库系统验收通过。Hook 未标记的其他历史安装目录不会被猜测删除，符合不做迁移的范围。

> 2026-10-15 渠道补充：已确认 OBS + CDN 公开分发，Coding Agents 通过 `.tgz` URL 安装，不要求按包名 `npx`。新增固定版本 CLI 安装脚本及 HTTPS/校验回归；正式资源地址与线上验收仍待完成。详见 [CLIENT-DISTRIBUTION.md](CLIENT-DISTRIBUTION.md)。

> 2026-10-15 更新：Issue #2 已确认只对外发行 CLI、Coding Agents、标准 Agent Plugin、Claude Code 四类客户端；服务端包/镜像、本地引擎、Web 安装包、SDK、Helm 不发行。远端连接收敛和客户端候选构建已继续实施。详见 [CLIENT-DISTRIBUTION.md](CLIENT-DISTRIBUTION.md) 的当前行为、测试证据与未完成门槛。下文旧的本地引擎发行和 Rust 未验证记录属于此前快照；此次没有重跑服务端全量系统验收，不据此关闭 Issue。

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

| 边界           | 本轮行为                                                                                                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| REST / OpenAPI | agentstratum API 标题与说明；77 个路径的生成规范不含旧品牌；未新增 URL 前缀或改业务字段                                                                                         |
| Web API        | 保留上游公开错误及状态，不按品牌关键词过滤；健康响应不暴露后端地址；登录、Cookie、重定向、下载原有鉴权与流式语义保留                                                            |
| Webhook        | X-Agentstratum-Event、X-Agentstratum-Signature、X-Agentstratum-Signature-V2；标准 X-Hub-Signature-256 保留；保留 HMAC 算法、时间戳及原始 body；保留 header 忽略大小写防覆盖保护 |
| MCP            | 服务端身份 agentstratum-mcp-server；原中性服务端工具名不变；本地插件身份、带品牌工具/配置、注入标记和宿主注册同步修改                                                           |
| 模型请求       | 产品 User-Agent、X-Agentstratum-Bank-Id、Claude 工具 MCP 前缀、Gemini batch 标识使用新品牌；客户 prompt/output 不替换                                                           |
| 指标与内部追踪 | agentstratum 指标、span、scope、服务名和配套 Grafana/Prometheus 配置；内部追踪保留完整异常与堆栈                                                                                |
| 本地运行       | agentstratum CLI/agentstratum-embed 命令、配置与缓存目录、日志、引擎启动参数和本地 control API 合同                                                                             |

REST、MCP、异步任务状态、失败 consolidation Webhook、心智模型刷新历史及 LLM 请求记录中的客户错误消息按异常类型处理，不再按品牌关键词过滤。明确的业务拒绝保留原因和客户标识；ValueError 仅在各操作已明确的参数/资源校验分支保留原文，未知内部异常返回固定通用提示。异步错误在捕获异常时完成分类，再写入客户可读记录。模型未配置、图片能力不足的文案在异常产生处直接改为客户可理解的说明。完整异常与堆栈保留在服务端日志；不对响应 body 或文件流做全局字符串替换。后续收尾已移除客户端/Web 品牌关键词过滤，并恢复内部 OTLP 完整诊断。

2026-10-15 用户确认服务端运行日志仅供运营方查看，客户不可见：已撤回默认 stdout 的 PublicLogFormatter 过滤，恢复原始日志名称、文案、异常原因链和堆栈；删除仅为该过滤配套新增的 AGENTSTRATUM_INTERNAL_LOG_FILE 分流配置，无需额外配置文件日志才能保留完整诊断。原有文本/JSON 格式、日志级别和 JSON 字段选择配置保持不变。API、MCP、Webhook 等客户可见出口的错误处理不受本次撤回影响。OTLP 导出过滤也已撤回，使用原生导出器保留诊断属性、异常堆栈、客户内容及 trace 关联信息。

## 发行时必须提供的配置

| 配置                               | 用途                                                   |
| ---------------------------------- | ------------------------------------------------------ |
| AGENTSTRATUM_API_URL / apiUrl      | 插件连接实际服务；云模式无猜测的默认域名               |
| AGENTSTRATUM_CODING_AGENTS_PACKAGE | 经运营方确认的 npm 自动更新目标；未配置不查询 registry |
| AGENTSTRATUM_EMBED_PACKAGE         | 本地 Python embed 发行 spec；开发可指定本地包路径      |
| AGENTSTRATUM_EMBED_API_PACKAGE     | 本地自动下载的 API 发行 spec                           |
| AGENTSTRATUM_EMBED_CP_PACKAGE      | 启用本地 Web 时的发行 spec                             |
| AGENTSTRATUM*API*\*                | 服务入口读取的公开配置前缀；内部映射到既有引擎实现     |

工作区 npm 名称为私有构建标识，不代表已在 npm 占用或发布。实际域名、文档站和分发地址未创建。

CLI 安装脚本的来源尚未确认，用户对是否改为强制预装也回复“待定”。因此 CLI_INSTALLER_URL 当前为 None，自动安装入口在任何网络请求或 shell 执行之前返回明确 pending 提示。没有填入虚构域名，没有恢复旧厂商安装源，也没有把预装要求视为已接受的最终产品方案。Python 本地引擎的已配置发行包自动下载逻辑仍保留。CI 从本仓库构建 Rust CLI 供测试，不代表面向用户的新安装方案。

## 验证记录

以下是本机本轮记录，各组存在交集，不能将数量直接相加。原始日志位于被忽略的 .local/issue-2/，不含在 Git 交接中。

| 验证                                                 | 结果                                                                                            | 本地证据                                                                         |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 根 scripts/hooks/lint.sh                             | PASS；已处理 Windows 类型检查及 Ruff 路径问题                                                   | project-lint-final.log                                                           |
| 后端 tracing/metrics/MCP/模型 headers 等定向测试     | 245 passed、6 skipped                                                                           | python-targeted.log                                                              |
| 最终品牌/Webhook/真实指标导出/内部500/PG0解析/Worker | 38 passed                                                                                       | backend-final.log                                                                |
| 独立后端基础复审测试                                 | 48 passed；另品牌9项通过                                                                        | backend-independent-review-tests.log、backend-independent-review-extra-tests.log |
| Web 测试                                             | TZ=UTC 下 333 passed；默认上海时区有原有相对日期测试失败                                        | web-tests.log                                                                    |
| 真实 Next HTTP smoke                                 | PASS：401、登录跳转、会话 Cookie、健康成功/失败、503诊断、客户文件名与字节保留                  | web-http-smoke.log                                                               |
| coding-agents 全量                                   | 1312 passed、21 failed；21失败全部在原 HEAD 独立基线存在，未标全绿                              | plugin-final-results.json、plugin-baseline-comparison.json                       |
| ZCode                                                | 103 passed                                                                                      | zcode-tests.log                                                                  |
| Claude 插件重点测试                                  | 156 passed；1个Windows符号链接权限用例未执行                                                    | claude-plugin-tests.log                                                          |
| OpenAPI                                              | 官方脚本重新生成成功；独立生成JSON一致、无旧品牌                                                | openapi-review.json                                                              |
| Python 本地引擎                                      | 263 passed、2 skipped、1 failed；唯一失败为沙箱拒绝查询当前进程命令行，该方法与原 HEAD 逐字一致 | embed-final-tests.log                                                            |
| 模板同步                                             | 9 passed，包括根/嵌入模板字节一致                                                               | 引擎子任务记录                                                                   |
| Node 本地引擎                                        | 11 passed；打包通过                                                                             | 引擎子任务记录                                                                   |
| 原 Python SDK 嵌入配置                               | 8 passed；SDK公开命名不变                                                                       | 引擎子任务记录                                                                   |
| Rust                                                 | cargo fmt 通过；cargo test 未完成                                                               | rust-cli-tests.log                                                               |

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
