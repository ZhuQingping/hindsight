# 品牌/UI 独立交付结果

状态：`LOCAL_ACCEPTANCE_PASS / CODE_REVIEW_CLOSED / DRAFT_FOR_USER_REVIEW`。2026-10-18。此前原生运行与 knip 阻塞已解除，必需本地验收已完成；保持 draft，由用户审查与决定合并。

分支：`product/agentstratum-brand-ui-20261016`。基线：`f51b165a5165b1042ba0b6408fcffb5bc1a80fdb`。初始实现：`cbd42fcae`；续验修复：`72218e9f2`；最终源码提交：`9ba259fa386f56c97c9b5af64901f5e3fb228815`。PR：[Draft #5](https://github.com/RSIXDB/hindsight/pull/5)。没有合并 main。

## 实现及本次修复

独立产品 UI、运行品牌 `contextdb_name`、Workspace 展示术语、语言回落、指南与原生 SDK/REST/MCP 接入、单节点 UI 会话及文件传输均已交付。多用户、多 API Key 管理、Owner/策略/恢复账本和 Workspace schema 隔离实现未进入本分支。原生 engine、worker、迁移、授权扩展及 integrations 保持基线；Hook 无可提取品牌补丁。

真实语言菜单发现了原单测未覆盖的缺陷：localePrefix=never 下 next-intl 强制前缀跳转后丢失 fragment。改为写入同 basePath 的 locale cookie 后刷新原 URL，实际浏览器已验证 query/hash 保留。补充 cookie path 隔离及重复查询参数回归；清理新增无外部调用的类型与导航重导出，没有添加 knip 忽略项。

## 最终验证

全部重型检查经同一共享 run-bounded.py 串行执行。日志根目录：`/home/cimon/code/hindsight/.local/product-brand-ui/runs`。机器可读结果、哈希和资源记录见 [VALIDATION.json](VALIDATION.json)，逐文件来源见 [SOURCE-MAP.json](SOURCE-MAP.json)。

| 检查 | 最终结果 | 证据（相对日志根目录） |
| --- | --- | --- |
| 前端单测 | PASS：55 文件、348 项，TZ=UTC | unit-final-20261018.log |
| TypeScript 类型检查及 SDK build | PASS | type-final-20261018.log；build-final-20261018.log |
| 全仓必需 lint（ruff/ty/ESLint/Prettier） | PASS | lint-final-20261018.log |
| Next 16 production build / standalone | PASS，真实 /brand-ui 路径前缀 | build-final-20261018.log |
| Python 命名单测 | PASS：11 项；涉及的 Python 源码未变化，哈希已核对 | python-brand.log |
| 独立原生 API/Worker/PG + 生产 UI + Chromium | PASS：完整最终故事 | native-c08-20261018.log；runtime-c08/result.json |
| 同制品 agentstratum / contextdb | PASS：UI、metadata、SVG 导出、真实 MCP initialize/get_bank | runtime-c08/mcp-*.json、downloads、截图 |
| 两品牌原生 API/OpenAPI 标题和非秘密配置 | PASS，no-store；既有路径与模型不变 | final-audit-20261018/result.json；static-result.json |
| 原生归档下载、CRC、multipart 导入、SDK 回读 | PASS，两个原始文档完整到达 | runtime-c08/archive-manifest.json；bank-transfer.zip；原生故事 |
| 旧页签、品牌错配、服务故障 | PASS：输入保留，旧 Recall 仅发一次被拒绝，写入未转发；文件请求亦被拒绝 | browser-requests.json、browser-responses.json、stale-tab-preserved.png |
| 登录/退出/重启、复制 Cookie、Origin/Host | PASS：匿名 401、错配拒绝、离线退出、重启后撤销持续、错误 Origin 403 / Host 421 | runtime-c08 原生故事及日志 |
| 中文/英文/fr 回落、真实语言菜单、移动导航 | PASS：query/hash 保留，移动端功能页和接入无页面横向溢出，无旧管理链接 | runtime-c08/guide-*.png、documents-mobile-agentstratum.png、connect-mobile-agentstratum.png |
| SDK 黑盒命名故事 | PASS：两个品牌，2 项 | runtime-c08/sdk-story.log |
| 特殊 ID 跨品牌资源身份 | PASS：含 %、中文、点号的 ID：SDK 创建/列举/删除，产品名变化后 ID 保持；真实 MCP get_bank | final-audit-20261018/result.json；runtime-c08/mcp-*-get-bank.json |
| knip 文件/依赖阻断检查 | PASS：exit 0，5.88.1 | knip-final-20261018.log；verify-final-20261018-result.json |
| vulture / knip advisory 与最终 code-review | 已执行并审查；新增死导出已关闭，没有未处理 Must fix | post-review-20261018-result.json；CODE-REVIEW.md |
| scope / OpenAPI / env 模板 / 来源 | PASS；原 API 路径和模型完全一致，仅新增 ProductConfig 和 /product-config | static-result.json；SOURCE-MAP.json |

最终 production 制品清单摘要：`ead4662408389127129a975cd4ae916827710553a83bb65b816a538a4db7bd74`。同一制品完成两个名称的重启；清单在运行后仍逐文件匹配。最终浏览器事件中没有未捕获异常。

## 资源与保留边界

用户明确授权正常停止原 READY 体验服务，并指定恢复交由原会话。只通过它的 STOP 文件请求退出；记录为 STOPPED、cleanup_errors=[]、data_preserved=true。原容器 `5a9e46c20eb3c23b61bb7608171bae086a7efe4ca5f1eae4cfe77e18d9adc626`、数据挂载和配置均保留，未删除；本任务不擅自恢复该体验服务。

所有自有 API/UI/Chromium/SDK 服务均已退出；c06/c07/c08 PG 已停止，数据在本任务 runs 的 bind mount 目录保留。四个更早的自有临时容器/匿名卷已按标签和清单核对后清理，不涉及原体验资源。共享锁未绕过、未复制。

wrapper 限制为 3 GiB、256 pids、CPU affinity=0-1；PG 另设 512 MiB / 96 pids，并核验相同 affinity。内核 CPU quota 不受支持，记录 false，没有将请求的 1.5 核 quota 当成内核已执行。资源 JSON 与授权停用记录均已保留。

## 仍未运行的范围

Go/Rust 编译因工具链缺失为 NOT_RUN；源码生成不替代编译。Hook 宿主、真实模型质量、生产部署、人工产品验收和远端 CI 不作为本次通过结论。特殊 ID 的端到端结论以实际测试的 %、中文、点号为界，未声称所有斜杠 ID 路由已端到端运行。

历史失败保留：c01–c05 为资源参数或验证器准备问题；c06 真实发现语言 fragment 缺陷，已修复并在最终 c08 完整复测通过。没有移植旧分支 PASS、跳过测试或将未运行记成 PASS。
