# 优化版管理 API：按场景验证

适用于 authorization 对象合同，API 仍为 v1。当前旧体验实例若尚未升级，继续使用其原手册，不能混用请求体。以下是人工执行用例，不会自动操作已有空间。

每个管理操作使用运维 Admin Key；业务 Key 不具有管理权限。准备已启动的新版本、curl/jq，在同一个 Bash 终端顺序执行。地址示例为 8888，换成实际地址即可。

```bash
bash
umask 077
# DEPLOY 为按部署手册生成的私有配置目录。
export ADMIN_KEY=$(jq -er '.secret' "$DEPLOY/admin-key.json")
export RESULT=$(mktemp -d /tmp/contextdb-curl.XXXXXX)
export TAG="curl-demo-$(date +%Y%m%d%H%M%S)-$$"
```

命令失败先停止后续步骤。创建响应保存在 RESULT；其中 Key 签发响应包含一次性 secret，不提交仓库。

## 一、实例初始化与检查

实例没有 HTTP 创建接口。离线生成 Admin Key、配置 PG/模型、执行 `python -m hindsight_ext_contextdb migrate` 后再启动服务，详见 [部署手册](contextdb-optimized-guide.md)。不要在已有体验库重建凭据或重跑初始化来模拟创建实例。

健康检查无需鉴权，200 的 status=healthy、database=connected：

```bash
curl -fsS 'http://127.0.0.1:8888/health/ready' | jq .
```

**1. GET /admin/session**，无参数。200 返回 user_id、role=admin、instance_id、cloud_tenant_id：

```bash
curl -fsS 'http://127.0.0.1:8888/ext/contextdb/v1/admin/session' \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

## 二、工作空间

**2. POST /workspaces**。name 必填 1～64 字符，description 可选最多512；必填 Idempotency-Key（ASCII字母、数字、下划线、连字符，1～128）。202 只代表受理，返回 operation_id、workspace_id、action、state、error_code，Location 指向查询操作：

```bash
curl -fsS -X POST 'http://127.0.0.1:8888/ext/contextdb/v1/workspaces' \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $TAG-create" \
  -d "{\"name\":\"$TAG\",\"description\":\"管理API验证\"}" \
  | tee "$RESULT/workspace.json" | jq .
export SPACE=$(jq -er '.workspace_id' "$RESULT/workspace.json")
export OP=$(jq -er '.operation_id' "$RESULT/workspace.json")
```

**3. GET /operations/{id}**。路径传操作ID，200 返回同一操作对象；重复查询直到 succeeded，failed 时先检查 error_code：

```bash
curl -fsS "http://127.0.0.1:8888/ext/contextdb/v1/operations/$OP" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

pending/running 尚未完成，不能开始新增授权。查询不重启操作。初始响应丢失时管理员明确决定重试，再使用原幂等Key和完全相同原始请求；failed 的同Key重试可能重新执行。

**4. GET /workspaces**。q 按名称包含匹配（≤128字符），limit 默认20、0～100，offset 默认0、≥0。200 返回 items/total/limit/offset：

```bash
curl -fsS -G 'http://127.0.0.1:8888/ext/contextdb/v1/workspaces' \
  -H "Authorization: Bearer $ADMIN_KEY" \
  --data-urlencode "q=$TAG" --data-urlencode 'limit=20' --data-urlencode 'offset=0' | jq .
```

空间对象含 workspace_id、name、description、state、version、created_at、latest_operation_id。管理列表包含中间/失败状态；内容访问仅 active。workspace_id 同时为 bank_id，客户端不指定 schema。

**5. GET /workspaces/{id}**。200 返回单个上述对象，删除后404：

```bash
curl -fsS "http://127.0.0.1:8888/ext/contextdb/v1/workspaces/$SPACE" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

空间 DELETE 放在最后，避免提前删除影响授权验证。当前不提供空间 PATCH。

## 三、成员

**6. POST /users**。只填 name（1～64非空字符），不选角色、不授予空间、不自动创建Key。201 返回 user_id、name、status、version、created_at：

```bash
curl -fsS -X POST 'http://127.0.0.1:8888/ext/contextdb/v1/users' \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d "{\"name\":\"$TAG-member\"}" | tee "$RESULT/user.json" | jq .
export USER_ID=$(jq -er '.user_id' "$RESULT/user.json")
export USER_VERSION=$(jq -er '.version' "$RESULT/user.json")
```

**7. GET /users**。q/limit/offset 同上；200 返回成员分页，已删除不返回，停用仍保留：

```bash
curl -fsS -G 'http://127.0.0.1:8888/ext/contextdb/v1/users' \
  -H "Authorization: Bearer $ADMIN_KEY" \
  --data-urlencode "q=$TAG" --data-urlencode 'limit=20' --data-urlencode 'offset=0' | jq .
```

**8. PATCH /users/{id}**。name、status 至少一个，status为active/disabled；If-Match必填且带双引号。200 返回更新对象，version增加：

```bash
curl -fsS -X PATCH "http://127.0.0.1:8888/ext/contextdb/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -H "If-Match: \"$USER_VERSION\"" -d "{\"name\":\"$TAG-member-edited\"}" \
  | tee "$RESULT/user-updated.json" | jq .
export USER_VERSION=$(jq -er '.version' "$RESULT/user-updated.json")
```

请求体改为 `{"status":"disabled"}` 即停用，`{"status":"active"}`恢复。每次使用最新版本；停用使其全部Key后续认证失败，恢复不复活吊销Key。后续创建Key要求成员active。

## 四、API Key

**9. POST /users/{id}/keys**。name必填，authorization必填。selected.workspaces为1～1000个不重复active空间，每项workspace_id为32位小写十六进制；新建permission省略时默认read_write：

```bash
curl -fsS -X POST "http://127.0.0.1:8888/ext/contextdb/v1/users/$USER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d "{
    \"name\":\"$TAG-key\",
    \"authorization\":{\"mode\":\"selected\",\"workspaces\":[
      {\"workspace_id\":\"$SPACE\",\"permission\":\"read_write\"}
    ]}
  }" | tee "$RESULT/key.json" | jq .
