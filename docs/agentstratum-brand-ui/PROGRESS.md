# 实施进度

2026-10-17：已接收。cwd、branch、HEAD 与交接一致；SOURCE-MAP 95 项逐文件哈希全部一致，两个不可变清单哈希符合 HANDOFF。已读仓库 code-review 规范及已安装 Next 16 文档（proxy、运行环境、instrumentation、metadata）。

- 独立 npm 安装首次尝试：共享 runner 在执行前拒绝，其他任务持锁；npm 未开始，NOT_RUN。不停止持锁任务。
- 正在逐项审查全部 diff 与未跟踪源码、会话/品牌/provider/原生文件代理。
- 已添加通用 LINT_SERIAL=1 支持，不引入 hosted 任务；清理产品配置模块的过时 hosted 说明。
- 运行/构建证据尚未产生，不能称为可合并。

审查修复：恢复草稿误删的基线 Gemini 配置控件和 en/zh-CN 文案；memory-defense 删除项仅为原厂 Cloud 营销面板，不影响原生敏感数据策略。系统测试启动器新增可选 database_url，以便品牌故事使用本任务独立 PG。生成适配器从本分支 scripts/generate-clients.sh 构造，验证 Java 7.10.0 jar 固定哈希，无 hosted 环境/源码依赖。

已执行的候选检查：npm ci --ignore-scripts --offline exit 0；独立 slim Python 环境及本地 client/dev/embed/system-tests 安装 exit 0；接口生成 exit 0（Java jar SHA-256 已匹配历史工具清单）。静态 schema 比对：原有 paths 与 schemas 均逐结构相同，仅增加 ProductConfig 和 /product-config。Go/Rust 工具链缺失，编译 NOT_RUN。

后续共享锁由其他会话长期 serve-experience.py 体验服务持有；其循环等待正常停止，非短期检查。unit/type/lint/build/runtime 尚未开始，已通过同一 runner 有界排队，询问预计释放时间，未停止其他资源。轻量 AST 语法解析及 bash -n 已执行；这些不替代测试。

共享锁由持有方自行释放后继续：SDK TS build 与前端 tsc 通过；Python 品牌测试 11 passed。前端首轮 347 项中 339 passed，8 failed 为恢复 Gemini 后其他语言键集未同步；已补回八个语言目录中的原生键（zh-CN/en 维护完整文案，其他 locale 仍明确英文回落）。已启动串行 lint → 前端复测 → production build → 原生 runtime 验证。

全仓 lint、前端 347 项复测与 production build 均 exit 0。使用 /brand-ui 构建以覆盖 basePath；同一 standalone 制品完整服务端/静态文件哈希清单已保存。runtime-c01 在 Docker 创建前因 CPU CFS 不受支持失败，无容器创建；改为 taskset entrypoint 并核验 PG PID 1 affinity=0-1。runtime-c02 已启动独立原生 API/Worker/PG，但准备样例时遇到未声明的 stub extract_facts 请求，测试显式失败并清理了自有资源；已补充明确的 extraction/consolidation 规则，未修改产品引擎，runtime-c03 排队执行。

runtime-c03/c04 的失败分别来自指南标题硬编码及同 URL 带 fragment 导航未触发重载，已根据真实目录文案和 DOM 修正验证器；runtime-c05 已生成三种 locale 的真实 DOM/截图，失败于验证器用 click() 而非 Radix 所需指针事件打开菜单。已改成 CDP 真实鼠标事件，并为后续运行冻结 harness.py 与失败 DOM。以上未以静态或 mock 冒充运行通过。最终 PG 使用任务目录 bind mount，保留明确归属与资源上限证据。

实现已本地提交 cbd42fcae66a3c4e50864a0718bbbc97165e47d0（548 源码/配置/SDK/测试路径），未推送。Java 7.10.0 对三个新增 Python/Go 生成文件输出 EOF 空行；保留规范生成物以避免 CI 重生成漂移，提交前仅忽略 blank-at-eof 做 whitespace 检查，其余检查正常。剩余独立运行/审查仍排队，不以本地提交冒充全部验收。

最终外部阻塞快照：其他会话体验服务已 READY，runner PID 1377292 持锁直到正常停止。本任务自己的 c06 等待队列已停止，未留下无人观察的后台验证。已完成静态最终审查、正式 VALIDATION.json、逐项验收状态和精确恢复入口；准备推送 draft，保持运行门槛未闭合，不称为可合并。四个自有历史 PG fixture/全部子进程均已停止，清理入口等待同一共享锁。

2026-10-17T04:57:13.471882+00:00：实现与证据提交已推送，创建 Draft PR #5（https://github.com/RSIXDB/hindsight/pull/5），明确本地检查通过与动态门槛受阻，未合主干。后续恢复仍用 RESULT.md 的唯一共享 runner 入口。

2026-10-18T00:40:52.647867+00:00：用户要求继续补齐全部剩余验收。同一 worktree/分支、HEAD fc0d2f545、548 项源码哈希和既有 production 制品哈希已复核一致，PR #5 仍 draft。共享锁仍由同一 READY 体验服务占用；依照 HANDOFF 的不停止其他任务规则，已请求用户选择由原会话释放或明确授权正常停用，未擅停。正在审查/补强剩余运行脚本，待锁正常释放后执行，不再以既有部分证据代替完整验收。

