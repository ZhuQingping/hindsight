# ContextDB 管理 API：curl 验证手册

更新：2026-10-16。适用于 release-hardening 分支部署的元数据3实例，API路径v1；原8890/9998旧体验实例未升级。按“初始化→工作空间→成员→Key→清理”覆盖14个管理操作。

[设计](contextdb-release-design.md) · [部署](contextdb-optimized-guide.md) · [OpenAPI](contextdb-control-plane.openapi.yaml)。优化前完整用例已归档，不混用旧服务、旧身份路径和配置摘要认证。

## 1. 准备

先按部署手册启动新实例。在同一 Bash 终端设置实际服务地址和私密目录；远端可用可达IP/域名，不限单机。所有后续写入只针对本手册创建的测试资源。

```bash
bash
set -o pipefail
umask 077
export API='http://127.0.0.1:8888'
# 已完成部署的同版源码和Python环境，原生SDK/MCP示例使用。
: "${CODE:?先按部署手册设置同版CODE路径}"
export PY="$CODE/.venv/bin/python"
export RUN="$HOME/.contextdb/release"
export ADMIN_KEY=$(jq -er '.secret' "$RUN/admin-key.json")
export CASE_DIR=$(mktemp -d /tmp/contextdb-api-demo.XXXXXX)
export DEMO_NAME="api-demo-$(date +%Y%m%d%H%M%S)-$$"
unset ALL_KEY_ID
command -v curl
command -v jq
```

Admin Key 用于管理和所有空间的原生 REST/MCP；UI 密码独立。业务 all Key 也不能调管理接口。新 Key 的明文保存在私密 CASE_DIR，只首次返回，不提交仓库。失败先停止后续步骤核对状态；签 Key 结果未知不自动重试。

## 2. 实例初始化与检查

### 2.1 实例创建：离线部署，没有 HTTP 创建接口

当前没有 `POST /instances` 或实例注册接口。实例由运维/节点 Agent 部署：准备专用 PG 数据库及扩展，生成 Admin Key，写入配置，初始化元数据，再启动 API/Worker；API 就绪后再启动 UI。

当前实例已经完成初始化，不要为执行本手册重新生成它的 Key 或 pepper。

新实例先配置私密目录、PG/模型/扩展，执行同版脚本 init，再启动 api/ui：

```bash
export CONTEXTDB_DEPLOY_DIR="$RUN"
export SERVICE="$CODE/hindsight-extensions/contextdb-service/scripts/service.sh"
"$SERVICE" init
# 在各自监督器/终端前台执行："$SERVICE" api / "$SERVICE" ui
```

init 离线保存秘密并导入 PG 的管理员 HMAC，不依赖运行中的 API；已有实例不要重新生成 pepper。重复初始化保留原秘密。所有详细命令见部署手册。

### 2.2 健康检查

**接口：** `GET /health/ready`。无需鉴权、无参数。确认数据库连接和服务就绪。

```bash
curl -fsS \
  "$API/health/ready" | jq .
```

预期 HTTP `200`，主要字段：

```json
{
  "status": "healthy",
  "database": "connected"
}
```

实际还包含连接池统计，数值会变化。

### 2.3 检查管理员身份（管理操作 1/14）

**接口：** `GET /ext/contextdb/v1/admin/identity`。无业务参数。

```bash
curl -fsS \
  "$API/ext/contextdb/v1/admin/identity" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

新实例返回示例 HTTP `200`：

```json
{
  "user_id": "instance-admin",
  "role": "admin",
  "instance_id": "<实际实例ID>",
  "cloud_tenant_id": "local-cloud-tenant"
}
```

`instance-admin` 是运维身份标识，不是通过用户管理接口创建的成员。

## 3. 工作空间管理

一个工作空间对应一个独立 PG schema；`workspace_id` 同时也是原生 REST/MCP 调用中的 `bank_id`。空间 ID 和 schema 由服务生成，客户端不能指定。

### 3.1 创建工作空间（2/14）

**接口：** `POST /ext/contextdb/v1/workspaces`。

| 参数 | 位置 | 约束 |
| --- | --- | --- |
| `Idempotency-Key` | Header，必填 | 1～128个 ASCII 字母、数字、下划线或连字符；同次操作重试复用 |
| `name` | JSON，必填 | 1～64 字符；服务归一化后校验名称冲突 |
| `description` | JSON，可选 | 最多 512 字符，默认空字符串 |

```bash
curl -fsS -X POST \
  "$API/ext/contextdb/v1/workspaces" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $DEMO_NAME-create" \
  -d "{
    \"name\": \"$DEMO_NAME\",
    \"description\": \"用于手工验证管理接口\"
  }" \
  | tee "$CASE_DIR/workspace-create.json" | jq .

