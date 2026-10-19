# 整合交付结果

`LOCAL_ACCEPTANCE_PASS / INDEPENDENT_REVIEW_CLOSED / DRAFT_FOR_USER_REVIEW`，2026-10-19。源码检查点`5d350568ae3d7537e452999cb6d0fae86b64563b`；未合并main、未公开发行。

[Draft PR #8](https://github.com/RSIXDB/hindsight/pull/8)已创建，base为main，双方成果位于同一个整合分支；原PR #5保留。

本方独立品牌/UI候选`b799f721`与同事PR #3净10提交已经整合到`integration/agentstratum-brand-ui-clients-20261019`。实际同事输入为`fd69ec9bf..2885dd33b`，采用有原作者与`-x`来源的逐提交重放，排除旧hosted分支另33提交。本方多用户、多Key管理、Workspace schema隔离继续排除。原生auth extensions与migrations相对固定main没有diff。

用户已确认：`contextdb_name`继续控制UI/API/OpenAPI/MCP/服务显示名；发行、CLI、插件、目录和协议标识固定`agentstratum`。详细语义冲突及逐提交映射见[CONFLICT-RESOLUTION.md](CONFLICT-RESOLUTION.md)，逐路径内容摘要见[SOURCE-MAP.json](SOURCE-MAP.json)。原品牌分拆快照本无可提取Hook补丁；本次新增客户端/Hook改动来自同事PR #3，不冒充从原快照提取。

## 当前验证

所有重型任务均通过原唯一共享runner/lock串行运行，日志集中在主仓`.local/product-brand-ui/runs/integration-20261019`。旧报告的PASS没有继承为本轮证明。[VALIDATION.json](VALIDATION.json)绑定源码、原生结果与制品哈希。

| 检查 | 本轮实际结果 | 证据（上述日志根） |
| --- | --- | --- |
| Frontend unit/type | 61文件/379项通过，tsc通过 | unit-07 |
| Coding Agents build/type/unit | 83文件/1362通过、6跳过；最新安装器/host追加回归267通过、2跳过 | unit-07；checks-02 |
| API scoped deterministic tests | 303通过、71 local-ml条件跳过、1真实LLM标记排除 | unit-07/native-api.log |
| Claude Code | 226通过 | unit-07/claude-code.log |
| 必需全仓lint与额外Python检查 | PASS | checks-01 |
| knip blocking | files/dependencies PASS；完整knip/vulture advisory保留供审查 | checks-01 |
| OpenAPI/SDK | native重生成，485个受检路径重复0漂移；432基线公共签名、空元素guard与Go3实际消费者/序列化测试通过 | api-generation-02；checks-06 |
| Rust SDK/CLI | SDK regex实际编译/反序列化回归通过；CLI153单元/进程通过，live25在独立原生fixture全部通过；fmt通过 | checks-04、checks-07、runtime-04/cli-live.log |
| 三类插件打包/HTTPS安装 | 实际包与许可证/校验和；8项HTTPS故事、11 subtests通过，含实际tarball安装/注册/重装/卸载 | checks-05 |
| Linux发行候选与许可证 | 默认release profile构建、固定cargo-about0.9.1许可证、9项release进程与实际native API读列表smoke通过；四类候选CRC/checksum通过 | release-02；four-client-candidates；preview-01 |
| Production standalone | PASS，真实`/brand-ui`构建 | checks-05/production-build.log |
| 原生API/MCP/worker/PG/UI/browser | PASS，共19组；5项SDK黑盒故事通过；全部fixture PG正常停止并保留数据 | runtime-04 |

原生场景包含四类客户端真实连接（CLI、Coding Agents stdio、实际Claude插件warm launcher、标准Agent Plugin manifest驱动HTTP MCP）、特殊bank ID、有界61项选择/搜索/返回、移动导航、locale及query/hash、真实归档导出/ZIP CRC/导入回读、MCP initialize/get_bank、双名称同一制品、旧页签保留输入且拒绝写入、实际操作详情Download正常200后旧页签409且零转发/保存/重试、前后端名称不匹配与服务离线拒绝、退出与服务重启后撤销、Host/Origin和native key边界。真实宿主会话没有执行，不以协议适配器替代该证明。

UI制品SHA-256：`7bb60c91851cc4d621a55293f66a18bc9e9a2c568ffe4717e8dffd4f65e111cb`。运行时只更换`contextdb_name`，未重复构建第二个品牌。

## 审查与修复

独立审查者的[INDEPENDENT-REVIEW.md](INDEPENDENT-REVIEW.md)保留原始I1–I4与逐轮复审。已实施同名MCP ownership保护（HTTP/stdio/坏配置/重装/卸载及11家JSON宿主＋Codex）、独立Workspace MCP Endpoint、动态运行banner与worker、persistent host配置错误在共享factory转disabled。Rust实际编译另发现缺regress runtime依赖，SDK lock只补该依赖项。原生CLI发现清空cron被Option省略；CLI完整trigger overlay显式传cron/tags_match null，API/SDK公共合同不改，扩展原live故事后25全部通过。

本轮失败保留：依赖准备误判、Coding Agents临时目录Git祖先与初次不完整namespace、旧trace断言、Rust缺lock/缺runtime crate、CLI旧隐式8080 fixture、runtime helper遮蔽stdlib queue、原生nullable PATCH及旧MCP结果包装解析。各次FAIL不算PASS，只有修复后的实际执行被计入当前结果。

## 证据边界

- 内存/pid由内核限制，主进程3GiB/256、PG512MiB/96；CPU affinity为0–1。请求1.5核quota但此WSL未内核落实，准确标为false，实际CPU上界2核。
- API的71项local-ml测试与Coding Agents的6项system-sqlite3测试未执行；实际provider均为显式本地stub，不是模型质量或真实模型服务验收。
- 远端CI、多平台发行、真实第三方宿主全新安装会话、OBS/CDN公开渠道与生产部署尚未执行。下载根仍用明确占位符，没有编造地址。
- Linux release候选与许可证已完成，独立源码终审I1–I4全部关闭、零Must fix；工件独立复审也通过，已推送并创建Draft PR #8。主干合并仍交用户决定。

## 整合预览与本地候选

[中文Workspace列表](http://127.0.0.1:28921/brand-ui/zh-CN/dashboard)与[示例概览](http://127.0.0.1:28921/brand-ui/zh-CN/banks/agentstratum-demo?view=home)已READY，同一production artifact，3个Workspace/5文档/13事实，隔离本地stub数据。最长2小时，正常停止后保留数据/配置/容器。[OPERATIONS.md](OPERATIONS.md)给出本session停止路径、目录与边界；不恢复其他session的28910/28911体验。

四类候选均在本地`runs/integration-20261019/four-client-candidates`，MANIFEST绑定源码与全部12个文件摘要；CLI为Linux amd64的实际release binary（SHA-256 `9e7a3afb3b6e83babb6052628c9aeb99ec1b200b71492ec1c322df3aff4e92f9`）。包含CLI/第三方许可证、三种插件、安装脚本及SHA256SUMS。没有上传云存储或公开发行。

独立工件补充复审：`PASS_LOCAL_CANDIDATE_ARTIFACT_REVIEW`，12个manifest摘要及7个SHA256SUMS目标、ZIP/tgz完整性与许可、ELF架构、源码无漂移及运行中preview均已独立核对，无新增Must fix。预览是明确保留的两小时lease，不冒充已经cleanup。

## 后续任务：ContextBase 命名解耦

用户另要求以ContextBase为产品展示名，并将解耦目标和验收交给新session。[新任务交接](../contextbase-naming/HANDOFF.md)与[目标/验收](../contextbase-naming/GOALS-AND-ACCEPTANCE.md)已另行持久化。本报告仍只证明原AgentStratum整合源；ContextBase实施尚未开始，不继承本报告PASS。
