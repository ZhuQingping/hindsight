# 整合进度

2026-10-19：fresh refs核对与对象级净PR预演完成。实际PR base fd69ec9bf，10提交/405路径；4个Git冲突，另识别品牌权威/客户端发行/公开错误与日志/协议及示例/生成物等语义冲突。用户D1已接受“动态显示名＋固定发行与协议标识”。新建自己的integration worktree/branch从b799f721开始；未修改原worktree或其他工作区。源代码和本轮测试尚未执行，NOT_VALIDATED。

10个同事提交已按原顺序cherry-pick -x，作者和原SHA均保留。实际顺序重放比净预演多出api-errors.ts导入冲突（首品牌提交添加临时过滤，后续客户错误修复删除），逐提交合成messageLocale导入并保留后续删除过滤，未whole-file ours/theirs。旧HANDOFF在三处提交重复modify/delete，均按D7保持删除。重放结束HEAD a5954a0ff，仍未验证。D1修复开始：API/MCP/worker runtime名称统一从product_config派生；固定header/发行标识不变；health动态名称与UI公开AGENTSTRATUM连接示例同步。

进入验证准备：本session的preview-20261019-02已通过STOP文件正常停用，所有子进程退出、PG停止、数据配置保留，其他原体验不动。独立Python环境建立；首次安装把Claude插件误当Python项目失败，改按其requirements安装后成功。根npm安装完成，Coding Agents离线缓存缺write-file-atomic，记录失败并转为独立目录联网安装；它的新依赖要求Node>=22.22.2，现有22.19不满足，将安装独立Node工具链并记录官方来源/哈希。不改系统Node/Python、profile或其他worktree依赖。Rust/Go也在同一runner内准备隔离工具链，不以旧分支Rust119等历史通过冒充当前验收。

整合首轮：前端60文件/377项、tsc、Coding Agents build/type全部通过；SDK生成成功，固定Java哈希保持。工具链实际安装并验证版本：隔离Go1.27.2、Rust/Cargo1.99.1、Node22.23.3，均记录官方来源/摘要，无系统profile修改。Coding Agents首轮1315 passed/17 failed/6 skipped：非Git临时目录放在主仓.local下，真实探测读到主仓hindsight及300次提交，破坏测试的非repo假设。准备用bwrap仅在该测试子进程的私有mount/user namespace遮蔽外层主仓.git（宿主文件不变，仍在同一shared runner限额里），保留全部真实fake-repo/git-worktree测试；不修改产品probe逻辑、不跳过失败用例。首轮PG正常停止、数据保留。继续其余SDK/Go/API/Claude/安装故事。

测试隔离收敛：unit02/03漏显式/dev挂载导致/dev/null EACCES，均FAIL；unit04补/dev后仍13项，探测又遇到/home/cimon/code/.git且源仓Git用例因遮蔽主仓元数据失败。改为仅在Coding Agents测试子进程将物理本任务coding-agents-tmp目录bind到namespace内/tmp，TMPDIR=/tmp，保留所有真实源码/Git元数据、完整/dev，宿主/tmp与源码不改。这样临时文件物理仍集中.local，而虚拟非repo路径不嵌于任一Git仓库，不改任何产品代码/测试断言/跳过项。最终以unit05实际全套结果为准，以上失败完整保留。

独立整合审查提出I1–I4，均进入修复与回归：安装器按script ownership保护UI同名远程MCP，扩大检查Qwen/Factory/WorkBuddy/CodeBuddy（ZCode/Trae已有preflight或ownership）；Qwen移除显式user scope。Connect改为管理员提供的完整Workspace MCP Endpoint，避免从API推导与Unicode raw header。runtime banner和worker显示遵守动态名字。persistent host共享加载边界捕获RemoteConnectionError转为disabled并告警，installer仍严格校验；真实plugin入口回归断言fetch和所有child_process调用均为0。

unit06 SDK兼容性与Go实际编译/消费者测试通过；API首次302 passed/71 skipped/1 deselected/1 failed。失败为旧trace断言仍要求持久化原始kaboom；与已接受的公开错误合同冲突。保留原异常重新抛出断言，改为公开trace等于安全消息、operator日志仍含完整RuntimeError，随后重新执行。71 skip是缺local-ml等条件的显式边界，后续记录完整原因，不替代原生stub端到端验收。