export WORKSPACE_ID=$(jq -er '.workspace_id' "$CASE_DIR/workspace-create.json")
export CREATE_OPERATION_ID=$(jq -er '.operation_id' "$CASE_DIR/workspace-create.json")
```

预期 HTTP `202`，响应结构如下。尖括号内容均为说明，真实 ID 已由上面的命令自动保存。

```json
{
  "operation_id": "<操作ID>",
  "workspace_id": "<工作空间ID>",
  "action": "create_workspace",
  "state": "pending",
  "error_code": null
}
```

`202` 只表示受理，需要继续查询进度；响应 Location 指向 `/ext/contextdb/v1/operations/{operation_id}`。相同幂等 Key 和相同内容复用已有操作；同 Key 不同内容返回409。failed 操作在满足状态条件时可用原 Key 重试执行，不保证永远只返回旧失败结果。GET 查询不会重启任务。

### 3.2 查询操作进度（3/14）

**接口：** `GET /ext/contextdb/v1/operations/{operation_id}`。URL 参数为创建/删除响应中的操作 ID。

```bash
curl -fsS \
  "$API/ext/contextdb/v1/operations/$CREATE_OPERATION_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

预期 HTTP `200`，返回 `operation_id、workspace_id、action、state、error_code`。

| state | 含义 |
| --- | --- |
| `pending` | 等待执行 |
| `running` | 正在执行 |
| `succeeded` | 已完成 |
| `failed` | 失败，检查 error_code |

重复执行直到 `succeeded`，再继续授权。超时未完成时继续查同一个操作，不要换幂等 Key 重复创建。

为避免每次手动查询，可在当前 Bash 中定义函数，并等待本次创建完成：

```bash
wait_operation() {
  local op="$1" state i
  for ((i=0; i<60; i++)); do
    curl -fsS \
      "$API/ext/contextdb/v1/operations/$op" \
      -H "Authorization: Bearer $ADMIN_KEY" \
      -o "$CASE_DIR/operation-$op.json" || return 1
    state=$(jq -er '.state' "$CASE_DIR/operation-$op.json") || return 1
    case "$state" in
      succeeded) jq . "$CASE_DIR/operation-$op.json"; return 0 ;;
      failed) jq . "$CASE_DIR/operation-$op.json"; return 1 ;;
      pending|running) sleep 2 ;;
      *) echo "未知操作状态：$state"; return 1 ;;
    esac
  done
  echo "等待超时：继续 GET 查询原操作 $op，不代表服务端已取消"
  return 1
}
wait_operation "$CREATE_OPERATION_ID"
```

函数只查询，不提交重试。失败或等待超时时停止后续授权步骤，先处理或继续查询原操作。


### 3.3 查询工作空间列表（4/14）

**接口：** `GET /ext/contextdb/v1/workspaces`。

| 查询参数 | 约束 |
| --- | --- |
| `q` | 名称包含匹配，不区分大小写，最多 128 字符，默认空 |
| `limit` | 默认 20，范围 0～100 |
| `offset` | 默认 0，不小于 0 |

```bash
curl -fsS -G \
  "$API/ext/contextdb/v1/workspaces" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  --data-urlencode "q=$DEMO_NAME" \
  --data-urlencode 'limit=20' \
  --data-urlencode 'offset=0' | jq .
```

预期 HTTP `200`：

```json
{
  "items": [
    {
      "workspace_id": "<工作空间ID>",
      "name": "<测试空间名称>",
      "description": "用于手工验证管理接口",
      "state": "active",
      "version": 1,
      "created_at": "<创建时间>",
      "latest_operation_id": "<本次创建操作ID>"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

示例版本号以实际响应为准。列表可能包含处于创建、删除等中间状态的空间，已删除空间不返回。

### 3.4 查询单个工作空间（5/14）

**接口：** `GET /ext/contextdb/v1/workspaces/{workspace_name}`。按规范化唯一名称精确查询；中文、空格等需 URL 编码，不作 UUID 回退。DELETE/业务 bank_id/授权仍用 workspace_id。

```bash
curl -fsS \
  "$API/ext/contextdb/v1/workspaces/$DEMO_NAME" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

