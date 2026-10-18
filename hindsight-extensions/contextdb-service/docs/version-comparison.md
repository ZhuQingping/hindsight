# ContextDB V1 / V2 版本与对比

> **历史快照，不适用于当前首发版本。** 下文保留当时的配置、接口、表结构和测试环境用于对照，不应照此部署或验证当前代码。当前以[首发设计](contextdb-release-design.md)、[部署合同](contextdb-deployment-contract.md)和[API验证手册](contextdb-optimized-curl-guide.md)为准；开发期旧库不自动升级。

两版都基于 Hindsight `a77c1f3412a7b82f36588dffce1a8d7480e99cc7`，各包含一个完整功能提交。V1 分支和提交保持不变；V2 从此前开发工作树整理得到，运行时实现保持相同。

```text
Hindsight a77c1f341
├── contextdb/service-management     → V1 cdfc199e5
└── contextdb/service-management-v2  → V2 本分支 HEAD
```

| 项目 | V1 | V2 |
| --- | --- | --- |
| 用户归属 | 工作空间内成员 | 实例级用户，与工作空间同级 |
| Key 范围 | 固定一个工作空间/Bank | 一 Key 多空间，各自 scopes |
| 权限修改 | 换 Key | 原 secret 不变，修改 grants |
| 管理员 | 空间管理员 | 唯一实例管理员，全空间 all Key |
| UI | 原生固定数据面 Key | 管理员独立口令、all 服务端 Key、用户/Key 管理 |
| 对外术语 | Bank/记忆库 | ContextDB 中英文 UI 使用 Workspace/工作空间 |
| 空间存储 | 每空间独立 schema、唯一 Bank | 保持一空间一 schema 一 Bank |
| metadata | 版本 1，9 张表 | 版本 2，8 张表；使用新库，不迁移 v1 |
| 管理 REST | 16 个操作 | 18 个操作；空间生命周期与用户管理认证分开 |
| 原生内核改动 | 9 文件 +211/-20 | 与 V1 相同；V2 未再增加内核改动 |

在包含两个分支的仓库中执行：

```bash
# 分别观察两版相对上游的完整实现。
git diff a77c1f341 contextdb/service-management --stat
git diff a77c1f341 contextdb/service-management-v2 --stat

# 直接比较两版最终文件内容，适合评审设计和实现的变化。
git diff contextdb/service-management contextdb/service-management-v2 --stat
git diff contextdb/service-management contextdb/service-management-v2 -- hindsight-extensions/contextdb-service
git diff contextdb/service-management contextdb/service-management-v2 -- hindsight-control-plane

# 应为空：V2 没有额外改动 Hindsight 内核。
git diff contextdb/service-management contextdb/service-management-v2 -- hindsight-api-slim

# 两个功能提交的 parent 应为相同上游基线。
git rev-parse contextdb/service-management^ contextdb/service-management-v2^
```

直接比较 V1/V2 使用上述两端形式。`git diff V1...V2` 会从公共祖先比较到 V2，适合看 V2 完整改动，不能当作两版最终实现的差异。

部署、配置、验证与随版 OpenAPI 在本目录维护；产品架构和竞品分析在 ContextDB-Research 研究仓维护。真实运行配置、凭据、数据库和测试日志不纳入提交。