export KEY_ID=$(jq -er '.key_id' "$RESULT/key.json")
export KEY_VERSION=$(jq -er '.version' "$RESULT/key.json")
export BUSINESS_KEY=$(jq -er '.secret' "$RESULT/key.json")
```

201 返回 key_id、user_id、name、display_key、authorization、version、created_at、last_used_at，以及仅此次返回的secret。secret用于业务认证，key_id只用于管理定位；原Key格式不变。

多空间时给workspaces增加条目，各自选read/read_write。全部空间请求体示例：

```json
{"name":"实例应用","authorization":{"mode":"all","permission":"read_write"}}
```

all包含未来空间且不能提交workspaces；selected不能再提交统一permission。旧平铺access_mode/workspace_ids/permission与新合同混传拒绝。

**10. GET /users/{id}/keys**。q/limit/offset同前；200 返回未吊销分页，display_key如 `ctx_live_***5f82bf`，历史Key无尾缀则null。不含secret/digest，不以未吊销保证成员一定active：

```bash
curl -fsS -G "http://127.0.0.1:8888/ext/contextdb/v1/users/$USER_ID/keys" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  --data-urlencode "q=$TAG" --data-urlencode 'limit=20' --data-urlencode 'offset=0' | jq .
```

**11. PATCH /users/{id}/keys/{id}**。If-Match必填。name可独立修改；authorization一旦提供就完整替换，PATCH每项permission必填，不套用创建默认值。下面只改名：

```bash
curl -fsS -X PATCH "http://127.0.0.1:8888/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -H "If-Match: \"$KEY_VERSION\"" -d "{\"name\":\"$TAG-renamed\"}" \
  | tee "$RESULT/key-updated.json" | jq .
export KEY_VERSION=$(jq -er '.version' "$RESULT/key-updated.json")
```

200 返回元数据，不返回secret，原明文与授权不变。再完整改为只读：

```bash
curl -fsS -X PATCH "http://127.0.0.1:8888/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -H "If-Match: \"$KEY_VERSION\"" \
  -d "{\"authorization\":{\"mode\":\"selected\",\"workspaces\":[
    {\"workspace_id\":\"$SPACE\",\"permission\":\"read\"}
  ]}}" | tee "$RESULT/key-readonly.json" | jq .
```

read可Recall/Reflect及内容读取，不能Retain；read_write也不能管理资源。412表示版本过期，重新读取确认，不能自动覆盖。Key改名不因旧授权空间失效而失败。

**12. DELETE /users/{id}/keys/{id}**。无请求体，无If-Match。永久吊销，不可恢复；204无正文，重复吊销在成员尚未删除时仍204：

```bash
curl -sS -X DELETE "http://127.0.0.1:8888/ext/contextdb/v1/users/$USER_ID/keys/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -o /dev/null -w 'HTTP %{http_code}\n'
```

重新列表应items为空、total=0，后台保留吊销记录。失效指后续认证，不承诺取消已受理任务。

## 五、清理资源

**13. DELETE /users/{id}**。无请求体、无If-Match；204无正文，成员软删除、全部Key失效，空间内容保留：

```bash
curl -sS -X DELETE "http://127.0.0.1:8888/ext/contextdb/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_KEY" -o /dev/null -w 'HTTP %{http_code}\n'
```

**14. DELETE /workspaces/{id}**。必填Idempotency-Key，无请求体；202返回删除操作，不能据此直接判断清理完成：

```bash
curl -fsS -X DELETE "http://127.0.0.1:8888/ext/contextdb/v1/workspaces/$SPACE" \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Idempotency-Key: $TAG-delete" \
  | tee "$RESULT/delete.json" | jq .
export DELETE_OP=$(jq -er '.operation_id' "$RESULT/delete.json")
curl -fsS "http://127.0.0.1:8888/ext/contextdb/v1/operations/$DELETE_OP" \
  -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

重复最后GET到succeeded后，GET该空间应404。本步骤清理该空间数据，只对上文新建的SPACE执行。

## 返回码与错误

200查询/更新，201成员或Key创建，202空间受理，204吊销/成员删除。错误包括400参数、401凭据、403权限、404不存在、409状态/幂等/名称冲突、412版本、503不可用。管理错误最低为code/message/request_id，可有安全fields提示；不会返回敏感原始输入。

`curl -f`遇HTTP错误会报错；需要完整错误体时改为`curl -sS -i`并去掉jq管道。创建成员/Key结果未知不自动重试；不靠名称或最新记录自动吊销。已有明确操作ID就继续GET，刷新页面不自动POST。
