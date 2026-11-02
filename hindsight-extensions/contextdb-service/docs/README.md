<a id="contextdb-文档入口"></a>

# ContextDB 文档导航

第一次部署并使用插件，按[插件 README 的四步阅读顺序](../README.md#reading-order)走：了解用途和凭据 → 部署启动 → 管理员创建空间和 Key → 业务写入与召回。无需先阅读评审记录，也不用把所有文档从头读完。

已有服务时，按当前任务直接进入：

| 读者 | 当前入口 |
| --- | --- |
| 连接已有服务的应用/Agent 用户 | [业务接入](../README.md#business-quickstart)；[Coding Agents 客户安装](../../../hindsight-integrations/coding-agents/README.public.md)、[Python SDK](../../../hindsight-clients/python/README.md)、[TypeScript SDK](../../../hindsight-clients/typescript/README.md) |
| 管理空间、用户和 Key 的管理员 | [UI 操作顺序与截图](../README.md#admin-quickstart)，完整规则见[设计第 3 章](../../../docs/contextdb-management/DESIGN.md#ui) |
| 部署/维护实例的运营者 | [部署总览](deployment.md)选择[宿主进程](deployment-native.md)或[Docker](deployment-docker.md)；插件配置与优先级共用[一份说明](deployment.md#configuration) |
| 理解实现或参与开发的贡献者 | [唯一 DESIGN](../../../docs/contextdb-management/DESIGN.md#overview)、[源码与测试入口](../README.md#development) |

## 当前技术依据

完整架构、对象关系、权限和生命周期只在 [DESIGN.md](../../../docs/contextdb-management/DESIGN.md)维护。教程给操作步骤并引用规格，不复制第二套设计。机器契约在代码仓：[管理 OpenAPI](../schemas/contextdb-control-plane.openapi.yaml)、[完整 DDL](../hindsight_ext_contextdb/schema.sql)；生成器支持的输入见[意图示例](../deployment/intent.example.json)，[env 示例](../deployment/contextdb.env.example)只是补充参考，不自动加载。

## 检视、验收与历史来源

[CODE-REVIEW](../../../docs/contextdb-management/CODE-REVIEW.md)保存检视发现与实现位置，[VALIDATION](../../../docs/contextdb-management/VALIDATION.md)保存实际验证结果和未验边界，均保留对应日期和版本。二者是支撑记录，不替代当前操作指南。

原始设计来源固定于 [ContextDB-Research@5f9993c2](https://github.com/ZhuQingping/ContextDB-Research/blob/5f9993c2c1d9eb68a83decdb99590f4dfe7d76dd/hindsight/design/contextdb-release-design.md)。其部署和运维材料是历史背景；当前行为应核对同一 checkout 的设计、部署指南和代码，不把历史 SHA 或旧评审中的“最新”当作当前状态。


Local development with authentication and persistent embedded PG: [deployment-local.md](deployment-local.md).
