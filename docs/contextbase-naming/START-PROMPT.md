# 可复制的新session启动任务

请在新session提交以下完整任务。先从本材料所在工作区读取交接，再按交接建立自己的下一阶段工作区；本材料session不会替你启动实施。

```text
任务：完成ContextBase产品命名解耦与改名任务，复用已整合功能，按目标和验收合同交付。

先读取：
/home/cimon/code/hindsight/.local/product-brand-ui/integration-worktree/docs/contextbase-naming/HANDOFF.md
以及同目录GOALS-AND-ACCEPTANCE.md、STATUS.json。

必须继承双方已整合成果，基点530a630641c7fe5ab274e510e5551eb24e99378b，源码检查点5d350568ae3d7537e452999cb6d0fae86b64563b；交接材料的docs-only提交在该分支之后。先核对实时HEAD/dirty/祖先关系，不从main或旧brand分支漏掉同事成果。建议按HANDOFF另建自己的ContextBase工作区/分支，不修改其他工作区及未提交内容。

产品展示名确定为ContextBase。核心目标是补齐展示名、技术标识、发行/协议身份的解耦，使下一次改名只需修改明确的品牌定义并运行确定流程，不能逐页、逐插件、逐安装脚本重写业务。contextbase是技术标识建议；CLI/包/目录/env/协议具体新旧映射尚未逐项确认，不要把旧建议当用户已经接受的破坏性迁移。先落盘盘点与明确兼容映射，继续已明确范围；超出授权的外部不兼容项以具体差异澄清，不再次询问是否启动整个任务。

先核验输入并写SESSION-ACK，然后持续完成真实入口盘点、命名映射、最小实现、二次改名演练、相关unit/type/lint/build/knip、接口生成兼容、独立原生API/MCP/浏览器/客户端与打包验证、独立终审和结果文件；不要只停在方案或ACK。

保留会话/旧页签/下载/分页搜索/locale、错误诊断、远程连接、MCP所有权、Rust依赖及nullable PATCH修复。多用户、多Key管理、Workspace schema隔离继续排除；不全局替换客户内容、ID、许可证或历史记录，不合并main或公开发行。

所有重型任务复用HANDOFF指定唯一run-bounded.py/resource-heavy.lock，日志集中在主仓.local/product-brand-ui/runs的新任务目录，核验实际cwd与所有权。当前preview可能仍持锁，先核验/协调或等lease，不能抢停或绕过。单持久实施session，不主动派生额外实施agent；独立审查按可用且已授权通道执行，自审不能冒充独立审查。

既有PASS是回归基线，不能当ContextBase已通过。逐项执行N01–N12，持续记录PROGRESS，交付RESULT/VALIDATION/兼容与来源清单、可复核提交和适当draft PR，真实跳过/失败/未运行如实保留。
```