预期 HTTP `200`，返回上述单个工作空间对象，创建完成后为 `state: "active"`。

### 3.5 再创建一个空间，用于验证逐空间权限

仍是第2个管理操作的另一组测试数据，不增加新接口。两个空间全部由本手册创建，避免给已有业务空间授予测试 Key。

```bash
curl -fsS -X POST \
  "$API/ext/contextdb/v1/workspaces" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $DEMO_NAME-create-b" \
  -d "{\"name\":\"$DEMO_NAME-b\",\"description\":\"逐空间权限验证\"}" \
  | tee "$CASE_DIR/workspace-b-create.json" | jq .
export WORKSPACE_B_ID=$(jq -er '.workspace_id' "$CASE_DIR/workspace-b-create.json")
export CREATE_B_OPERATION_ID=$(jq -er '.operation_id' "$CASE_DIR/workspace-b-create.json")
wait_operation "$CREATE_B_OPERATION_ID"
```

预期202，操作成功后两个空间都为 active。当前没有工作空间修改接口；两个空间的删除安排在第6.2节。

## 4. 用户管理

用户是业务 Key 的归属主体。创建时只填写名称，不设置角色或空间权限，也不自动生成 Key。停用用户可以统一阻断其所有 Key。

### 4.1 创建用户（6/14）

**接口：** `POST /ext/contextdb/v1/users`。JSON 参数 `name` 必填，1～64 字符。

```bash
curl -fsS -X POST \
  "$API/ext/contextdb/v1/users" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"$DEMO_NAME-user\"}" \
  | tee "$CASE_DIR/user-create.json" | jq .

export USER_ID=$(jq -er '.user_id' "$CASE_DIR/user-create.json")
export USER_VERSION=$(jq -er '.version' "$CASE_DIR/user-create.json")
```

预期 HTTP `201`：

```json
{
  "user_id": "<用户ID>",
  "name": "<测试用户名称>",
  "status": "active",
  "version": 1,
  "created_at": "<创建时间>"
}
```

响应 Header 包含 `ETag: "1"`。当前没有供普通成员选择管理员角色的参数。

### 4.2 查询用户列表（7/14）

**接口：** `GET /ext/contextdb/v1/users`。`q、limit、offset` 的含义和范围与工作空间列表一致。

```bash
curl -fsS -G \
  "$API/ext/contextdb/v1/users" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  --data-urlencode "q=$DEMO_NAME" \
  --data-urlencode 'limit=20' \
  --data-urlencode 'offset=0' | jq .
```

预期 HTTP `200`，返回 `items、total、limit、offset`，每项为用户对象。列表包含 active/disabled 用户，排除已删除用户。当前没有单独的 `GET /users/{user_id}`。

### 4.3 修改名称或状态（8/14）

**接口：** `PATCH /ext/contextdb/v1/users/{user_id}`。

| 参数 | 约束 |
| --- | --- |
| `If-Match` Header | 必填，当前版本，双引号是值的一部分，例如 `"1"` |
| JSON `name` | 可选，1～64 字符 |
| JSON `status` | 可选，`active` 或 `disabled` |

至少提供一个非 null 字段，不能空请求体。下面先只修改名称，保持用户 active，以便后续创建 Key。

```bash
curl -fsS -X PATCH \
  "$API/ext/contextdb/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -H "If-Match: \"$USER_VERSION\"" \
  -d "{\"name\":\"$DEMO_NAME-user-edited\"}" \
  | tee "$CASE_DIR/user-update.json" | jq .

export USER_VERSION=$(jq -er '.version' "$CASE_DIR/user-update.json")
```

预期 HTTP `200`，返回修改后的用户对象，version 更新。版本过期返回 `412`。

可选的停用/恢复测试建议在第 5.1 节创建 Key 后进行，以检查已有 Key 受用户状态影响。停用命令：