2026-10-18T00:43:28.860063+00:00：用户明确授权正常停止 READY 体验服务，保留全部数据、配置和容器，恢复交由原会话。已核对 supervisor PID 与脚本身份，只写其自有 STOP 控制文件请求正常退出，不删除或更改服务数据/配置/容器。剩余验收已在原共享 runner 队列中等待接管。

续验 c06：knip 5.88.1 files/dependencies 阻断检查通过，vulture/knip advisory 已执行；只清理了本任务四个旧 fixture 容器/匿名卷，原体验资源保留。真实语言菜单暴露 localePrefix=never 下 next-intl 强制前缀重定向丢失 fragment，已根据安装源码修复为同 basePath 的 locale cookie + Next router.refresh，补充 query/hash/重复过滤器与 cookie path 隔离回归测试。另移除两个新增但无外部调用的类型导出。当前需重跑相关 unit/type/lint/build，再继续完整原生故事。

修复后 c07 完整原生故事 PASS：真实语言菜单保留 query/hash、archive CRC 与原生下载/multipart 导入及 SDK 文档回读、移动导航和接入、两品牌同制品与真实 MCP initialize/get_bank、旧页签输入与单次拒绝、故障退出/重启撤销均通过，两个 SDK 命名系统故事亦 2 passed。前端348、type、全仓lint、production build、knip阻断检查均通过。最终 advisory 复核发现语言切换改用 Next router 后，原 i18n/navigation 包装器仅剩 Link 被使用，已移除该私有模块无调用者的重导出；将对最终候选重跑同组验证，避免遗留新增死导出。

2026-10-18 收尾：最终源码 9ba259fa3，c08 完整原生故事与两品牌 SDK 系统故事通过；最终前端348、type、lint、production build、knip 阻断检查全部 exit 0。advisory 已复核新增无用导出关闭，原生 Python 25 个提示的基线行相同，无新增 Must fix。补充两品牌真实 API/OpenAPI/no-store 与特殊 ID 创建/跨产品改名保留/删除通过。授权停用的原体验容器/数据/配置仍保留；所有自有服务已退出、PG 停止。已生成当前 RESULT、逐项验收、CODE-REVIEW、549 项 SOURCE-MAP 和带日志/制品/资源哈希的 VALIDATION；更新 PR，不合主干。

2026-10-18 独立审查轮：用户明确要求独立 review 与对应修复，已由不参与实现的独立 reviewer 审查不可变 HEAD 9341d473（完整范围/方法见 INDEPENDENT-REVIEW.md）。确认 R1 操作归档下载旧页签绕过、R2 未变 schema 的 SDK 类型漂移、R3 接入列表缺分页、R4 共享搜索状态不一致、R5 特殊 bank ID 路由误判；初审 CHANGES_REQUIRED（4 P2/1 P3）。既有自审不能代替独立审查。正在修复与添加回归，当前变更尚未验证，不继承上轮 PASS。所有重型任务继续通过唯一共享 runner，不改原体验资源。

本轮新增3个组件回归首轮6 passed；全量前端58文件/354项、SDK模型与请求签名（原生基线固定清单）及Python非空元素6项、tsc已通过。R2固定生成器复现：原生基线正常、加品牌端点后3个旧模型漂移；全关nullable简化会改变其他类型，不采用。现对临时Python/Go输入的components裸items显式nullable:false，原生公开spec和Rust/TS输入保持不变；全量签名已一致。一次生成适配器预处理插入点错误导致未给Java输入，已实际失败记录并修正，不记PASS；维护README从本分支HEAD恢复后重新生成。独立reviewer静态接受修复方向，动态与确定性门槛仍在执行。

生产构建通过，固定规范生成重复一轮566个已跟踪SDK文件无漂移。扩展验收c09在启动前因验证器语法错误NOT_RUN；修正后c10真实通过语言/归档导入/移动端和61工作空间分页搜索返回、特殊bank ID按钮，但验证器错误地使用不存在的?view=operations，没有打开原生配置概览里的Operations列表，最终FAIL。已按源码改为profile/general，并调整CDP闲置连接keepalive及双页失败截图；自有进程/PG均正常停止，保留数据，继续同制品c11。没有把局部通过当完整验收。

2026-10-18 最终独立闭合：源码修复提交14c2d60ea，558路径摘要e0680fc9；独立reviewer逐项复审R1–R5全部CLOSED。c11操作行过滤器只找document export而真实whole-bank操作为export_bank，记录FAIL后修正验证器；同制品c12完整15组检查PASS。实际Download按钮200/ZIP CRC，改名后原旧tab409，native文件请求/保存/重发增量均0；两品牌SDK故事2 passed，两个browser事件集无未捕获异常。rest3 native/knip/advisory/extra style全0；原生/制品/清理与外层资源记录亦由独立reviewer核对。完整RESULT/CODE-REVIEW/ACCEPTANCE/SOURCE-MAP/VALIDATION更新；原体验容器仍exited且数据/配置保留，不恢复、不合主干。开始仅文档证据提交、推送和更新已有draft PR。
