# ContextDB 工作空间、用户与 API Key

| 任务 | 入口 |
| --- | --- |
| 业务接入与管理员操作 | [插件 README](../../hindsight-extensions/contextdb-service/README.md) |
| 本地启动（Windows 原生 / Linux x86_64） | [本地启动指南](../../hindsight-extensions/contextdb-service/docs/deployment-local.md) |
| 安装、配置、初始化与维护 | [同版本部署指南](../../hindsight-extensions/contextdb-service/docs/deployment.md) |
| 架构、权限、生命周期及恢复边界 | [完整设计](DESIGN.md#overview) |
| 管理接口与数据结构 | [OpenAPI](../../hindsight-extensions/contextdb-service/schemas/contextdb-control-plane.openapi.yaml)、[DDL](../../hindsight-extensions/contextdb-service/hindsight_ext_contextdb/schema.sql) |
| 召回统计配置、升级与内容恢复 | [统计运维](../../hindsight-extensions/contextdb-service/docs/recall-usage.md) |
| 浏览器公开资源与品牌检查 | [品牌检查指南](../contextbase/BROWSER-BRAND-AUDIT.md) |
| 测试入口与验证边界 | [验证入口](VALIDATION.md) |
| 云平台外部条件与目标环境验证 | [云环境交付待办](../contextbase/CLOUD-READINESS.md) |

使用同一 checkout 的 API、扩展和 UI。源码和历史实现以 Git/PR 记录为准；
验证结果须绑定实际环境、提交和产物，不能从旧记录推断当前版本已通过。