```bash
curl -fsS -X PATCH \
  "$API/ext/contextdb/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -H "If-Match: \"$USER_VERSION\"" \
  -d '{"status":"disabled"}' \
  | tee "$CASE_DIR/user-disabled.json" | jq .

export USER_VERSION=$(jq -er '.version' "$CASE_DIR/user-disabled.json")
```

恢复命令：

```bash
curl -fsS -X PATCH \
  "$API/ext/contextdb/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -H "If-Match: \"$USER_VERSION\"" \
  -d '{"status":"active"}' \
  | tee "$CASE_DIR/user-restored.json" | jq .

export USER_VERSION=$(jq -er '.version' "$CASE_DIR/user-restored.json")
```

两次均预期 HTTP `200`。停用阻断全部 Key 的后续认证；恢复只恢复未吊销 Key 的使用资格，不恢复已吊销 Key，不表示撤销已经执行中的请求。

删除用户放在第 6.1 节，避免提前删除导致后面的 Key 管理失败。

## 5. API Key 管理

授权配置在 Key 上，一个用户可以有多个 Key；用户本身不再另配角色和空间权限。业务 Key 不能调用任何管理接口，包括创建/删除空间、用户或其他 Key。

### 5.1 创建业务 Key（9/14）

**接口：** `POST /ext/contextdb/v1/users/{user_id}/keys`。用户必须 active。

| JSON 参数 | 约束 |
| --- | --- |
| name | 必填，1～64字符，不能纯空白 |
| authorization | 必填对象，只能使用下面两种模式之一 |
| authorization.mode | 必填，selected / all |
| selected 的 workspaces | 1～1000项，每项 workspace_id 不重复，且空间为 active |
| 每项 permission | read / read_write；新建时省略默认 read_write |
| all 的 permission | 全部当前及未来空间的统一权限；省略默认 read_write |

selected 不提交统一 permission；all 不提交 workspaces。旧平铺 access_mode、workspace_ids、permission 不再作为公开输入。

下面用同一个 Key 配置：**空间A读写、空间B只读**。创建响应包含明文，只保存到私有文件，终端展示时去掉 secret：

```bash
jq -n --arg name "$DEMO_NAME-key" --arg a "$WORKSPACE_ID" --arg b "$WORKSPACE_B_ID" \
  '{name:$name,authorization:{mode:"selected",workspaces:[
    {workspace_id:$a,permission:"read_write"},
    {workspace_id:$b,permission:"read"}
  ]}}' > "$CASE_DIR/key-input.json"

curl -fsS -X POST \
  "$API/ext/contextdb/v1/users/$USER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary "@$CASE_DIR/key-input.json" \
  -o "$CASE_DIR/key-create.json"
jq 'del(.secret)' "$CASE_DIR/key-create.json"
export KEY_ID=$(jq -er '.key_id' "$CASE_DIR/key-create.json")
export KEY_VERSION=$(jq -er '.version' "$CASE_DIR/key-create.json")
export BUSINESS_KEY=$(jq -er '.secret' "$CASE_DIR/key-create.json")
```

预期 HTTP201，实际响应结构如下；授权数组顺序以实际返回为准：

```json
{
  "key_id": "<Key ID>",
  "user_id": "<用户ID>",
  "name": "<Key名称>",
  "display_key": "ctx_live_***5f82bf",
  "authorization": {
    "mode": "selected",
    "workspaces": [
      {"workspace_id": "<空间A ID>", "workspace_name": "<空间A名称>", "permission": "read_write"},
      {"workspace_id": "<空间B ID>", "workspace_name": "<空间B名称>", "permission": "read"}
    ]
  },
  "version": 1,
  "created_at": "<创建时间>",
  "secret": "<仅本次返回的完整ctx_live_凭据>"
}
```

secret 用于业务认证，key_id 只用于管理定位。以后查询不能找回 secret；普通响应不再返回旧平铺授权、status、revoked_at 或 digest。

**可选：创建全部空间 Key。** 该模式没有逐空间例外，包含未来新建空间。这个 Key 仍没有管理权限。以下会实际签发另一把 Key，末尾一起清理：

