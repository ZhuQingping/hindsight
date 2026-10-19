# 冲突处理与来源

用户已确认D1，详细边界见[PLAN.md](PLAN.md)。合入目标是本方`b799f721`加同事PR #3净10提交；不是旧hosted分支整体merge。

## 决策落点

| 冲突/语义交点 | 最终处理 |
| --- | --- |
| HTTP title/description、metrics、MCP serverInfo | 保留本方动态`contextdb_name`；合成同事公开错误/日志改动。新`brand.py`提供显示名函数，headers与metric instruments固定。 |
| Worker、API banner、CP health | 运行名称动态；对外健康信息不返回内部backend地址。安装命令和参数名保持固定。 |
| `api-errors.ts`导入冲突 | 首提交的临时关键词过滤与本方`messageLocale`导入合成；后续同事删除过滤照常接收，保留本方locale行为。禁止对客户内容按品牌关键词重写。 |
| OpenAPI/SDK | cherry-pick仅临时合成，最终从整合源码重生成；保留本方non-null array item修复、432旧签名guard。Rust产品名pattern实际编译发现runtime regress缺依赖，显式补依赖与合法/非法名反序列化回归；SDK lock只增一条root dependency。 |
| 旧hosted HANDOFF modify/delete | 三次重放均保持删除；本目录为整合权威。原两边测试报告作为历史输入保留。 |
| 控制台Connect＋客户端发行合同 | 独立完整Workspace `<MCP_ENDPOINT>`，由管理员提供；API Endpoint另列。固定客户端alias `agentstratum`。不从API猜`/mcp`，不返回服务端密钥。 |
| CLI/plugin发行＋UI原生MCP同名 | 名称不能证明ownership。Claude/Codex/Qwen仅更新/移除插件script；其他JSON host共用保留门，保护外部HTTP/stdio配置及凭证。Qwen显式user scope，不碰project登记。 |
| 无效远程配置＋persistent host启动 | 共享factory捕获RemoteConnectionError并disabled、告警；不发请求/不启本地engine。installer和CLI仍严格拒绝错误配置。 |
| CLI nullable PATCH | 原生25项实测发现清空cron被生成Option省略；仅在CLI完整trigger overlay时补显式cron/tags_match null，不改变原生API或全局SDK字段签名。CLI live测试显式选择owned fixture，compile-time binary，退役ui命令明确拒绝。 |
| 原UI会话/旧页签/下载/locale/有界搜索 | 原保护实现保留；真实整合浏览器验收重新执行，原PASS不继承。 |
| 本方多用户/多Key管理/schema隔离 | 继续排除。原生auth extensions与migrations相对固定main无diff；同事engine/worker品牌与错误改动按D2保留。 |

## 10个提交的可追溯重放

所有重放使用`cherry-pick -x`，保留原作者及原SHA，未用整文件ours/theirs。

| 原提交 | 整合重放 | 标题 |
| --- | --- | --- |
| `8af5b82bb1054d9a80e9e0a84dada0bc61ece915` | `15bacfefd1dee0994d899021ec1cb172c266f3ec` | feat(branding): unify agentstratum public interfaces and local tooling |
| `7ba3eec6a0bdca071dbcf3a61a49572553d880b4` | `c3328ee205f36e4d288242946352fdeb69720c10` | feat(clients): enforce remote connections and scope release to client candidates |
| `bd882bf87ed955dc85029ce4b9ab3b950b16747f` | `fd17e73598e8b59a887726061d960c8a21e706fb` | feat(distribution): add pinned CLI installer for OBS/CDN delivery |
| `e4ee469b4b3e4d981a9c7b463cc154e0e0d8ec0c` | `165c15c29d2e63a95bb66cde880a3c1c9699be70` | fix(coding-agents): contain remote configuration failures during plugin startup |
| `1bfb2b4aa2fa0b7e2fbba43d0920b53f50d48173` | `0cb04e1dd25c623edd902b147362b448a4f0f653` | fix(distribution): install and type-check the Coding Agents client package |
| `55273605f23583d9795b59797c7922f0048a2789` | `624e9af5468f3856668c5096f0c0b13acc4c4129` | fix(logging): restore complete operator diagnostics on server stdout |
| `31acacc4a8b664da4b4b48677dbbe1ebdb82ff97` | `210ec23b88c25e701cf359385e025eb2b5453e6a` | fix: classify client errors without filtering customer identifiers |
| `9aecc3469a106666778ec2fc6ccb302f8f0c10d3` | `42f80374fced0e34c0923eb0d0bf068507e861f1` | fix: repair plugin entrypoints, fs connection resolution and hook ownership |
| `c7407c7b7c05a665d5e208f053a29cfa94d065b5` | `ae89d73231b56b4e21366df3c355b3ca57577f15` | fix: preserve client errors and restore internal trace diagnostics |
| `2885dd33b9a7663b3dbb15c8a394ac60390bbf47` | `a5954a0ff3d922fe94205f82422f7a32dddb2edd` | fix(ci): align CLI command and Claude Code test dependencies |

对象级预演日志：主仓`.local/product-brand-ui/runs/integration-preflight-20261019`。本轮执行/失败/资源日志：`runs/integration-20261019`。逐路径内容摘要与来源见[SOURCE-MAP.json](SOURCE-MAP.json)，实际结果以[RESULT.md](RESULT.md)及[VALIDATION.json](VALIDATION.json)为准。
