# 独立审查修复与验证

2026-10-18。原始候选 `9341d473c75bc647b0cda3fadb4ac697390a8152`，基线 `f51b165a5165b1042ba0b6408fcffb5bc1a80fdb`。独立 reviewer 未参与源码实现，初审原样保留在 [INDEPENDENT-REVIEW.md](INDEPENDENT-REVIEW.md)，由主实施 session 修复、独立 reviewer 复审。技术验证、独立判断和用户接受分别记录。

| 问题 | 对应修复 | 回归证据 |
| --- | --- | --- |
| R1 / P2：操作详情原生归档下载未带页签名称 | 实际 Download 按钮经 productFetch，非成功响应不保存；pending 禁用和可见错误 | bank-operations-download.test.tsx：真实按钮成功/409 两分支；c12 实际按钮200/ZIP CRC后，旧页签409、零原生文件转发/保存/重发 |
| R2 / P2：未变 schema 导致既有 SDK 类型漂移 | 固定生成器的临时 Python/Go 输入显式标记组件裸 items 非空；不关闭全局简化，不修改公开 spec、Rust/TS 输入 | 全既有 Python/Go 模型与请求 API 签名固定为原生基线；四项 Pydantic null 元素拒绝；432个基线API一致、6项通过；566个SDK路径重复生成无漂移 |
| R3 / P2：接入列表只有首 50 项 | 使用原有 provider loadMoreBanks、总数、pending/end 状态 | 真实 BankProvider 61 项及多页搜索；c12原生61项中首50项以外条目实际选择通过 |
| R4 / P2：Change Workspace 后空输入与已筛选列表不一致 | 直接使用共享 bankSearch | 真实 provider 重挂载及外部共享搜索；c12实际Change Workspace返回保持搜索/列表 |
| R5 / P3：guide/connect bank ID 被识别成资源页 | stripBasePath 后精确比较应用路径 | 普通/特殊 ID、实际资源页、空及 /brand-ui 前缀组件回归；c12两个特殊ID实际Add Document可见 |

当前技术验证已闭合：58前端文件/354项、SDK签名与元素校验6项、tsc、全仓lint、production build、完整原生c12及2个SDK系统故事、knip阻断与advisory均已实际执行；独立R1–R5关闭。Go/Rust编译及人工产品接受仍不作为已通过。固定修复源码：`14c2d60eacf9be3e67093f374082eb4fbda3ba39`。

R2 的复现与候选生成日志在主仓 `.local/product-brand-ui/runs/review-generator-*`、`review-api-generation*`。对照同一 7.10.0 jar：基线正常，初审 spec 出现非空元素被标记可空；关闭 SIMPLIFY_ONEOF_ANYOF 会改变其他公共类型，未采用。临时输入仅在 components 的裸 string/object items 添加显式 false，保留 nullable/ref/composition 与 API 参数。公开 API paths/schemas 保持原生结构。一次本任务适配器删除预处理段导致无输入 spec，已记录失败、修复适配器并完整重新生成；不把此失败计作通过。维护 README 仅从本分支 HEAD 恢复后随规范生成保留，没有复制旧 SDK/权限方案。

R1 同族边界：原厂只读 inline attachment anchor/img 及其缓存保持基线，不带页签名称；本分支保护声明限定带页签标识的业务 API 与适配后的归档入口。已同步 DESIGN/ACCEPTANCE，不宣称全部浏览器资源均受旧页签保护。原有会话/服务配置校验继续生效。

共享 runner、锁和资源限制沿用 HANDOFF；没有操作其他 worktree。原体验服务仍保持用户授权的停止状态，保留容器/数据/配置，恢复属于原会话。主干不合并。

历史验收器失败：c09语法错误，未启动资源；c10使用不存在的operations视图；c11只找document-export行，实际whole-bank导出为export_bank。三次均记录失败/未完成，修正验证器后同制品c12完整通过；c10/c11自有服务/PG均正常退出或停止并保留数据。初审问题不因之前自审PASS而抹除。