```bash
jq -n --arg name "$DEMO_NAME-all" \
  '{name:$name,authorization:{mode:"all",permission:"read_write"}}' \
  > "$CASE_DIR/key-all-input.json"
curl -fsS -X POST \
  "$API/ext/contextdb/v1/users/$USER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary "@$CASE_DIR/key-all-input.json" \
  -o "$CASE_DIR/key-all-create.json"
jq 'del(.secret)' "$CASE_DIR/key-all-create.json"
export ALL_KEY_ID=$(jq -er '.key_id' "$CASE_DIR/key-all-create.json")
```

预期201，authorization 为 all + read_write，不含 workspaces。

### 5.2 查询用户的 Key 列表（10/14）

**接口：** `GET /ext/contextdb/v1/users/{user_id}/keys`。q、limit、offset 同前。

```bash
curl -fsS -G \
  "$API/ext/contextdb/v1/users/$USER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  --data-urlencode "q=$DEMO_NAME" \
  --data-urlencode 'limit=20' --data-urlencode 'offset=0' | jq .
```

预期200，返回 items、total、limit、offset。items 为上述 Key 元数据，不含 secret，并增加近似使用统计 last_used_at。未执行可选 all 创建时 total=1；执行后为2。

- display_key 是真实凭据末6字符的脱敏值；迁移的历史 Key 没有可恢复尾缀时为 null。
- 已吊销 Key 在统计和分页前过滤，普通列表不返回；成员停用不会把未吊销 Key 从目录中移除。
- 不再根据 status/revoked_at 在客户端过滤，也不把“出现在列表”当成成员一定 active。


### 5.2.1 原生业务正向验证（在改权限与清理资源之前）

本节使用刚创建的 BUSINESS_KEY，它对 WORKSPACE_ID 有读写权限。SDK 走原生 REST，bank_id 使用返回的 workspace_id；界面名不替代它。需同版发布 Python SDK、fastmcp，使用模型的 Retain/Reflect 会实际调用模型。

```bash
# 在同版源码环境安装公开SDK；不改变服务端源码。
uv pip install --python "$PY" -e "$CODE/hindsight-clients/python"
"$PY" - <<'PY'
import asyncio, os, time
from hindsight_client import Hindsight
async def main():
 client=Hindsight(base_url=os.environ['API'],api_key=os.environ['BUSINESS_KEY'])
 bank=os.environ['WORKSPACE_ID']
 try:
  accepted=await client.aretain(bank_id=bank,content='嘉木项目负责人是李明，使用PostgreSQL保存记忆。',retain_async=True)
  print('retain accepted:',accepted.operation_id)
  deadline=time.monotonic()+120
  while True:
   page=await client.operations.list_operations(bank,limit=100)
   if not any(op.status in ('pending','processing') for op in page.operations): break
   if time.monotonic()>=deadline: raise TimeoutError('任务仍处理中，请查询原生operations，不重复retain')
   await asyncio.sleep(1)
  print(await client.arecall(bank_id=bank,query='谁负责嘉木项目？'))
  print(await client.areflect(bank_id=bank,query='总结嘉木项目的负责人和存储方案。'))
 finally: await client.aclose()
asyncio.run(main())
PY
```

预期：Retain 返回任务ID；等待终态后 Recall 返回相关记忆，Reflect 返回基于记忆的回答。还应查看任务是否 failed，不能只以 pending/processing 消失作为提取成功。实际文本由模型产生，不要求逐字匹配。

MCP 单空间入口明确绑定同一个不可复用ID：

```bash
"$PY" - <<'PY'
import asyncio, os
from fastmcp import Client
async def main():
 url=os.environ['API'].rstrip('/')+'/mcp/'+os.environ['WORKSPACE_ID']+'/'
 async with Client(url,auth=os.environ['BUSINESS_KEY']) as client:
  print([tool.name for tool in await client.list_tools()])
  print(await client.call_tool('recall',{'query':'谁负责嘉木项目？'}))
asyncio.run(main())
PY
```

多空间 MCP 使用 `/mcp/`，工具参数显式 bank_id；同一个Key只可访问其当前授权空间。工作空间管理、用户与Key管理仍用管理REST/UI，不通过原生create_bank/delete_bank绕过映射。Admin Key可替换相同位置的业务Key访问全部active空间；Bearer/SDK调用方式相同，服务端按PG角色与授权区分。

