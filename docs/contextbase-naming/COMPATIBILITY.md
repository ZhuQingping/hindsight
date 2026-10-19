# 兼容与部署说明

产品展示名为 ContextBase。CLI 命令仍为 `agentstratum`；Coding Agents 包/命令仍为 `agentstratum-coding-agents`；配置目录仍为 `~/.agentstratum`。这是本轮明确的兼容发行策略，新 `contextbase` 命令、目录或环境变量 alias 未引入。

## 配置与版本组合

| 组合 | 实际合同 |
|---|---|
| 新 API + 新 UI，无命名环境变量 | 默认展示 ContextBase，部署slug为contextbase；v2交叉核对 |
| 新 API + 新 UI，只有旧contextdb_name | 原小写值继续作为展示；UI请求v1；新API附展示头供一致性核对 |
| 新 API + 新 UI，同时设置product_display_name | 大小写展示与旧slug分离；新UI要求v2，两字段都一致 |
| 新 UI + 旧 API | 仅legacy-only配置使用v1；显式独立展示模式要求v2，不静默降级 |
| 旧 UI + 新 API | legacy-only配置可继续使用原两键v1；启用独立展示需同步升级UI。旧UI不理解v2及新增展示头，不能将其当作混合版本展示一致性保证 |

已有部署可以保留原 `contextdb_name` 并在 API/UI 两端同时设置 `product_display_name=ContextBase`，同步重启。这样旧slug及其telemetry service.name行为保留。显示值不改写endpoint、bank、Workspace、配置文件或凭证。

新部署默认telemetry resource service.name仍为agentstratum-api/worker；显式旧slug延续既有service.name行为；显示覆盖不会切分监控历史。UI `/api/health.service` 则是展示字段，仍可显示ContextBase-control-plane。instrument名、webhook/reranker头和日志协议标识维持原值。

`/product-config` 的v1响应体及ProductConfig公共模型保持原合同。`/product-config/v2` 为新增接口；v1额外响应头只包含非秘密展示名。严格键集、slug校验、非法/未知版本拒绝均保留。大小写展示名不允许控制字符和首尾空白，不能被当成任意HTML或协议头注入。

## 客户端与数据

CLI的Profiles、环境变量和配置优先级保持现有实现；更换endpoint仍隔离凭证。插件远程连接、无默认本地引擎、坏配置诊断、外部同名HTTP/stdio MCP ownership及旧自有脚本幂等升级均沿用已整合源与本轮回归。

未执行主机配置迁移，不删除用户文件。安装/重装/卸载测试使用私有fixture；真实第三方宿主会话仍NOT_RUN。

MCP serverInfo的显示与mcpServers注册键/工具名独立。后者保持agentstratum及原工具名。API路径、bank_id、SDK技术包名继续使用原合同。包含agentstratum/contextbase/hindsight的客户文本、ID和归档不经过品牌替换；历史归因识别只读，不重写transcript。

许可证、作者、历史报告和AMB测量主体不改名。四类客户端当前版本号仅表示本地候选，未公开发布或覆盖既有公开版本。未来若改CLI/package/协议身份，需单独定义迁移/alias/冲突合同；当前生成器会拒绝身份消费者偏离已记录映射。
