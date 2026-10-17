# AgentStratum 品牌与 UI 独立交付

当前为 draft：实现已提交、unit/type/lint/build 已通过；原生全故事和 knip 仍受共享资源锁阻挡。验收边界与恢复命令见 [RESULT.md](RESULT.md)。

本分支从 `origin/main` 提取 AgentStratum 产品界面，并提供同一制品通过运行配置改变产品名称的能力。原生 API、记忆引擎、数据库、授权扩展和客户端协议继续使用主干实现。

实施边界见 [PLAN.md](PLAN.md)。来源与逐文件处理记录见 `SOURCE-MAP.json`；最终验证与审查见 `RESULT.md`。

## 包含的产品能力

- 响应式分组导航、工作空间选择、图表/图谱、原生文档/记忆/实体/Recall/Reflect/知识页/配置与操作页面。
- 使用指南、Python/REST/MCP 接入页；API 凭证由部署管理员提供。
- `contextdb_name` 控制 UI 名称、页面标题、图表导出名称、API/OpenAPI 服务标题和 HTTP MCP `serverInfo.name`。
- 中文和英文产品文案；其他已有语言选项明确回落到英文。切换语言保留当前查询参数和锚点。
- 独立 UI 登录保护、服务端会话撤销、可信 Origin/Host、原生文件下载和传输修复。

工作空间（Workspace）在 UI 中对应原生 API 的 bank。`bank_id`、`/v1/default/banks/...`、`/mcp/`、`/mcp/{bank_id}/`、MCP 工具名及 SDK 包名保持原生协议，不随产品名变化。

本分支不提供用户/Owner 管理、签发或撤销 API Key、授权策略编辑、管理 BFF、恢复账本或 per-Workspace 存储隔离。后续接入同事的权限方案应另行适配这些边界。

## 运行配置

API 与 UI 进程设置相同配置；修改后重启，无需按品牌重新构建：

```dotenv
contextdb_name=agentstratum
```

值为 1–40 个 ASCII 字符：以小写字母开头，后续仅小写字母、数字、连字符。不自动去空白或转换大小写；非法值拒绝启动。配置键固定为小写 `contextdb_name`，不是 `NEXT_PUBLIC_*`。

UI 只检查 `HINDSIGHT_CP_DATAPLANE_API_URL` 所指向的原生 API 的 `/product-config`，不要求独立管理服务。该端点仅返回配置版本和产品名，不返回凭证。旧页面在产品名变更后保留当前输入并提示手动刷新；带旧品牌的新数据请求返回 409，API/界面品牌不一致或 API 不可用时返回 503，不自动重试写入。

UI 的受保护模式是默认值，至少需要：

```dotenv
HINDSIGHT_CP_AUTH_MODE=local
HINDSIGHT_CP_ACCESS_KEY=<独立的界面访问密码>
HINDSIGHT_CP_PUBLIC_ORIGIN=https://memory.example.com
HINDSIGHT_CP_SESSION_DIR=/var/lib/agentstratum/ui-sessions
HINDSIGHT_CP_DATAPLANE_API_URL=http://127.0.0.1:8888
HINDSIGHT_CP_DATAPLANE_API_KEY=<原生数据API凭证>
```

会话目录应由 UI 进程独占且持久化；退出会删除会话记录。UI 访问密码与数据 API Key 是不同凭证。反向代理保留配置的公共 Host；只在明确无保护的本机开发场景设置 `HINDSIGHT_CP_AUTH_MODE=bootstrap`。这套单节点 UI 保护不等同多用户账户或平台 SSO。

API 的鉴权沿用主干配置。例如原生 `ApiKeyTenantExtension` 可验证一个部署共享 Key；本分支没有修改其语义，也没有增加 Key 管理。

稳定的会话 Cookie 名称仍绑定公共 origin/base path，不随展示名称更换；品牌变化不迁移资源 ID、授权或数据库。

## Hook 与客户端边界

已检查来源分支和工作区，`hindsight-integrations/` 没有相对主干的产品改动可提取。原生 Hook 集成与 SDK 包/CLI 发行名保留。不能将 HTTP MCP 服务名、接入页 MCP 连接名或 `scripts/hooks/lint.sh` 的开发检查改动称为 Agent Hook 品牌改造。

## 验证入口

前端测试使用 `npm test --workspace=@vectorize-io/hindsight-control-plane`；构建使用 `npm run build --workspace=@vectorize-io/hindsight-control-plane`。API 命名回归在 `hindsight-api-slim/tests/test_product_config.py`，原生 SDK 黑盒故事在 `hindsight-system-tests/tests/test_98_product_naming.py`，沿用系统测试包的运行方式。

最终结果只登记本次拆分候选实际执行的检查。来源分支的旧 PASS 不作为本分支通过证明。
