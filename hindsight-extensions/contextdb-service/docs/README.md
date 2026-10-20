# ContextDB 文档入口

当前RSIXDB团队集成的完整设计见 [DESIGN.md](../../../docs/contextdb-management/DESIGN.md)。以原始完整设计为基础，直接在相关章节更新团队适配和不完备之处；所有读者使用同一份设计。

[代码走读及检视记录](../../../docs/contextdb-management/CODE-REVIEW.md)提供实现位置与发现；[验证记录](../../../docs/contextdb-management/VALIDATION.md)记录实际结果及边界。二者作为设计支撑，不替代设计正文。

原始设计来源固定于 [ContextDB-Research@5f9993c2](https://github.com/ZhuQingping/ContextDB-Research/blob/5f9993c2c1d9eb68a83decdb99590f4dfe7d76dd/hindsight/design/contextdb-release-design.md)。其部署/运维材料提供背景；当前团队配置和会话差异以同版完整设计为准，本轮按a05b808适配，其最新实现位于未提交团队工作树，不能仅用HEAD检查。

机器契约保留在代码仓：[管理OpenAPI](../schemas/contextdb-control-plane.openapi.yaml)、[完整DDL](../hindsight_ext_contextdb/schema.sql)。源码启动与部署资产见[扩展README](../README.md)、[deployment](../deployment)。
