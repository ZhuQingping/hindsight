# ContextDB 首发优化版：部署与验证

本版落实用户管理、管理 API 与独享 PG 元数据优化。API 路径仍为 `/ext/contextdb/v1`，只有一个运维 Admin Key。UI 登录密码独立，成员不登录 UI，业务 Key 不管理资源。

全部 14 个接口的参数、返回值和 curl 见 [按场景验证手册](contextdb-optimized-curl-guide.md)。

原始方案保留在 [首发设计](contextdb-first-release-design.md) 和 [原始部署手册](contextdb-first-release-guide.md)。它们的三字段授权格式属于优化前实现；本版使用下述 authorization 合同，不能混用。

## 部署

Python、Node、PG 扩展和 MaaS 设置沿用原始部署手册。英文可用 native 全文；中文按选定后端安装 PGroonga 或支持 jieba 的 pg_search。基础扩展为 vector、pg_trgm、btree_gin；pg_stat_statements 用于观测。PGroonga 的生产恢复与主备仍需单独验收。

首次部署准备新的 UTF8 专用数据库，安装依赖并配置：

```bash
export CODE='/实际的优化版代码根目录'
export PY="$CODE/.venv/bin/python"
export PYTHONPATH="$CODE/hindsight-extensions/contextdb-service:$CODE/hindsight-api-slim"

# DEPLOY 指向按部署手册生成的私有配置目录。
source "$DEPLOY/api.env"
"$PY" -m hindsight_ext_contextdb migrate
```

Admin Key 仍由 `generate-admin-key` 离线生成。不要对现有部署重新生成 pepper，或把 Admin Key 放入公开文档、浏览器、日志。

### 已有首发库升级

优化前首发库使用 schema_versions/instances，内部元数据结构版本为 1；优化版合并为 deployment_info，并使用有序结构版本 2。**这不是 API v2 或第二代产品，公开路径仍为 v1。**

先备份专用数据库并停止该实例的 API、Worker及其他写入者，在相同实例/租户配置下执行上面的 migrate，再启动新版。迁移在事务内预检查和转换，失败不能手动篡改版本号或截断名称来强行通过。原始实验 V1/V2 格式和未知版本不自动兼容。

迁移保留原有 ID、摘要、吊销状态、幂等历史、审计和初始化时间。原 selected 统一权限转为每个空间的同一权限，all 仍是统一权限；历史 Key 没有可恢复尾缀时显示历史标识。原生记忆 schema 与 Alembic 不重建。

生产升级仍需备份与恢复演练。不要在旧进程仍持有连接时执行结构升级；本版自测只操作临时 PG，不代表已升级现有体验实例。

### 元数据结构

完整 DDL 见 [schema.sql](../hindsight_ext_contextdb/schema.sql)。实例/租户只保存在单行部署表，不在各业务表重复：

| 表 | 用途 |
| --- | --- |
| deployment_info | 唯一部署绑定、格式/结构版本、原始安装时间，也承接管理事务锁 |
| workspaces | 工作空间与原生 schema/Bank 映射、状态和删除墓碑 |
| users | 成员归属与启停/删除状态 |
| api_keys | Key 摘要、归属、模式、全部空间统一权限、吊销与使用时间；无明文 |
| key_workspace_permissions | 指定模式的逐空间权限，Key+空间唯一并有外键 |
| management_operations | 空间创建/删除的幂等结果、状态和执行租约 |
| request_admissions | 在途请求/提交的持久屏障；正常结束删除，异常不能按TTL清空 |
| audit_events | 成功管理变更追溯，不是原生业务任务队列 |

受控 ID 为32位小写十六进制，名称最长64字符、外部实例/租户标识最长128。采用 varchar 是为了输入约束，不宣称比相同短 text 值更快。各表和字段有真正的 PG COMMENT；metadata 仅预留非安全扩展，不是权限旁路。管理任务、准入、审计生命周期不同，保留独立表，当前不自动清理终态幂等历史。

## 管理 API

所有操作使用 `Authorization: Bearer <Admin Key>`。路由数量仍为 14：

| 场景 | 接口 |
| --- | --- |
| 检查部署身份 | GET `/admin/session` |
| 工作空间 | POST/GET `/workspaces`，GET/DELETE `/workspaces/{id}` |
| 创建/删除进度 | GET `/operations/{id}` |
| 成员 | POST/GET `/users`，PATCH/DELETE `/users/{id}` |
| Key | POST/GET `/users/{id}/keys`，PATCH/DELETE `/users/{id}/keys/{key_id}` |

列表使用 q、limit、offset，返回 items、total、limit、offset。创建/删除空间提供 1～128 位 ASCII 字母、数字、下划线或连字符组成的 Idempotency-Key，返回 202 后查询操作。PATCH 的 If-Match 是带双引号的正整数资源版本，例如 `"1"`。

