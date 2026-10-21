# ContextDB 文档入口

详细文档统一在[资料仓](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/README.md)维护；本目录只提供入口，不保留重复副本。

## 代码检视只按这个顺序读

1. [特性设计](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/design/contextdb-release-design.md)：先看第1章总体设计、第5章实现理由、第6章边界及文末TODO；接口、PG表、安全和恢复细节都在同一文档中。
2. [代码对比与检视顺序](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/design/code-review-guide.md#专家检视顺序)：按原生接入、外围扩展、UI、部署和测试分别查看相对 v1.0.0 的差异。

这两份是评审主线。部署手册、过程调研及截图不要求逐份通读；两张架构图随设计正文阅读，可编辑drawio原稿保存在资料仓。

## 需要实际操作时再查

| 工作 | 文档 |
| --- | --- |
| 部署自研 ContextDB | [部署合同](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/deployment/contextdb-deployment-contract.md) · [联调指南](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/deployment/contextdb-service-integration-guide.md) |
| 先部署官方原生 Hindsight | [原生部署合同](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/deployment/native-v1.0.0/contextdb-deployment-contract.md) · [原生联调指南](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/deployment/native-v1.0.0/contextdb-service-integration-guide.md) |
| 手工验证接口和权限 | [curl用例](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/api/contextdb-management-api-curl-guide.md) |
| 运维排障 | [运维手册](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/operations/contextdb-operations-runbook.md) |

官方原生部署的配置模板、Compose、渲染器、源码启动器和工具测试统一在[资料仓 tools/](https://github.com/ZhuQingping/ContextDB-Research/tree/main/hindsight/deployment/native-v1.0.0/tools)维护，不随自研扩展交付。

接口定义不属于阅读副本：[OpenAPI](../schemas/contextdb-control-plane.openapi.yaml)保留在代码仓，生成器和测试均使用它。

文档只在资料仓修改；代码变更涉及接口、部署或安全边界时同步更新资料仓，并在提交或PR中记录对应文档版本。正式评审固定代码提交和资料提交，避免用不断变化的main分支冒充同一快照。
