# 集成源码与验证审查

依据当前 `CLAUDE.md` 和 `.claude/skills/code-review/SKILL.md`，由本实施会话执行。
这不是独立第三方复审。比较基线是固定 `origin/main / 4f7a2781`，不是落后 32 个
提交且带有用户改动的本地 main。上游输入固定到 `39c65ffe`，未使用移动的 upstream/main。

## 已处理的主要发现

| 发现 | 处理与证据 |
|---|---|
| HTTP 错误冲突可能丢掉上游 503 或我方错误边界 | 合成两种行为；store-unavailable、customer-error、internal-error 及相关 API 回归通过 |
| 上游 flush/usage 调整与我方 remote-only 分支交叉 | 保留 optional client 与 in-flight 跟踪，远程校验替代 daemon 启动；完整 Coding Agents 测试和实际 MCP 连接通过 |
| Windows shell spawn 的固定包名假设不适用于我方配置值 | registry-name 校验；无 lookup/spawn 的反例测试通过；真实 Windows 执行未验证 |
| 新增 User-Agent 把我方流量标为官方集成 | 从实际包名与版本派生；真实本地 HTTP 请求断言通过 |
| 生成结果与模板/源文档可能不同步 | 在品牌模板接收上游文档变化，重新生成；SDK 重复生成零差异，docs-skill 重复生成零差异，品牌 roundtrip 恢复原值 |
| CI lockfile 检查误判我方私有开发 helper | 仅允许固定 private 包的固定 dev-only 链接；公开/运行/非 dev 反例拒绝；15 个锁文件检查通过 |
| 新增上游测试使用原始品牌默认值 | 仅适配夹具的既有身份与远程 endpoint，不修改产品行为来迎合错误夹具 |

## 审查结论与范围

- 20 个文本冲突已解决；自动合并交点也已检查。重点覆盖 API/provider 错误与 tracing、
  retain JSON-array append、客户端生成/解码、Coding Agents 生命周期、发行身份及新维护工具。
- 保留我方 brand/identity-contract 和原生 SDK/API/bank_id 合同；未整体导入 hosted 分支。
- API 变化没有增加 handler SQL、advisory lock、BaseHTTPMiddleware 或同步外部网络调用。
  request_context/租户鉴权路径没有被冲突处理绕开。Alembic/backup 表覆盖本轮没有增量。
- 新维护预检使用 dataclass 返回结果；真实 Git 夹具证明不改变 refs/index/worktree。
  已运行 lint、类型检查、knip 与 Rust format；未发现需阻止本轮代码交付的未处理实现问题。
- 新上游 provider 失败/trace 分支有相关回归；prompt/模型效果不由这些确定性测试证明。
  SDK 的旧签名、non-null array、Rust enum、Go 未知字段兼容回归保留并通过。
- 原样上游变化按差异、关联机制与相关测试核对；没有执行所有第三方框架的真实宿主验收。
  实际执行的包和未执行范围详见 VALIDATION.json，不能把它解释为整个 monorepo 全量通过。
- 完整文档站编译未在本机限定预算内完成，GitHub Actions 当前禁用；这两项保留为
  **未验证**，没有通过调整资源上限、禁用检查或虚构结果使报告变绿。

本轮应用/客户端验收结束后，已核对实际源码与最终检查的代码 manifest 一致，
浏览器对应同一生产 UI artifact。后续仅更新交付文档不会继承到不同的产品源码。
所有本轮 API、UI、浏览器和 PG 已停止，原主工作区修改保持原状。

结论：**可交付 draft PR 供用户检查；非生产部署批准，非全平台/全站/真实模型验收。**