unit07最终：前端379 passed、Coding Agents1362 passed/6 skipped、build/typechecks均通过；API303 passed/71 skipped（local-ml缺失）/1 deselected（真实LLM标记）、Claude226 passed、安装脚本7 passed/1 skipped（缺tarball参数）及11 subtests。所有owned PG已停止、数据保留。新增installer HTTP/stdio与重复安装回归将在focused复跑；历史unit07结果不覆盖之后新增测试。独立复审I1–I4静态修复暂无新Mustfix，仍等待最终运行证据。

check01 root lint与额外Claude/ZCode/packager ruff通过；knip files/dependencies blocking通过，完整knip/vulture advisory输出留存。Rust首次--locked因CLI项目忽略/未跟踪Cargo.lock而拒绝，NOT_PASS；将从当前Cargo.toml独立生成CLI lock、归档摘要，再用--locked真实编译/测试，不复制其他分支依赖或修改已跟踪Rust SDK lock。三类插件打包后用显式tarball路径补齐第8项HTTPS安装故事。

最新定向回归checks02：installer/host-client/真实plugin入口共267 passed/2 skipped，Coding Agents types通过。Rust实际编译发现生成ContextdbName校验引用::regress::Regex而SDK只在build依赖树间接含regress，缺运行时直接依赖（E0433）；不是可忽略警告。补SDK runtime regress=0.10，与当前typify生成器一致；最小更新原SDK lock并补合法/非法显示名反序列化回归。新建checks03真实编译与测试，旧失败日志保留。

Rust SDK真实回归通过（独立tracked SDK lock只增regress依赖）。CLI第一轮all-target测试因其旧live helper自动探测8080（health=200、业务404）出现15FAIL，该轮未计PASS。已去掉隐式服务探测及PATH旧binary回退：live25明确标ignored，只有显式独立fixture+--ignored执行，缺fixture时必须失败；普通CLI测试不再访问未授权服务。当前binary替代nested cargo run，退役ui命令明确断言拒绝。checks05当前153项unit/进程测试通过、live25如实ignored，下一步在本任务owned API实际执行25而非以ignored冒充验收。三类插件实际归档成功，8项HTTPS安装故事及11 subtests全部通过（含实际tarball＋注册/重复/卸载）。

接口重复生成api-generation-02完成，spec/Python/TS/Go受检文件0漂移；随后432签名/空元素guard与Go实际3项消费者/序列化回归通过，Agent Plugin manifest通过，Rust两crate fmt check通过。runtime01因本地helper名queue.py遮蔽stdlib queue在启动前失败（未创建服务）；重命名为enqueue-bounded.py，仅排队到同一唯一run-bounded，不增加/绕过锁。runtime02在owned fixture实际CLI25中24过/1失败，找到--trigger-refresh-cron清空时Option省略而非null；修CLI仅在已读完整trigger的请求显式发送cron/tags_match null，保留status/body与URL path编码，扩展原live故事不放宽断言。源码检查点5d350568。runtime03 CLI25全过，4客户端请求实际成功，但native MCP结构为FastMCP structuredContent.result字符串包裹，旧harness错误当对象取bank_id；修解析支持协议实际shape，原bank_id校验保持。以上FAIL与清理证据完整留存。runtime04正在执行最终整合源的全套原生验收。

最终runtime04 PASS（19组）与5个SDK黑盒全部通过，源码5d350568、production artifact7bb60c…，owned PG停止/数据保留。独立源码终审复算3314源码hash849aed…、974来源路径及825制品文件全部零漂移，I1–I4关闭/零Mustfix。release01的cargo-about未启cli feature导致未产binary已记FAIL；release02显式cli feature安装并验证version，独立lock许可fetch/about offline扫描、默认release构建、9项release进程回归、四类候选CRC/checksum全部通过。preview01按唯一锁等release退出后启动，28920/28921/28922新owned数据，READY；相同UI制品、3banks5docs13facts，实际release CLI读native列表smoke成功，旧预览/其他session数据不动。

独立工件复审PASS_LOCAL_CANDIDATE_ARTIFACT_REVIEW：12个manifest摘要、7个checksum目标、ZIP/tgz CRC/许可证/无daemon入口、Linux ELF、release9与CLI API smoke均核对，源码无漂移，无新增Mustfix。远端main只读再次核对仍f51b165a；原brand worktree仍b799f721且clean。进入最终docs本地提交/推送/draft PR；不merge main。预览READY保留限时lease，不标已清理。

交付：e66a73b59提交最终独立审查/来源/结果/验证/操作文档并成功推送新integration分支；创建OPEN Draft PR #8，base main，原PR #5保持。随后只更新交付链接/状态。最终源hash复核0漂移，原worktree clean、main未合并，preview01保持READY。远端CI/人工合并/其他平台和云发布不纳入本地PASS。