### 创建与编辑 Key

指定空间请求体：

```json
{
  "name": "订单应用",
  "authorization": {
    "mode": "selected",
    "workspaces": [
      {"workspace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "permission": "read"},
      {"workspace_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "permission": "read_write"}
    ]
  }
}
```

全部空间请求体：

```json
{
  "name": "实例应用",
  "authorization": {"mode": "all", "permission": "read_write"}
}
```

POST 必须明确范围，新建 permission 默认 read_write；selected 至少一个 active 空间，最多 1000 个、不重复。all 包括未来空间，不接受 workspaces。旧 access_mode/workspace_ids/permission 平铺字段不再是公开输入。

PATCH 可以只提交 `{"name":"新名称"}`。提交 authorization 时则完整替换目标授权，所有 permission 都必须明确，未列出的旧空间被移除。修改名称不触碰授权，也不因旧空间已删除而失败。返回不含 secret，原明文不变；412 后刷新确认，不能自动覆盖。

创建响应额外返回一次 secret。普通列表只有脱敏 display_key 等元信息，不返回明文/摘要；已吊销 Key 从正常列表排除。成员停用影响其全部 Key，恢复不复活已吊销 Key；删除成员保留工作空间数据。

### 可执行 curl 顺序示例

先设置实际 API 地址、Admin Key、一个 active 工作空间 ID；这些变量由部署配置和空间列表提供，不把示例 ID 当作真实空间。

```bash
export API='http://127.0.0.1:8888'
export ADMIN_KEY=$(jq -er '.secret' "$DEPLOY/admin-key.json")
umask 077
export RESULT=$(mktemp -d /tmp/contextdb-optimized-demo.XXXXXX)

curl -fsS "$API/ext/contextdb/v1/workspaces?limit=100&offset=0" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .

# 替换为刚才列表中一个 active 空间的 workspace_id。
export WORKSPACE_ID='替换为实际工作空间ID'

curl -fsS -X POST "$API/ext/contextdb/v1/users" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"验证应用"}' > "$RESULT/user.json"
export USER_ID=$(jq -er '.user_id' "$RESULT/user.json")

jq -nc --arg id "$WORKSPACE_ID" \
  '{name:"验证Key",authorization:{mode:"selected",workspaces:[{workspace_id:$id,permission:"read_write"}]}}' \
  > "$RESULT/key-input.json"
curl -fsS -X POST "$API/ext/contextdb/v1/users/$USER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  --data-binary "@$RESULT/key-input.json" > "$RESULT/key.json"
export KEY_ID=$(jq -er '.key_id' "$RESULT/key.json")
export KEY_VERSION=$(jq -er '.version' "$RESULT/key.json")

curl -fsS -X PATCH "$API/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -H "If-Match: \"$KEY_VERSION\"" -d '{"name":"验证Key改名"}' | jq .

curl -fsS "$API/ext/contextdb/v1/users/$USER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .

# 以下仅清理本示例生成的 Key 和成员，不删除工作空间。
curl -sS -X DELETE "$API/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -o /dev/null -w 'HTTP %{http_code}\n'
curl -sS -X DELETE "$API/ext/contextdb/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -o /dev/null -w 'HTTP %{http_code}\n'
```

## UI 和异常处理

用户管理是实例级目录。成员行展开 Key，创建成员只填名称；创建 Key 默认指定空间、默认读写。编辑回填已有权限，指定模式逐空间设置；全部模式明确包含未来空间。吊销成功移除该行，成员停用单独提示。

管理空间目录包含创建中、删除中和失败状态；内容切换只选 active。页面只持久保存非敏感操作意图，刷新只恢复 GET 查询。初始响应丢失且没有操作 ID 时显示结果未知，管理员明确继续才重放原请求，可能重新执行已失败操作。轮询超时不取消服务端任务。

创建成员和签 Key 没有透明重试；超时先核对列表，不按模糊名称自动吊销，不持久保存明文以求恢复。

## 业务调用与安全边界

工作空间 ID 等于 Bank ID。业务保持原生 REST/MCP 请求方式，按目标空间执行只读/读写授权；MCP 工具列表出现 Retain 不代表所有空间都可写。成员或 Key 权限变化对后续检查生效，不承诺强制取消在途任务。

运维独占工作空间生命周期、成员/Key 管理、配置写入、Webhook管理、归档及管理审计。业务 Key 不得读取原始任务载荷；Webhook 任务中的响应/错误诊断也不能带出凭据。普通业务任务状态继续可读。原生 Bank 生命周期仍禁止绕过空间映射，包括使用 Admin Key。

HTTPS、入口限流、大小/超时限制由既有网关负责；应用保留会话同源检查和逐请求权限校验。真实 PG 超级用户/OS root 无法靠同库 ACL 隔离。