权限编辑、停用或吊销后再请求应立即按新权限拒绝；不能依赖重建MCP会话才生效。保持旧MCP会话并从另一个管理终端收权的自动用例见 test_110_contextdb_tenant_admin.py、test_113_contextdb_optimized_authorization.py；同名重建与旧Key用例见 test_115_contextdb_workspace_recreation.py。

### 5.3 修改 Key 名称或授权（11/14）

**接口：** `PATCH /ext/contextdb/v1/users/{user_id}/keys/{key_id}`。

If-Match 必填，值带双引号；name / authorization 至少一个非 null 字段。只改名不改变授权；提交 authorization 则完整替换授权，所有 permission 必填，不能省略为默认读写。

先只修改名称：

```bash
curl -fsS -X PATCH \
  "$API/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -H "If-Match: \"$KEY_VERSION\"" \
  -d "{\"name\":\"$DEMO_NAME-key-renamed\"}" \
  | tee "$CASE_DIR/key-renamed.json" | jq .
export KEY_VERSION=$(jq -er '.version' "$CASE_DIR/key-renamed.json")
```

预期200，名称和 version 更新，两空间权限保留；原 BUSINESS_KEY 不变，不返回 secret。

再把空间A改为只读、移除空间B：

```bash
jq -n --arg a "$WORKSPACE_ID" \
  '{authorization:{mode:"selected",workspaces:[{workspace_id:$a,permission:"read"}]}}' \
  > "$CASE_DIR/key-patch-input.json"
curl -fsS -X PATCH \
  "$API/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -H "If-Match: \"$KEY_VERSION\"" \
  --data-binary "@$CASE_DIR/key-patch-input.json" \
  | tee "$CASE_DIR/key-update.json" | jq .
export KEY_VERSION=$(jq -er '.version' "$CASE_DIR/key-update.json")
```

预期200，authorization 只剩空间A且为 read。旧版本返回412；先从列表取得目标 Key 最新 version、确认授权，再修改。已吊销 Key 不能编辑。单纯改名不因历史授权空间失效而失败。

### 5.4 用业务 Key 检查权限边界

以下是原生接口的补充验证，不计入14个管理操作。读取不调用模型，只读写入应在调用模型前被拒绝。

空间A的读取应200；已从授权移除的空间B应403：

```bash
curl -sS \
  "$API/v1/default/banks/$WORKSPACE_ID/memories/list?limit=1" \
  -H "Authorization: Bearer $BUSINESS_KEY" -w '\nHTTP %{http_code}\n'
curl -sS \
  "$API/v1/default/banks/$WORKSPACE_B_ID/memories/list?limit=1" \
  -H "Authorization: Bearer $BUSINESS_KEY" -w '\nHTTP %{http_code}\n'
```

原生读取返回记忆列表，新空空间没有记忆；越权返回拒绝错误，不返回另一空间内容。空间A已被改为只读，下面的 Retain 应403，不产生新记忆：

```bash
curl -sS -X POST \
  "$API/v1/default/banks/$WORKSPACE_ID/memories" \
  -H "Authorization: Bearer $BUSINESS_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"content":"只读写入拦截验证"}],"async":true}' \
  -w '\nHTTP %{http_code}\n'
```

业务 Key 调管理接口应403：

```bash
curl -sS "$API/ext/contextdb/v1/workspaces" \
  -H "Authorization: Bearer $BUSINESS_KEY" -w '\nHTTP %{http_code}\n'
```

也可回到第4.3节停用用户，再执行空间A读取，预期401；恢复用户后读取恢复200。只读支持 Recall、Reflect 和内容读取；读写增加 Retain 等内容写入，但都不包含管理资源。Retain/Recall/Reflect 的模型功能验收另见业务验收文档。

### 5.5 吊销 Key（12/14）

**接口：** `DELETE /ext/contextdb/v1/users/{user_id}/keys/{key_id}`。无请求体，无需 If-Match。

```bash
curl -sS -X DELETE \
  "$API/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -o /dev/null -w 'HTTP %{http_code}\n'
```

预期204，返回体为空，永久吊销；后台保留 revoked_at 和审计，不物理删除。成员尚未删除时重复吊销同一 Key 仍204。

重新执行第5.2节：本 Key 不再出现在 items，total 减1；如未执行可选 all 创建，应 items=[]、total=0。再执行空间A读取，预期401；不承诺取消已受理任务。

如果执行过可选 all 创建，清理那把 Key：

