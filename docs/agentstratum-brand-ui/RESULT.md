# 品牌/UI 独立交付结果

状态：`LOCAL_ACCEPTANCE_PASS / INDEPENDENT_REVIEW_CLOSED / DRAFT_FOR_USER_REVIEW`。2026-10-18。独立初审发现4项P2、1项P3；全部修复并由原独立审查者复审关闭，无遗留 Must fix。人工产品接受与主干合并仍由用户决定。

修复源码：`14c2d60eacf9be3e67093f374082eb4fbda3ba39`；分支 `product/agentstratum-brand-ui-20261016`；基线 `f51b165a5165b1042ba0b6408fcffb5bc1a80fdb`。[Draft PR #5](https://github.com/RSIXDB/hindsight/pull/5)，未合并 main。

## 独立审查与修复

[INDEPENDENT-REVIEW.md](INDEPENDENT-REVIEW.md) 保留原始候选 `9341d473` 的 CHANGES_REQUIRED 与独立复审全过程；[REVIEW-FIXES.md](REVIEW-FIXES.md) 对应每项实现/证据。独立 reviewer 与实施者分离，仅执行静态核验并审查实施者通过共享 runner 产生的动态证据，不冒充人工审查。

- R1：操作详情实际 Download 经 productFetch，失败不保存；真实按钮正常200/ZIP CRC，服务改名后同一旧页签409、零原生文件转发、零新增文件和零自动重发。
- R2：修正固定生成器对组件裸数组元素的 nullable 漂移。公开原生 OpenAPI、Rust/TS 输入不变；全部432个旧模型/请求API公共签名保持基线，Python空元素拒绝通过，566个已跟踪SDK路径重复生成零漂移。未复制旧权限SDK。
- R3/R4：接入工作空间选择支持有界加载更多，直接使用共享查询状态。真实61项、首50项外条目选择及 Change Workspace 返回保持查询/列表均通过。
- R5：去除basePath后精确识别资源页，`guide`/`connect`原生bank不再隐藏 Add Document；组件和浏览器均覆盖。

## 当前验证

全部重型任务通过 HANDOFF 指定的唯一共享 run-bounded.py 串行执行。日志集中在主仓 `/home/cimon/code/hindsight/.local/product-brand-ui/runs`。机器可读证据/哈希见 [VALIDATION.json](VALIDATION.json)，558个源码路径来源和候选哈希见 [SOURCE-MAP.json](SOURCE-MAP.json)。

| 检查 | 当前结果 | 日志根目录下证据 |
| --- | --- | --- |
| 前端unit、TypeScript、SDK build | PASS：58文件/354项；新增6项组件回归另复测 | review-unit-all.log、review-type.log、review-build.log、review-final-extra.log |
| 必需全仓lint、生产standalone构建 | PASS，真实 /brand-ui | review-lint.log、review-build.log |
| SDK基线签名/空元素、重复生成 | PASS：432签名、6项pytest、566路径无漂移；guard准确拒绝初审六文件 | review-final-extra-result.json、repeat-generation-review-result.json |
| 原生API/Worker/PG + production UI/Chromium | PASS：完整c12的15组检查，两个名称使用同一制品，MCP initialize/get_bank；无未捕获浏览器异常 | runtime-c12/result.json、mcp-*.json、两组requests/responses及截图 |
| 实际操作归档按钮与旧页签 | PASS：200/CRC → 同一旧tab409；native文件请求/保存/重发增量均0 | runtime-c12/operation-tab-*.json、forwarded-native-requests.json、actual-operation-old-tab-refused.png |
| 原生传输、导航、语言与会话 | PASS：ZIP CRC、multipart导入/SDK回读，移动端，三locale/切语言query/hash，错配/离线不转发写入，退出/重启撤销，Origin/Host反例 | runtime-c12完整故事/截图 |
| 发布Python SDK命名黑盒 | PASS：两品牌2项 | runtime-c12/sdk-story.log |
| 原生API/OpenAPI/no-store、特殊ID身份 | 既有补充证据保留；相关API源码未变，c12重验特殊ID的UI/MCP | final-audit-20261018/result.json、runtime-c12；static-review-result.json |
| Python命名单测 | 11项既有证据保留；相关源码未变 | python-brand.log |
| knip阻断与advisory | files/dependencies PASS；advisory实际执行并复核，25项Python提示的基线行未变，不声称零警告 | review-knip.log、review-advisory.log、review-advisory-audit.json |
| 保护路径、公开OpenAPI与模板 | PASS：engine/worker/migrations/auth扩展/integrations不变，旧paths/schemas一致，仅增加ProductConfig及/product-config | static-review-result.json、SOURCE-MAP.json |
| 独立最终审查 | PASS：R1–R5 CLOSED | INDEPENDENT-REVIEW.md |

同一生产制品825文件摘要：`ce68572d2ae61a4bd7eb9bd89781a9e833cb5c7082da2d0e2e8fb93713c84514`。558路径源码清单摘要：`e0680fc955f976278832fc810a0dbf91e7c8f37e5132c478df47e0ba8d1d84e7`。独立审查者均逐文件复核无漂移。

## 资源、范围与未运行项

用户授权停止的原 READY 体验服务保持停止；容器 `5a9e46c20eb3c23b61bb7608171bae086a7efe4ca5f1eae4cfe77e18d9adc626`、全部数据/配置保留，恢复交由原会话。本轮自有API/UI/Chromium/SDK进程全部退出，c10/c11/c12 PG停止且bind数据保留。没有修改其他worktree或其未提交内容，未绕过共享锁。

runner为3GiB/256pids、CPU affinity 0–1；PG另设512MiB/96pids并核验affinity。内核不支持请求的1.5核quota，明确记录false。c09验证器语法错误未启动资源；c10/c11入口或操作类型选择错误为FAIL，修正后c12完整PASS，历史失败保留。

原生只读inline attachment anchor/img与缓存保留基线，不带页签名称；旧页签保护声明仅覆盖携带页签标识的业务API及本分支适配的归档入口，不宣称所有asset入口保护。

未引入我们自己的多用户、多API Key管理或Workspace schema隔离；原生协议身份不变。Hook无可提取品牌补丁，宿主未运行。Go/Rust编译缺工具链，仍为NOT_RUN；真实模型质量、生产部署、远端CI及人工产品接受均不列为PASS。特殊ID端到端以已测%、中文、点号为界，不声称所有斜杠ID已实测。
