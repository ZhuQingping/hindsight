# Hindsight 组件对接与上线验收

本清单约定跨团队对接的最低内容及邀请公测前的验收条件。范围以[公测方案](README.md)为准，责任分工见[工作分解](WORK-ITEMS.md)。所有运行场景初始状态为 `NOT_RUN`，执行后记录对应版本、环境、结果和问题归属。

## 组件合同

| 对接关系 | 必须明确的内容 |
| --- | --- |
| 页面与实例管理服务 | 客户身份、实例归属、操作权限、实例资源、进度、错误、释放与销毁的区别 |
| 实例管理服务与云资源平台 | 资源规格、VPC／子网、安全组、IP、机器、PG、bucket、资源 ID、创建结果、失败清理和回收责任 |
| 实例管理服务与调度 | 可部署位置、规格、容量、分配结果、重复请求和不足时的返回 |
| 实例管理服务与管控 agent | 实例 ID、机器 ID、操作 ID、目标版本、配置版本、启停部署指令、进度、结果、实际状态和心跳 |
| 管控 agent 与 Hindsight | 启动方式、配置与凭证、迁移、健康就绪、停止宽限、版本及配置生效、日志指标 |
| 平台登录与实例功能页 | 客户会话到专属实例的映射、退出、路由、服务凭证保管及页面完整管理权限 |
| Key 管理工具与授权扩展 | 创建、查询、有效期、停用、bank 集合、管理权限、生效结果及元数据权威位置 |
| Hindsight 与 PG | 私网连接、角色权限、pgvector、TLS、迁移连接、向量维度和连接池 |
| Hindsight 与 OBS | bucket、region、endpoint、独立 AK／SK、权限、TLS、签名 URL 可达性和对象生命周期 |
| Hindsight 与内部模型 | LLM／embedding／reranker 分别配置，型号、协议、维度、超时、并发和凭证 |
| 网关与 UI API MCP | HTTPS 地址、证书、续期、路径、认证头、可信代理、Cookie、流式响应、文件传输与超时 |
| 管控 agent 与可观测平台 | 实例与版本标签、日志、机器资源、服务健康、依赖状态、任务状态和告警归属 |

耗时操作需要可查询的进度和终态。接口要约定重复请求、超时后查询、部分成功、失败清理及组件重启后的处理；仅返回“请求已收到”不能代表实例创建或部署成功。

实例管理服务维护目标版本、配置与资源绑定；agent 回报实际版本、配置生效与本机状态。资源释放只处理实例拥有的资源，不能误释放共用或引用的网络等资源。

## 上线验收

| 编号 | 场景 | 通过条件 | 初始状态 |
| --- | --- | --- | --- |
| V01 | 实例创建 | 资源申请、agent 注册、配置、迁移、服务启动、HTTPS 和页面完整跑通，资源归属可查询 | NOT_RUN |
| V02 | 创建失败与重复请求 | 资源不足、申请失败、部署失败和重复请求有明确结果；不会重复占用或遗留无归属资源 | NOT_RUN |
| V03 | PG 接入 | 真实云 PG 的扩展、权限、TLS、迁移和连接正常，向量配置与模型一致 | NOT_RUN |
| V04 | 内部模型 | LLM、embedding、reranker 分别验证，实际抽取、检索和推理流程可执行 | NOT_RUN |
| V05 | 原生能力回归 | 按 T01 基线验证 retain、recall、reflect、后台处理、bank、文档、mental model 和现有主要 UI 能力 | NOT_RUN |
| V06 | OBS 兼容性 | 上传、下载、head、列表、删除、前缀清理及原生使用的分片上传和签名链接正常 | NOT_RUN |
| V07 | 文件生命周期 | 附件、上传、导入导出及文档／bank 删除保持原生行为；PG 元数据与对象引用可正确使用 | NOT_RUN |
| V08 | 实例隔离 | 两个实例使用不同 PG、bucket 和凭证；各自只能访问自己的存储和实例入口 | NOT_RUN |
| V09 | 多 key 与有效期 | 多 key 可用；无效、过期及停用 key 的新请求被拒绝；元数据查询不返回明文密钥 | NOT_RUN |
| V10 | Bank 授权 | REST 和 MCP 的 bank 访问正确拒绝越权，列表及分页不泄露未授权 bank | NOT_RUN |
| V11 | 间接资源授权 | 任务状态与控制、chunks、附件、文件下载、导入导出、clone、别名和预检查均纳入授权检查 | NOT_RUN |
| V12 | 页面与平台身份 | 登录、实例归属、路由、退出及页面操作正常，客户只能进入自己的实例，实例内保持完整管理能力 | NOT_RUN |
| V13 | HTTPS | 证书可信且匹配域名，代理头及 Cookie 正确，认证头正确传递，API、MCP、流式响应和文件传输可用 | NOT_RUN |
| V14 | 客户 Agent 接入 | API／SDK／MCP 使用交付地址和内部发放的 key 可以完成实际操作，原生协议保持一致 | NOT_RUN |
| V15 | 启停与重启 | API、UI 和任务状态可观察；正常停止及重启按原生机制运行，实际完成任务而非只拉起进程 | NOT_RUN |
| V16 | 配置与升级 | 目标配置与实际配置可对应；升级迁移、启动、业务检查及失败状态可追踪 | NOT_RUN |
| V17 | 释放与数据回收 | 释放计算和访问入口保留 PG、OBS 数据与归属；内部单独操作才最终销毁数据 | NOT_RUN |
| V18 | 监控与故障定位 | 能发现进程、PG、OBS、模型、任务和磁盘异常，定位到实例、版本和负责组件 | NOT_RUN |
| V19 | 分批公测 | 固定镜像和配置可重复交付，操作说明与反馈渠道齐备，按计划开放到 10～20 个实例 | NOT_RUN |