```bash
if [ -n "${ALL_KEY_ID:-}" ]; then
  curl -sS -X DELETE \
    "$API/ext/contextdb/v1/users/$USER_ID/keys/$ALL_KEY_ID" \
    -H "Authorization: Bearer $ADMIN_KEY" \
    -o /dev/null -w 'HTTP %{http_code}\n'
fi
```

## 6. 清理测试资源

只删除本手册生成的 USER_ID、WORKSPACE_ID、WORKSPACE_B_ID。第5.5节已经吊销测试 Key；两个测试空间都需要清理。

### 6.1 删除测试用户（13/14）

**接口：** `DELETE /ext/contextdb/v1/users/{user_id}`。无请求体，无需 If-Match。

```bash
curl -sS -X DELETE \
  "$API/ext/contextdb/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -o /dev/null \
  -w 'HTTP %{http_code}\n'
```

预期 HTTP `204`，无返回体。用户软删除，其全部 Key 无法通过后续认证；空间和记忆数据保留。重新查询用户列表不再展示该用户。

### 6.2 删除测试工作空间（14/14）

**接口：** `DELETE /ext/contextdb/v1/workspaces/{workspace_id}`。必填 Header Idempotency-Key，1～128 字符，无请求体。此操作会清理该空间的数据。

```bash
curl -fsS -X DELETE \
  "$API/ext/contextdb/v1/workspaces/$WORKSPACE_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Idempotency-Key: $DEMO_NAME-delete" \
  | tee "$CASE_DIR/workspace-delete.json" | jq .

export DELETE_OPERATION_ID=$(jq -er '.operation_id' "$CASE_DIR/workspace-delete.json")
wait_operation "$DELETE_OPERATION_ID"
```

预期 HTTP `202`：

```json
{
  "operation_id": "<删除操作ID>",
  "workspace_id": "<工作空间ID>",
  "action": "delete_workspace",
  "state": "pending",
  "error_code": null
}
```

查询删除进度，重复到 succeeded：

```bash
curl -fsS \
  "$API/ext/contextdb/v1/operations/$DELETE_OPERATION_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

确认空间已删除：

```bash
curl -sS \
  "$API/ext/contextdb/v1/workspaces/$DEMO_NAME" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -w '\nHTTP %{http_code}\n'
```

预期 HTTP `404`。如操作仍 pending/running，继续查同一个操作；如 failed，先检查 error_code，不要据 202 判断删除已完成。

第二个测试空间按相同步骤删除：

```bash
curl -fsS -X DELETE \
  "$API/ext/contextdb/v1/workspaces/$WORKSPACE_B_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Idempotency-Key: $DEMO_NAME-delete-b" \
  | tee "$CASE_DIR/workspace-b-delete.json" | jq .
