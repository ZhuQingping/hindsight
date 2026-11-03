<a id="contextdb-文档入口"></a>

# ContextBase 部署与维护文档

| 任务 | 入口 |
| --- | --- |
| Windows 原生 / Linux x86_64 本地启动 | [统一启动指南：依赖、配置、鉴权、启停](deployment-local.md) |
| 宿主进程部署 | [宿主进程](deployment-native.md) |
| Linux 容器部署 | [Docker Compose](deployment-docker.md) |
| 宿主/容器的共同前提、配置、初始化与维护 | [部署总览](deployment.md) |
| 召回统计配置、升级与内容恢复 | [统计运维](recall-usage.md) |
| 当前测试方法和验证边界 | [验证入口](../../../docs/contextdb-management/VALIDATION.md) |
| 云平台外部条件与目标环境验证 | [云环境交付待办](../../../docs/contextbase/CLOUD-READINESS.md) |

首次使用按[插件 README](../README.md#reading-order)完成部署、管理员配置和业务验证。
已有服务的应用直接看[业务接入](../README.md#business-quickstart)，
管理员看[空间、用户和 Key 操作](../README.md#admin-quickstart)。

架构和技术规则见[完整设计](../../../docs/contextdb-management/DESIGN.md#overview)，
接口以[管理 OpenAPI](../schemas/contextdb-control-plane.openapi.yaml)为准。
配置生成器的输入见[意图示例](../deployment/intent.example.json)；
[环境变量示例](../deployment/contextdb.env.example)仅供参考，不自动加载。