V05 应按固定版本的实际功能清单形成回归场景，不以一次模型响应代表全部后台派生处理完成。只读／只写若加入首期，需要追加相应允许与拒绝场景。

## 必须保持的行为边界

- Key 的过期与停用拒绝新请求；已受理任务继续使用原生处理行为，现有取消和重试接口保留。
- 原生签名链接按链接自身有效期失效，不能把 Hindsight key 停用写成已签出 URL 立即失效。
- 网页拥有实例完整权限，bank scope 限制的是对应 Agent key；新增 scoped key 不自动让网页获得成员级隔离。
- 释放计算实例与销毁 PG、OBS 分开；主动删除文档或 bank 仍执行原生对象清理。
- 数据库迁移后的应用回退需要版本兼容检查，首期不声明已完成备份恢复能力。

## 源码依据与实现注意点

以下链接对应导入基线 `a9eeed77f9bce99d8f97d39a30d3281747300824`。源代码支持不等于目标云环境已通过验收。

| 事项 | 源码位置 | 实施影响 |
| --- | --- | --- |
| 单租 API key | [builtin tenant](../../hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py#L44) | 原生内置实现为单 key，完整多 key、有效期和 bank 授权需要补充 |
| 授权扩展 | [operation validator](../../hindsight-api-slim/hindsight_api/extensions/operation_validator.py#L1119) | 可复用 bank 读写和列表等 hook，仍需完整覆盖审计 |
| UI 后端凭证 | [hindsight client](../../hindsight-control-plane/src/lib/hindsight-client.ts#L14) | 当前 UI 使用服务器凭证，符合实例内完整管理权限边界 |
| 原生 S3 配置 | [S3 storage](../../hindsight-api-slim/hindsight_api/engine/storage/s3.py#L20) | 接受 bucket、region、endpoint、AK／SK；OBS 需真实兼容性验证 |
| 文件后端扩展 | [storage factory](../../hindsight-api-slim/hindsight_api/engine/storage/__init__.py#L44) | 原生配置优先，必要时使用 FileStorage 扩展 |
| 原始文件默认清理 | [file defaults](../../hindsight-api-slim/hindsight_api/config.py#L1717) | 原件默认不长期保留，继续沿用原生行为 |
| 签名链接 | [download URL](../../hindsight-api-slim/hindsight_api/engine/storage/base.py#L228) | 原生默认签名有效期为一小时，OBS endpoint 需满足对应下载路径可达性 |
| 内置 worker | [API worker](../../hindsight-api-slim/hindsight_api/api/http.py#L5146) | 默认无需另装 worker 进程，任务仍进入监控和重启验收 |
| 向量维度变更 | [migration check](../../hindsight-api-slim/hindsight_api/migrations.py#L684) | 不能将模型切换视为普通配置刷新，已有数据需检查兼容性 |
| HTTPS 与代理参数 | [API startup](../../hindsight-api-slim/hindsight_api/main.py#L239) | 可由网关终止 TLS，明确启用代理支持并限制可信来源 |
| HTTPS Cookie | [UI session](../../hindsight-control-plane/src/lib/auth/session.ts#L43) | 网关正确设置外部协议，验证登录与 Cookie |
| Standalone 启动 | [start all](../../docker/standalone/start-all.sh#L346) | API 与 UI 分别检查，容器状态不能代替业务状态 |

本期未执行云 PG、OBS、内部模型、网关、浏览器或部署测试，也未实现新增 key 授权。验收状态由实际执行记录更新，备份恢复与集群能力继续按范围延后。