export DELETE_B_OPERATION_ID=$(jq -er '.operation_id' "$CASE_DIR/workspace-b-delete.json")
wait_operation "$DELETE_B_OPERATION_ID"
```

预期202，最后 succeeded。此时 Bank/文件、独立 schema、空间行和对应授权已清理，操作快照及审计仍可追溯。繁忙/未知执行者/外部依赖会阻止成功。默认操作结果保留168小时；相同 Idempotency-Key 在窗口内返回旧操作，过期不保证可重放。

## 7. 返回码、重试与接口边界

| HTTP | 说明 |
| --- | --- |
| 200 | 查询或修改成功 |
| 201 | 用户或 Key 创建成功 |
| 202 | 空间操作受理，需查询进度 |
| 204 | 用户删除或 Key 吊销成功，无响应体 |
| 400 | 参数、幂等 Header 或版本 Header 不合法 |
| 401 | 缺少或无效凭据 |
| 403 | 有效业务 Key 调用了管理员接口 |
| 404 | 目标不存在 |
| 409 | 名称、幂等请求或资源状态冲突 |
| 412 | If-Match 版本过期，需要重新获取当前版本 |
| 503 | 元数据服务不可用 |

错误体统一为：

```json
{
  "code": "<错误标识>",
  "message": "<错误说明>",
  "request_id": "<请求追踪ID>",
  "fields": []
}
```

参数校验错误可附安全 fields 提示，字段只含 field/reason，不回显 secret、原始输入或数据库错误。

管理请求响应包含 X-Request-ID 和 Cache-Control: no-store；用户与Key编辑响应含ETag；空间只读详情不发ETag。If-Match 为带双引号的正整数，最多22位数字；路径 ID 为32位小写十六进制。`curl -fsS` 遇 HTTP 错误会报错；需要查看错误 JSON 和状态码时，将该条改为 `curl -sS -i` 并去掉末尾 jq 管道。

工作空间创建/删除支持幂等重试。用户和 Key 创建当前没有幂等参数；请求超时、结果未知时先查询列表，避免直接重试造成重复创建。若 Key 已创建但明文丢失，列表无法找回 secret，需要吊销后重新签发。

原生 Bank 创建、删除等生命周期接口被限制，管理员也必须使用工作空间接口，以维护空间和 schema 映射。原生 REST/MCP 内容操作另行使用 bank_id=workspace_id 调用。

## 8. PG 只读核对

以下命令使用本机 PG18 客户端连接**当前服务使用的新库**；不是原库。只读核对，不手动修改元数据：

```bash
export PSQL=psql
# PG_URL 从新实例私密配置加载，不能连接旧体验库。
set -a; source "$RUN/api.env"; set +a
export PG_URL="$HINDSIGHT_API_DATABASE_URL"
"$PSQL" "$PG_URL" -X -v ON_ERROR_STOP=1 \
  -c 'SELECT instance_id,cloud_tenant_id,metadata_version,format_id,installed_at FROM ctxdb_meta.deployment_info;' \
  -c "SELECT tablename FROM pg_tables WHERE schemaname='ctxdb_meta' ORDER BY tablename;" \
  -c "SELECT to_regclass('ctxdb_meta.instances') AS old_instances,to_regclass('ctxdb_meta.schema_versions') AS old_versions;"
```

预期 deployment_info 恰好1行、metadata_version=3、format_id=contextdb-first-release；8张管理表；两个旧表返回 NULL。这是数据库结构序号，API 路径仍为 v1。

查看本次 Key 的模式、吊销标记和逐空间权限，不查询 digest：

```bash
"$PSQL" "$PG_URL" -X -v ON_ERROR_STOP=1 -v key_id="$KEY_ID" <<'SQL'
SELECT key_id,user_id,name,access_mode,permission,revoked_at
FROM ctxdb_meta.api_keys WHERE key_id = :'key_id';
SELECT key_id,workspace_id,permission
FROM ctxdb_meta.key_workspace_permissions WHERE key_id = :'key_id';
SQL
```

selected 的 api_keys.permission 为 NULL，权限在关联表；all 的统一权限在 api_keys.permission，关联表无记录。吊销后主表仍有 revoked_at，不代表 Key 仍有效。成员软删除和 Key 吊销保留记录；空间正常删除后物理移除行与授权，仅留独立操作/审计历史。

完整 API 合同见 [OpenAPI](contextdb-control-plane.openapi.yaml)。旧体验目录的 management-api-cases.sh 使用旧请求体，不用于验证本优化版；本手册的 curl 用例替代该旧入口。

## 9. 本次新增边界验证

- 新建同名、大小写等价/全角等价成员：409；停用仍占名，删除后可同名新建，新 user_id 不继承旧 Key。
- 名称 GET：用实际名称查询200，传旧 UUID 名称查404（除非真实名称恰好就是它）；中文路径先 URL 编码。
- selected 授权读包含只读 workspace_name，写入只传 workspace_id/permission，不能原样回传只读名称。
- 删除选定空间会移除对应授权、Key version加1；旧 If-Match 编辑412，刷新后只改名成功，余下权限不变。
- 授权清成空 selected 仍可列出/编辑，但拒绝所有空间；同名新建不继承旧授权。
- Key 列表 last_used_at 为60秒粒度近似值，无列表 ETag；创建/编辑响应不含该统计，保留编辑版本。
- UI 创建/删除中自动 GET 刷新，正常行无“查询进度”；未知写超过24小时不继续重放。
- 系统管理员不在成员列表，已知其内部 ID 也不能用普通用户/Key CRUD 修改或删除。

完整真实进程故事位于代码仓 test_115_contextdb_workspace_recreation.py；同时覆盖内嵌与独立 Worker。模型功能测试使用本地模拟服务，真实 MaaS 质量另验收。
