# 品牌/UI 独立交付结果

状态：`IMPLEMENTATION_COMMITTED / LOCAL_CHECKS_PASS / RUNTIME_GATES_BLOCKED / DRAFT_ONLY`。2026-10-17。**不能标记可合并。**

实现提交：`cbd42fcae66a3c4e50864a0718bbbc97165e47d0`。分支：`product/agentstratum-brand-ui-20261016`；基线及本次复查的远端 main 均为 `f51b165a5165b1042ba0b6408fcffb5bc1a80fdb`。本分支只含本任务提交；没有合并 main，没有修改其他工作区。

已推送至 origin；[Draft PR #5](https://github.com/RSIXDB/hindsight/pull/5)（base=main，保持 draft）。首次推送的证据提交为 `d6edee715`；远端已核对分支与 draft 状态。

## 已完成的实现

- AgentStratum 响应式 UI、原生功能页、图表、指南与 Python/REST/MCP 接入说明；Workspace 仅为原生 bank 的展示术语。
- `contextdb_name` 运行品牌、动态 metadata/图标/图表导出名称、API/OpenAPI 标题和 HTTP MCP 服务名；协议路径、资源身份和 SDK 包名保持。
- 中文/英文产品文案，其他 locale 明确英文回落；语言切换保留 URL 状态。
- 独立单节点 UI 登录、服务端会话撤销、Host/Origin 检查、服务端数据 API 凭证、原生文件下载与取消传播。
- 解除旧多用户/Key、管理服务和 schema 隔离依赖；补齐通用串行 lint、Next 16 ESLint 入口、显式独立数据库测试入口。
- 修复草稿误删当前基线 Gemini 配置的问题，恢复控件及所有语言目录的对应键。

原生 engine、worker、迁移、授权扩展和 integrations 保持基线。没有新增我们自己的用户/Owner/Key 管理、权限合同、恢复账本或 Workspace schema 隔离。Hook 没有可提取品牌补丁，不能将此次 HTTP MCP 命名称为 Hook 改造。

## 实际验证

日志和运行器均位于 `/home/cimon/code/hindsight/.local/product-brand-ui/runs`。正式摘要和日志哈希见 [VALIDATION.json](VALIDATION.json)。

| 检查 | 结果 | 证据文件（相对日志根目录） |
| --- | --- | --- |
| 95 项交接草稿、两个不可变清单 | PASS，逐文件一致 | SESSION-ACK.md；源/草稿清单哈希见 SOURCE-MAP.json 和 HANDOFF.md |
| 独立 npm 安装 | PASS，offline / ignore-scripts | npm-ci.log；对应 resources.json |
| 独立 Python 环境及本分支本地包 | PASS | python-deps.log；对应 resources.json |
| OpenAPI、Python/TS/Go 源码重生成 | PASS（仅生成） | api-generation.log；api-generation/result.json |
| 原有 API 路径和模型 | PASS，逐结构完全一致；仅新增 /product-config、ProductConfig | static-result.json |
| 排除路径、旧管理依赖、两份 env 模板 | PASS 静态 | static-result.json |
| TypeScript SDK build | PASS | sdk-ts-build.log；production-build.log |
| 前端 tsc --noEmit | PASS | frontend-type.log |
| Python 品牌测试 | PASS，11 项 | python-brand.log |
| 前端单测复测 | PASS，55 文件 / 347 项，TZ=UTC | frontend-unit-final.log |
| 全仓必需 lint（含 ruff/ty/ESLint/Prettier） | PASS，串行执行 | lint.log；validation-runner.log |
| Next 16 production build + standalone | PASS，使用 /brand-ui 构建 | production-build.log |
| 原生 API/Worker/PG + 生产 UI | 已实际启动，SDK 创建/列举/retain 和浏览器登录/接入页已走通；不是完整验收 | runtime-c03 至 runtime-c05 的日志/DOM/截图 |
| en / zh-CN / fr 英文回落 | PASS 实际页面范围；菜单切换 query/hash 尚缺成功的真实操作验证 | runtime-c05/guide-dom-*.json、guide-*.png |
| 双品牌同制品、真实 MCP、旧页签/下载/退出全故事、两项 SDK 系统故事 | **NOT_RUN 完整成功故事；恢复脚本已准备** | runtime-c06 未开始；runtime.py / runtime-review.sh |
| 全量死代码扫描 / knip blocking | NOT_RUN：共享锁阻挡；已有 lint 和人工引用检查不能替代 | final-review.sh 未开始 |
| Go / Rust 编译 | NOT_RUN：无工具链；不将生成当编译 | api-generation/result.json |
| Hook 宿主、真实模型、生产部署、产品验收 | NOT_RUN，不在本次已证实范围 | 无对应通过声明 |

首轮前端测试曾有 8 个目录键集失败，已修复后 347 项全部通过。运行验证早期失败保留在日志中：c01 为 Docker 不支持 CPU CFS，未创建容器；c02 为样例 stub 缺显式提取规则；c03/c04/c05 为验证器的标题、同 URL 带 fragment 重载、Radix 指针事件问题。后续验证器已修正，但 c06 尚未取得共享锁，不能把修正后的脚本当成通过证据。

## 当前阻塞与恢复

共享锁：`/home/cimon/code/hindsight/.local/hosted-single-tenant/development/runs/m2-access-ui-delivery/resource-heavy.lock`。

最后核对：PID `1377292` 的 runner 启动另一会话 `serve-experience-c04.py`，其服务状态为 `READY`（2026-10-17T04:48:51Z），启动器等待正常停止信号后才释放锁。我们没有停止、修改或绕过它。c06 经同一个 runner 多次排队仍未开始，停止了本任务自己的等待队列，避免留下无人观察的后台执行。

锁正常释放后，在本 worktree 执行：

```bash
python3 /home/cimon/code/hindsight/.local/product-brand-ui/runs/queue-step.py runtime-c06-runner bash /home/cimon/code/hindsight/.local/product-brand-ui/runs/runtime-review.sh
```

该入口依次运行独立 PG/API/Worker/生产 UI/Chromium、双品牌与 MCP、SDK 系统故事、系统测试 lint、scope 检查、vulture/knip 和自有旧 fixture 清理。它不重跑无关模型基准，也不停止其他服务。失败时保留日志并修复，不得跳过。随后更新本目录验收和审查结果、补交证据提交、推送并更新 draft PR；满足门槛后仍由用户决定是否合并。

运行脚本和未运行入口哈希已登记。若运行已创建 runtime-c06 目录，保留其证据，给 runtime-review.sh 中的运行目录换一个新编号后继续；不要覆盖旧结果。

## 资源和证据边界

所有重型命令只经指定共享 runner；3 GiB、256 pids 和 affinity=0-1 的资源记录在对应 resources.json。内核 CPU quota 不生效，明确记录 false，不声称 1.5 核 quota 已执行。PG 独立设置 512 MiB / 96 pids，以 taskset entrypoint 限定到同样 CPU，c04/c05 中已核验内核 memory.max、pids.max 和 PID 1 affinity。

本任务创建的四个早期 PG fixture 均已停止，API/UI/Chromium 子进程也均已停止，没有自己的活动服务。早期 PG 数据仍在这些明确归属的停止容器/匿名卷中；为遵守锁约束，未绕过 runner 做后续清理。恢复入口只删除其标签/资源清单精确匹配的自有历史 fixture。c06 启动器已改为把 PG 数据 bind mount 到本任务 runs 目录。

生产制品指纹为 `676314aafda48903b6f3ce3632ae1c2632521e1e08bdea094079be43f52d63ab`（服务端和静态文件清单摘要），见 runtime-c05/artifact-manifest.json。当前只实际运行 agentstratum；contextdb 同制品重启尚待完成。未引用其他分支的 PASS。
