# 本地验证与预览操作

源码分支`integration/agentstratum-brand-ui-clients-20261019`，独立worktree为主仓`.local/product-brand-ui/integration-worktree`。原`product/agentstratum-brand-ui-20261016`与PR #5保持，不改其他worktree或其未提交内容。

所有依赖、Go/Rust/Node工具链、caches、PG数据与详细日志都在主仓`.local/product-brand-ui/runs/integration-20261019`。不修改系统profile或系统工具版本。API/PG/client/Chrome各phase的frozen harness、resource.json与cleanup记录位于对应run目录。

重型工作必须排队到唯一`run-bounded.py`及其`resource-heavy.lock`；使用本轮`enqueue-bounded.py`只是等待同一runner空闲，不提供第二套锁/资源策略。原helper名`queue.py`曾遮蔽Python stdlib，已改名，旧失败留存。验证或构建前先正常停止本session预览，再运行重型检查；不要停其他任务或删锁。

## 整合预览

预定固定端口：API28920、UI28921、owned PG28922，只绑定loopback。当前运行结果以本地`preview-01/result.json`为准。

- Workspace列表：`http://127.0.0.1:28921/brand-ui/zh-CN/dashboard`
- 示例概览：`http://127.0.0.1:28921/brand-ui/zh-CN/banks/agentstratum-demo?view=home`
- 三个示例Workspace、五个文档、十三个事实，均为隔离合成数据；provider仅本地显式stub。
- 使用与原生runtime04相同的production artifact，启动后实际浏览器截图复核；release CLI再对该owned API作读列表smoke。
- 最长运行2小时，或在其结果中明确列出的本session STOP路径写入文件正常停止。supervisor会依次结束本session子进程并停止owned PG；数据、配置、容器和日志保留。

之前其他session的28910/28911体验由用户明确授权停止，数据和容器保留，其恢复由原session负责；本session不恢复或重建它。原本方旧预览`preview-20261019-02`也已正常停止，数据与配置保留。本轮使用新的隔离预览数据，不覆盖旧目录。

## 重跑与证据

[VALIDATION.json](VALIDATION.json)给出日志路径与内容摘要；[RESULT.md](RESULT.md)区分当前执行、历史失败和未执行项。运行脚本只在本地runs保留，命令/脚本hash与当前源、冻结输入、资源边界均可追溯，不将本地依赖/日志/密钥提交Git。

普通`cargo test`的25个live用例明确计ignored；需要显式owned API fixture并传`--ignored --test-threads=1`才执行。原生runtime04实际执行25项、零ignored。当前远端CI只运行普通Cargo及后续smoke，不能声称自动执行这些live25。
