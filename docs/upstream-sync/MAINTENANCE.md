# 上游同步维护合同

权威：当前主线源码、`brand/definition.json`、`brand/identity-contract.json`、
`docs/contextbase-naming/NAMING-MAP.md`。本文件组织同步检查，不替代这些合同。

## 工作流

明确目标发布标签及 peeled SHA，记录我方 SHA、共同祖先、工作区状态。
从最新目标主线建立独立集成 worktree；原工作区未提交内容保持原状。
正常 merge 上游并保留祖先关系，最终 PR 不 squash。未合入主线的 hosted
多用户、多 Key、schema 隔离工作不因同步而进入本轮。

skill 源码位于 `.agents/skills/hindsight-upstream-sync/`，明确调用
`$hindsight-upstream-sync`。可将此目录链接到个人 Codex skills 目录；链接目标应是
保留的 checkout，删除 worktree 前需迁移链接。预检入口为
`python3 scripts/upstream-sync/preflight.py --ours <SHA> --theirs <SHA>`。

## 同事如何使用

skill、调用策略、预检脚本与测试均纳入 Git；个人机器上的安装链接仅用于本机发现。
当前入口随 [PR #10](https://github.com/RSIXDB/hindsight/pull/10) 交付：合入前获取
`integrate/upstream-v1.0.0` 分支，合入后更新 main 即可获得这些文件。已有工作区
存在未提交改动时，使用独立 checkout/worktree 获取分支，保留原工作。

在对应 checkout 中明确调用，例如：

```text
$hindsight-upstream-sync 请只评估官方 <目标发布标签> 与 origin/main 的差异和冲突，暂不合并。
```

需要执行时，把请求改为“按维护合同集成官方 <目标发布标签>，解决冲突、验证并交付
draft PR，主线合入由我检查”。每次都应写明真实目标标签和接收分支，不能沿用旧报告的 SHA。

如果使用的 agent 没有发现该 skill，可以明确指定仓库文件：

```text
请读取 .agents/skills/hindsight-upstream-sync/SKILL.md，按其中流程评估官方 <目标发布标签>。
```

跨机器使用的流程入口来自当前 checkout 中的 skill、维护合同及脚本，不依赖原作者的个人
skills 目录或历史 `.local` 日志。下文绝对路径属于原执行机器的资源策略：同事应
先检查自己机器的仓库规则、工具链和资源约束，再选择当地 runner 或串行验证方式。
当前机器仍须复用现有共享 runner；不要因换了会话而绕开它。旧日志缺失时按本轮
源码重新验证，不能从文档中的旧 PASS 推断新环境也通过。

维护入口及调用策略在 `.agents/skills/hindsight-upstream-sync/`；行为脚本及测试在
`scripts/upstream-sync/`。修改后随仓库提交并审查，避免同事各自维护互不一致的副本。

## 我方差异登记与验收矩阵

| 差异/目的 | 权威位置 | 必须保留的行为与检查 | 可撤销条件 |
|---|---|---|---|
| 展示名与机器身份分离 | brand/；api product_config；CP product config | ContextBase 展示；命令、包、目录、headers、工具身份保持合同；brand generation/check 与命名黑盒故事 | 明确的身份迁移方案或等价上游扩展点 |
| 旧接口兼容 | product-config v1/v2；SDK wrappers | v1 签名/语义、additive v2、旧客户端；SDK compatibility 检查 | 有版本化退役方案 |
| 远程客户端模式 | coding-agents/core/connection、host-client；CLI config | 不因坏配置启动本地引擎；插件失败不拖垮宿主；connection/host-client/installer 测试 | 上游提供等价模式并实测 |
| 插件配置所有权 | coding-agents installer/MCP 配置 | 不覆盖外部 HTTP/stdio 配置或凭证；ownership 测试 | 上游等价所有权模型 |
| 客户内容与诊断 | API public errors；CLI errors；logs | 不按品牌词替换客户 ID/内容；保留内部诊断、保护公开错误；错误分类测试 | 上游行为等价且回归通过 |
| SDK 生成修正 | prepare-client-spec.py；generate-clients.sh；Rust build.rs | 非空数组元素、兼容签名、forward-compatible decoding；生成一致性及各语言构建 | 上游生成器已覆盖且生成差异审查通过 |
| UI 使用体验 | CP navigation/locale/Connect | 语言切换、URL fragments、Workspace、明确 MCP endpoint；单元与浏览器流程 | 产品决策确认替换 |
| 客户端发行 | installer、plugin packaging、release workflows | 保留固定身份和下载源、远程连接合同；安装包和命令验收 | 单独发行迁移获确认 |

每次集成同时检查上游新增行为，特别是错误码、重试、配置优先级、后台任务、
SDK 解码、跨平台启动和迁移。无文本冲突不免除语义检查。已被上游替代的补丁
应在有测试证明后移除，避免重复维护。

## 生成、资源与证据

先合并源、模板、配置和生成器，再生成品牌/OpenAPI/SDK/文档；对照当前
`verify-generated-files` 工作流，包含 bank-template-schema 和 docs-skill 的生成，
最后运行 lint 并检查再生成不产生差异。lock 由对应包管理器
从合成后的 manifests 生成。避免手工长期维护生成结果。

此机器现有重型 runner：
`/home/cimon/code/hindsight/.local/hosted-single-tenant/development/runs/m2-access-ui-delivery/run-bounded.py`。
复用其 `resource-heavy.lock`，不另设锁、不删除锁、不绕开资源拒绝；在其他机器先
发现当地适用资源策略。参数必须指定本轮 worktree 和主仓本轮日志目录。
PG、端口、容器、浏览器资料目录属于本轮，不能复用其他会话的固定 fixture。
若测试假设临时目录不属于 Git 仓库，直接把 TMPDIR 放进主仓 `.local` 会改变
其语义。此机器可用 bwrap 将本轮临时目录映射为隔离 `/tmp`：数据仍归本轮所有，
测试看到的父目录不再包含仓库。不要为这种夹具问题修改产品的仓库识别逻辑。

每轮在 `docs/upstream-sync/<release>/` 保留 PLAN、冲突决策、验证结果与最终状态。
大日志/运行数据放主仓 `.local/upstream-sync/<run>/`。每项结果明确 PASS/FAIL/NOT_RUN、
命令和源码绑定；历史报告仅供定位，不继承 PASS。数据库变更另验升级与恢复，
不把 git revert 当成数据库回滚。目标主线推进后重新分析受影响证据。

完成条件：无未解冲突、相关检查通过、审查问题已处理、输入和最终提交可追溯、
PR 可审查。主线合入、部署及外部发布不属于默认完成动作。
