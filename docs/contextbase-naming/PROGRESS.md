# 实施进度

- 2026-10-19 11:45 CST：输入/祖先/dirty 核验，建立独立工作区，SESSION-ACK 已写。
- N01/N02：IN_PROGRESS，开始真实消费者盘点与兼容映射。
- N03–N12：NOT_RUN；尚无 ContextBase PASS。
- 资源：旧 preview-01 持有唯一锁，等待具体停止授权或租期结束。无抢停/删锁。

- 11:55 CST：用户授权正常停止 preview-01，STOP 已写，原 runner 已释放锁；新 prepare-01 通过唯一 runner 执行。新 worktree/venv 均独立，工具缓存只借用明确路径。
- N01/N02：真实路径盘点和逐层兼容策略已落盘。保留全部外部机器身份；本轮默认展示 ContextBase / 部署 slug contextbase。
- N03/N04：实施 additive /product-config/v2，保留 v1 SDK 模型/严格键集；跨语言默认值和 manifest 展示字段由 brand/definition.json 生成。待测试，不宣称 PASS。
- unit-01：frontend 379 PASS / 10 FAIL，失败集中于 auth/proxy 测试仍 mock v1 默认、而新默认是 v2；实际 mismatch 503 符合失败关闭预期。更新 fixture 为明确 v2 ContextBase，保持原会话/Origin/Host/转发断言；v1 独立回归继续保留。首次失败日志不覆盖。
- 独立初审明确发现 CLI/skill 展示遗漏、历史测量误套品牌变量、旧配置模式 API-only 展示不一致、单字符梯度和归因统计联动。已逐项修复并保留原协议/工具/历史 transcript；最终证据复审仍未通过。
- unit-02：frontend 389 PASS/type PASS；Coding Agents build/type PASS，11 FAIL（旧展示断言及新增提示联动），日志保留；更新精确展示预期及历史归因兼容后 unit-03 正在跑。
- lint-01：必需全仓 lint PASS；额外 Claude lint 报 import 排序，已修复。blocking knip 尚未执行，不能由 lint PASS 推断。
- unit-03：frontend 390/type PASS；Coding Agents build/type PASS，1367 PASS/6 SKIP/1 FAIL。剩余为 opencode2 宿主 companion skill 的旧展示断言，已更正到 ContextBase，保留 skill ID/path/注册断言。API/Claude 在该串行脚本中尚未运行。
- N05 生成器增加缺失/null/boolean slug 和非法历史名称类型反例，非法输入需在写任何输出前失败；品牌历史只用于归因识别，禁止改写 transcript。
- unit-04：frontend 390 PASS，Coding Agents 1368 PASS/6 SKIP。API 387 PASS/1 SKIP/1真实LLM标记排除/1 FAIL：本次 lint 环境装有本地 ML，原先71项条件跳过中多数实际执行成功。失败指出 telemetry service.name 意外跟随 display_name；已修复为固定默认协议身份、显式旧 slug 继续保留原行为，显示 banner/title 独立。未放宽 worker 断言。待 API复跑和 Claude/安装检查。

- lint-02：必需lint、额外Claude lint、blocking knip PASS；生成器19目标round-trip与非法输入反例PASS。发现package.json的Prettier自动parser与显式json parser不同，已改生成器按filepath格式化；最终固定点检查必须直接在lint后运行--check，不用再次生成掩盖漂移。
- build-01：独立Rust target从已核验缓存复制，当前源Rust SDK实际编译/旧schema回归PASS；CLI、候选打包与production build继续执行。
- build-01 完成：当前Rust SDK/CLI测试与构建、三插件打包、HTTPS安装8项/11subtests、production standalone（/brand-ui）全部PASS。其他平台真实二进制仍NOT_RUN；安装脚本四平台选择测试不是四平台编译。
- N05 drill-01 已在runs下独立完整源码fixture启动；只改brand/definition.json，实际生成/构建/消费者/恢复比较，未修改产品工作区源文件。

- drill-01：fixture生成/检查、实际Python API、Coding Agents build/type、Rust CLI build/help、三插件归档PASS；UI prebuild因fixture未链接workspace子目录的tsup依赖失败（exit127）。该记录保持FAIL；修复fixture依赖布局，不修改业务实现。drill-02将同时包含fixture原生OpenAPI/SDK重生成和恢复生成，以覆盖接口元数据。

