# Agent memory / REST与MCP集成独立审查

Code-edit permission: **DENIED**。仅本报告允许写入。对象为独立worktree `contextdb-release-hardening-20261016-182619`，base `d5e851b60315b79696e995874e7edc1e9a7bae23` 加已保存原dirty基线；未回退基线，未部署/提交/推送，未启动子代理，未访问8890/9998/5432或任何现存数据库。

领域结论：**ACCEPT**。没有发现本领域新增Critical/Important代码问题；初审四项文档Minor经下方静态复核已全部关闭，当前无未解决领域发现。此结论覆盖Agent调用、动态权限、原生记忆及指导合同；共享代码问题和总体测试由原提出专家及主控制器独立确认。

## Critical

无新增发现。

## Important

无新增发现。主控制器已经受理的跨schema依赖须在原生破坏前校验、旧trigger禁用迁移拒绝、Worker DSN日志脱敏、UI构建来源启动校验，未重复列为本领域阻断；需由原提出领域核对最终修改和验证。

## Minor（初审记录，A-01～04已全部关闭）

### A-01：设计的密码修改说明与托管启动的持久秘密优先级不一致

- 位置：`hindsight-extensions/contextdb-service/docs/contextdb-release-design.md:100`、`:410`；实际加载：`hindsight-extensions/contextdb-service/hindsight_ext_contextdb/bootstrap.py:133`～`:135`、`launch.py:42`。
- 触发：管理员按Q&A仅修改 `HINDSIGHT_CP_ACCESS_KEY` 环境配置并重启托管UI。launch随后把 `ui-secrets.json.password` 再写回该环境变量，旧持久密码继续有效。
- 建议：与 optimized-guide.md:192一致，明确首次初始化可从环境选择自定义密码；初始化后修改 `ui-secrets.json.password` 并重启全部UI进程。不要将旧体验环境 `ui-settings.json` 说明混为本版托管入口。

### A-02：设计的PG字段表保留元数据2和无角色的旧描述

- 位置：`hindsight-extensions/contextdb-service/docs/contextdb-release-design.md:323`、`:325`。
- 触发：运维/Agent据表核对新库，看到metadata_version=3和users.role，会误判交付结构不一致。
- 建议：改为metadata_version=3，并列出name_key/role；说明内部唯一protected admin为admin，普通成员固定member，公开成员CRUD不提供角色输入。此处与同文:58、:399已有正确说明冲突。

### A-03：curl手册错误声称空间只读详情返回ETag

- 位置：`hindsight-extensions/contextdb-service/docs/contextdb-optimized-curl-guide.md:667`。
- 触发：按本行验收GET空间详情的ETag，实际没有该Header；空间没有PATCH，version并非该只读响应的HTTP编辑快照。
- 建议：保持与设计4.1一致，只承诺用户和Key创建/编辑的ETag；Key列表含近似使用时间而不发ETag，空间只读详情不发ETag。

### A-04：当前使用指南未给出可照做的MCP连接及正向记忆流程

- 位置：`hindsight-extensions/contextdb-service/docs/contextdb-optimized-guide.md:196`、`docs/contextdb-optimized-curl-guide.md:532`。
- 触发：新部署者按当前指南验收Agent记忆。guide称按curl手册验证REST/MCP，但三份当前设计/部署/curl文档都未给出 `/mcp/`、`/mcp/{workspace_id}/` 连接地址或Bearer客户端示例；curl只做空list及预期拒绝写，正向模型流程“另见业务验收文档”没有链接。测试覆盖充分，手工接入的最后一步仍靠读源码/测试发现。
- 建议：在当前使用文档增加一个短入口或明确链接到同版可执行示例：普通读写Key + UUID，retain→等待operation completed→recall/reflect；单空间MCP省略工具bank_id，多空间MCP每工具传UUID或设置X-Bank-Id；同会话降权后写入拒绝；说明read仍可reflect且消耗模型。复用test_100/110/113的真实客户端合同，不引入新API或服务。

## 已接受的领域合同与证据

- 身份没有隐藏在Key前缀：security.credential_key_id只定位，Repository.authenticate从PG读digest、owner.role和当前授权，统一HMAC校验；issue_admin_key保留的SHA仅是离线交付校验，运行认证未调用它。
- `workspace_id=bank_id`、`ctxdb_ws_<UUID>`始终一对一。仅管理GET详情按规范名称；授权、DELETE、原生REST/MCP继续UUID。未混入早期全面可读寻址候选。
- 一把普通Key可all或selected逐空间read/read_write；read覆盖memory/knowledge/reflect，写入额外要求memory.write。all没有管理角色；管理员也不能通过原生create/delete/clone/import/alias绕过空间生命周期。
- REST先按真实路径确定bank，持久准入保护响应/取消；引擎validator复核当前Key、schema、space与scope。调用方schema header不能切换空间。
- MCP middleware从当前HTTP消息读取Bearer，每次选择真实工具bank；单空间路径与参数不匹配即拒绝。tools/list过滤不是唯一安全门，工具执行仍经准入和引擎授权；同session权限不会继承initialize的强身份。
- test_104/105覆盖同session切Key、知识工具与跨空间隔离；test_110覆盖同明文Key实时移除空间、降为read、tools/list收缩、停用与同session拒绝；test_111覆盖吊销旧session且兄弟Key继续工作。均以真实HTTP/MCP客户端调用，不只断言内部过滤函数。
- test_115通过公开SDK先写入并确认记忆，再删除、同名重建、确认新UUID无旧内容、旧selected授权为空及旧编辑412，并重放旧DELETE只返回旧operation。旧selected不会升级all，同名新建不继承权限。
- test_100/101/103/108/109的记忆断言使用公开SDK/MCP，内容由外部输入和模型stub产生；没有用引擎/SQL制造或查询记忆。PG/扩展迁移只在独立fixture的离线部署中使用。模型stub脚本不等价真实MaaS质量评估，文档已明确这一边界。
- HTTP异步空间操作与原生记忆任务的生命周期清晰：202表示受理，GET不重启操作；已受理原生任务允许排空，未知执行者保守阻断。终态历史独立保留168h、未知浏览器写意图24h限制，均不要求新Agent服务或调度平台。
- 现有Cloud节点Agent/systemd/容器监督器负责前台原生API/Worker/UI的启停；默认内嵌Worker，独立Worker可读原生环境端口。文档没有新增Cloud控制协议或实例创建HTTP接口。

