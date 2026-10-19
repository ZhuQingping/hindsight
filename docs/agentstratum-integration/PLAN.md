# AgentStratum UI 与同事客户端/品牌提交整合

状态：IMPLEMENTATION_AUTHORIZED / IN_PROGRESS，2026-10-19。用户要求双方成果放入同一分支并解决冲突，已确认 D1：“保留动态显示名，发行与协议标识固定 agentstratum”。直接实施，不再请求启动确认。

## 固定输入与交付

- 本方独立候选：b799f721f58e44b27a59cbabff6e8e1f32f030a6；源码14c2d60ea；已有验收只属于该候选，不能继承为整合PASS。
- 同事 PR #3：https://github.com/RSIXDB/hindsight/pull/3 。实际提交起点fd69ec9bf50ce97867ff35ee40eb2e71b356586d，终点2885dd33b9a7663b3dbb15c8a394ac60390bbf47，10个提交，净405路径。不是以74b522作为PR净改动起点。
- 远端旧分支merge 3febaf8ac354268e7be35dfd666fc6c7e93f2620；其第一父分支相对main另有33个提交，不能整体merge旧hosted历史。
- 新分支：integration/agentstratum-brand-ui-clients-20261019；新建独立worktree：/home/cimon/code/hindsight/.local/product-brand-ui/integration-worktree。原brand-ui worktree/PR #5保持。
- 同一持久session实施，不额外派生agent；所有重型安装/构建/测试复用唯一run-bounded.py/shared lock。

## 已决策与冲突策略

| 事项 | 决策/处理 |
| --- | --- |
| D1 品牌权威（USER_AGREED） | UI、API/OpenAPI、MCP serverInfo和运行服务显示名由contextdb_name控制；CLI/包/插件/配置目录/协议标识固定agentstratum。不用部署名动态重命名安装产物或协议头。 |
| D2 已有边界 | 本方多用户、多API Key管理、Workspace schema隔离仍排除。允许同事PR明确列出的品牌、客户端、日志/错误边界对engine/worker的必要改动；不再声称整合分支engine逐字等于main。 |
| D3 客户端发行 | 保留同事后续CLIENT-DISTRIBUTION合同：四类客户端候选、远程显式连接、CLI Profile/插件单默认连接；保留服务端源码与本地开发预览。不恢复客户自动启动本地引擎；不发布云资源，不编造CDN域名。较早ISSUE-2文档的相反行为标注被后续合同覆盖。 |
| D4 API与错误 | 保留native bank_id/API路径/SDK包名/工具职责。保留同事的明确客户错误与状态、内部错误通用提示、运营日志完整诊断；不按品牌关键词替换客户数据/文件流。 |
| D5 UI与会话 | 保留本方动态品牌/旧页签、会话撤销、可信Origin/Host、下载productFetch、语言query/hash、分页搜索、特殊bank ID及Gemini修复。自动merge也要复核。 |
| D6 生成物 | 源码合同合定后重生成OpenAPI/Python/TS/Go，保留非空items生成修复与432签名兼容guard；不以ours/theirs整体覆盖SDK或手拼规范作为最终产物。 |
| D7 历史与证据 | 原成果/失败记录按历史候选保留；新整合结果独立登记。旧hosted HANDOFF不恢复为当前权威，新增客户端发行文档作为来源保留。 |

## 已执行预演

仅Git对象级预演，无index/ref/源码修改；生成对象在主仓runs/integration-preflight-20261019/objects，0.309秒。按PR净改动应用到本方：10个路径与本方改动重叠，4个Git冲突：

1. api/http.py：metrics service、API title/description两处；按D1保留动态运行名称，同时接收同事其余错误/日志修改。
2. api/mcp.py：FastMCP名称一处；保留动态名称，同事其他边界修复照常接收。
3. hindsight-docs/static/openapi.json：标题一处；只临时解决cherry-pick，最终从整合API重生成。
4. docs/hosted-single-tenant/module-delivery/M2/HANDOFF.md：modify/delete；保持旧权威文档删除，用本目录记录整合与来源。

自动合并仍有语义冲突：新增brand.py固定服务名、health响应、worker/监控命名、AGENTSTRATUM公开配置与UI连接示例、客户端发行与服务端开发边界、公开错误/状态、测试合同及CI条件。不会使用全局-X ours/theirs。

预演的本地TS相对/alias导入未发现缺失；净候选未出现排除的hosted runtime/manager/access路径；test-dev的Python/Go兼容guard触发仍保留。上述静态检查不等同type/build/runtime。

## 执行顺序与门槛

1. 固定本计划/预演，按顺序cherry-pick -x同事10提交，逐处解决冲突并记录来源；后续修复提交保留两边作者与可追踪性。
2. 按D1统一运行身份/发行标识，修复无Git标记的合同漂移；补双品牌/错误/连接/插件回归，审核旧分支边界与客户内容不被替换。
3. 新环境独立安装依赖。预览在共享锁内运行；到重型验证前正常停止本session自有预览，保留全部数据配置；最终恢复可查看的整合预览。其他体验资源不动。
4. 重生成spec/SDK；全前端unit/type/lint/production build、432旧SDK API兼容、Go/Python客户端/CLI与Coding Agents/Claude Code相关测试、打包/安装故事、knip。
5. 完整原生API/MCP/浏览器：双名称同制品、真实UI与native读写/归档/权限会话/错误边界；真实客户端对显式endpoint连接。Go/Rust工具链目前PATH未发现，实施时先解决隔离工具链准备，不把生成当编译或移植同事旧PASS。
6. 最终审查、准确RESULT/VALIDATION/来源清单、提交可复核整合分支；不合并main，不公开发布，不将未知/未运行写PASS。

预演原始证据：主仓.local/product-brand-ui/runs/integration-preflight-20261019/summary.json与net-pr3-merge-tree.txt。