- unit-05：修复后API390 PASS/1既有SKIP/1真实LLM标记排除；Claude226 PASS；无tarball参数的安装回归7PASS/1SKIP/11subtests，实际tarball8PASS证据单列build-01。
- drill-02：加入真实fixture OpenAPI/SDK生成、432声明/Go消费者回归均PASS；UI构建暴露Turbopack禁止node_modules越过fixture root的symlink，保持FAIL。drill-03将复制依赖到fixture内，保持原Next root和业务代码不变。
- 独立R10：发现manifest.name篡改后重新生成ledger可掩盖identity漂移；已增加四类真实manifest/Cargo主bin/installer bin/MCP注册键/marketplace源条目与权威映射的写入前检查，以及逐项破坏反例。打包改为完整sync-product-brand --check。lint-03执行中。
- lint-03：全仓lint/额外lint、blocking knip（files/dependencies）、advisory扫描、lint后立即完整brand-check零漂移、identity破坏反例及19目标round-trip全部PASS。独立R10已关闭；另按审查建议补跑CI一致的unlisted knip待执行。
- extra-static-01用了错误的统一root Ruff配置，报告既有包的import分组差异；extra-static-02使用各包原生配置检查同一组改动文件PASS，无改动既有import规则。原失败记录保留。
- 准备冻结源码提交：所有重型lint/test均通过唯一runner运行，提交禁用自动hook仅避免在runner外重复启动重型任务；不跳过必需检查。后续仍需N05/N06/N09及独立证据终审，当前不是完整交付。

- N05完整演练完成：drill-03实际构建/API/SDK/CLI/插件/UI，drill-03-resume-b完成实际Atlas Grove页面、两类stdio客户端、ContextBase恢复与接口再生成；5132文件对冻结source-checkpoint复核，fixture与原workspace均零漂移。手工生产组件/manifest/安装脚本改动清单为空，手工只改brand/definition.json。前序3次fixture构建/探针失败及resume的MCP宿主标识遗漏均保留。
- final-01：CI一致knip files/dependencies/unlisted PASS；现源码SDK再次生成0漂移；完整brand-check/Rust fmt PASS；新三插件包和实际HTTPS8项/11subtests PASS；冻结源码production standalone再次构建PASS。
- N05正式记录见SECOND-RENAME-DRILL.md。release-01正在生成当前Linux默认release profile及许可证；随后进行同制品双展示名的API/MCP/浏览器/实际客户端验收。

- release-01：工具链版本/可执行hash和实际API/SDK import来源已记录；cargo-about0.9.1、当前许可证生成、Linux默认release build、9项release进程测试PASS。
- runtime-01：CLI live25及真实release ELF的HTTPS安装/重装PASS；随后harness解压包CRC检查引用了错误局部变量content_zip而NameError，已修复验证脚本。该轮FAIL/cleanup保留，无产品源码修改；重新执行完整native回归。

- runtime-02：四类客户端已实际连接原生API、CLI live25及release HTTPS安装/重装PASS；Chromium因任务TMPDIR过长超过Unix socket路径限制而退出。已按交接namespace经验，将仅该Chrome进程的/tmp绑定到本次OUT/chrome-tmp，真实文件仍集中runs；不改系统TMPDIR或资源锁。FAIL及PG/子进程cleanup记录保留。
- runtime-03最终PASS：23组native/browser/client、7个SDK故事，CLI live25、真实release HTTPS安装/重装、同UI制品两名称、旧页签下载409零转发/保存/重试、所有本轮子进程与PG清理，数据保留。
- 四类候选stage-01 PASS（12文件、许可证、ZIP/gzip/校验和）；独立终审重算5132源码、825UI、12候选hash零漂移，无未关闭源码Must fix。仅交付docs提交与draft PR状态待补核。
- 独立文字校准已落实：node:sqlite条件跳过；Python生成FILES清单改归generated，统计473生成/33适配工作流。

- b5a01c4e7提交结果/兼容/复核/来源与审查文档，已推送专用分支；创建OPEN Draft PR #9（base整合分支），原#8保留，主干未合并。远端检查列表为空，NOT_RUN。N01–N12本地交付已完成，现做最终文档/远端状态补核。