## 验证记录

- **RUN（本审查）**：读取AGENTS→CLAUDE、`.claude/skills/code-review/SKILL.md`、workflow precedence/review-gate/verification-matrix、artifacts/task.md；只读git status与rg/逐段代码、当前文档和100～115系统故事检查。
- **RUN（本审查）**：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/hindsight-extensions/contextdb-service:$PWD/hindsight-api-slim" .venv/bin/python -B -m pytest -p no:cacheprovider hindsight-extensions/contextdb-service/tests/test_security.py hindsight-extensions/contextdb-service/tests/test_authorization_models.py -q`，exit0，**26passed**。仅纯函数/模型验证，没有PG或网络访问。
- **RUN（实现方，审查读取日志）**：extension-fourth-sweep.log **366passed**；system-full-sweep.log **60passed/1failed**，失败是fixture对离线迁移新增pepper/admin_secret参数的旧mock断言；主控制器已报告fixture修复并在system-fixture-correction.log补跑**2passed**。不能把此前全量失败记为本审查亲自全绿。
- **NOT RUN（本审查）**：DB集成/真实服务/部署、UI构建、根lint（会自动改文件，与审查只读边界冲突）。未验证真实MaaS、中英文检索质量、PGroonga恢复、生产容量、云HA或入口HTTPS/限流。
- **RECOMMENDED**：最终四项共享修复完成后由主控制器运行适当部署回归与最终相关套件，原发现专家重新确认；同步A-01～04文档后无需扩大Agent安全机制。

领域共识：Agent调用与动态权限/原生记忆生命周期方向及实现可接受，**ACCEPT（无新增代码must-fix）**。跨领域总验收仍由主控制器汇集四类独立结论后记录，不以本报告替其他领域提前签字。


## 文档修订复核与最终领域共识

本轮仅文档与静态复核，代码编辑仍为**DENIED**；仅修改本报告。

| 初审发现 | 复核位置与结果 | 状态 |
| --- | --- | --- |
| A-01 密码持久来源 | release-design.md:100、:410明确托管部署修改ui-secrets.json.password并重启UI，临时环境/ui.env会被持久秘密覆盖；optimized-guide.md:119、:224一致。原生直接启动的环境配置与托管来源已区分。 | CLOSED |
| A-02 PG结构表 | release-design.md:323写metadata_version=3，:325包含name/name_key、role(admin/member)且无用户级空间授权；:58继续明确唯一受保护系统管理员及固定member。 | CLOSED |
| A-03 ETag | optimized-curl-guide.md:718改为用户/Key编辑响应含ETag、空间只读详情不发ETag，与设计:242及Key列表:763一致。 | CLOSED |
| A-04 接入与正向记忆 | optimized-curl-guide.md:461新增公开SDK异步retain→operation等待→recall/reflect示例；:490明确检查failed且不以队列空判质量；:492～509给出带业务Key的单空间MCP /mcp/{UUID}/、多空间/mcp/显式bank_id，以及旧session收权/同名重建的真实自动故事入口。 | CLOSED |

部署补充也已静态核对：optimized-guide.md:32使用正式build-ui --source-root命令，__main__.py:92分发至artifacts.build_ui，launch.py:16确实调用verify_ui_build；:124～152补完整LLM/Embedding/Rerank配置并安全读取Key，所用BASE_URL、MODEL及DIMENSIONS环境名存在于原生config.py，不把配置示例当真实模型连通/质量证据。

- **RUN（本轮）**：只读逐行/rg检查当前设计、curl、部署指南及对应CLI/SDK签名；已确认旧metadata_version=2/无角色表描述及空间ETag承诺不再出现在三份当前指南。
- **RUN（本轮）**：用Python ast.parse静态解析optimized-curl-guide和optimized-guide的4个Python heredoc示例，全部成功；仅解析，未执行示例、未读真实配置、未发网络请求。
- **NOT RUN（本轮）**：模型、SDK/MCP实际服务调用、构建及全系统套件；已有初审26项纯函数/模型测试证据保留。主控制器报告扩展372/UI390此前通过，system-final-verified.log仍在进行，不将其写成最终通过。

最终领域共识：**ACCEPT**。Agent memory / REST与MCP集成及其当前使用指导没有未关闭的Critical、Important或Minor；支持在其他三类专家完成共享修改复核、主控制器确认最终验证后形成总体一致。未部署、未提交/推送、未接触现有服务或数据库。
