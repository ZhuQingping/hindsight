# ContextBase 浏览器端品牌审计

审计日期：2026-10-29。基线：`RSIXDB/hindsight` 的 `main`，提交
`c82f3bd5a4cfb3212307d14d312316f0048e4879`。提交前再次检查主干，版本未变化。
修改分支：`codex/contextbase-browser-brand-audit`。本次没有修改或合并 main。

## 验证边界与构建方式

- 控制台为 Next.js 16.3.8 App Router、React 19、next-intl、Tailwind CSS，使用 npm workspaces。
- `npm run build --workspace=contextbase-control-plane` 先构建 `contextbase-client`，再执行生产
  `next build`，最后复制 standalone 运行目录并扫描浏览器资源。
- 生产目录为 `contextbase-control-plane/.next` 和 `contextbase-control-plane/standalone`。
  浏览器静态资源来自 `.next/static`、`public` 及 standalone 内的对应复制件。
  动态页面由服务端生成，另启动真实 standalone 服务检查返回的 HTML/RSC 和 HTTP 响应。
- Docker 的 `cp-builder` 单独执行 Next 构建并复制上述目录，本次也在该构建路径加入扫描。
- 仓库是私有仓库。本环境无法直接 git clone，使用 GitHub 连接按固定提交获取了完整控制台、
  TypeScript SDK、UI 测试及所需构建/部署文件。远端分支始于该 main 提交，仅提交审计相关变更，
  未将本地检查快照中的其他文件作为新内容提交。
- 未连接实际部署服务。生产 HTTP 验证使用本机 standalone 服务和受控的 stub 数据面，
  不是线上浏览器验收；尚未对 ContextBase 执行真实浏览器端 JS 的端到端测试。

## 发现与处理

| 问题                      | 具体位置                                                                                                   | 影响与处理                                                                                                                                                                                                                                    |
| ------------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 旧完整 Logo               | `contextbase-control-plane/public/logo.png`                                                                | 图片中直接含 Hindsight 字样。即使页面不引用，静态资源 URL 仍可公开请求。用现有 `product-icon.svg` 渲染为 PNG，保留原 URL。                                                                                                                    |
| 旧 favicon 图形           | `contextbase-control-plane/public/favicon.png`                                                             | 保留了旧上游图标，同样可直接请求。改为相同的 ContextBase 产品图标；页面元数据原本已引用新 SVG。                                                                                                                                               |
| 浏览器事件旧前缀          | `src/components/bank-selector.tsx:257`、`:497`，`banks-overview.tsx:244`、`:264`，`documents-view.tsx:111` | 主干生产 JS 中实际出现 6 次 `hindsight:`。同步修改全部发送方、监听方以及扩展 UI 测试，使用 `contextbase:create-bank`、`contextbase:documents-refresh`。                                                                                       |
| 部分代理透传服务端故障    | 24 个 `src/app/api/**/route.ts` 文件，详见文件清单                                                         | 原始 5xx JSON/HTML 可能含旧品牌、源码路径或内部诊断。直接代理的原始 JSON 统一通过 `publicUpstreamPayload`；管理代理返回固定服务错误并保留状态、ETag、请求 ID、禁止缓存头；retain 的 5xx details 置空。已有安全的 SDK/本地化错误路径继续保留。 |
| 旧 ContextDB 展示文案     | `src/lib/contextdb.ts`、`src/app/api/contextdb/[...path]/route.ts`                                         | 改为 ContextBase；未改 ContextDB 的路由、协议字段、类名或配置键。                                                                                                                                                                             |
| 缺少公开资源回归检查      | `next.config.ts`、`package.json`、新增审计脚本                                                             | 原生产构建没有发现公开 Source Map，Next 默认已关闭；现在显式设置 `productionBrowserSourceMaps: false`，并检查公开 map、源码引用、旧品牌、旧图片哈希及合成私有配置标记。                                                                       |
| Docker 依赖清理表达式过期 | `docker/standalone/Dockerfile:114`、`:121`                                                                 | 原表达式匹配 `@vectorize-io/contextbase-client`，实际依赖已是 `contextbase-client`，无法移除本地 file 依赖。修正匹配，并在 standalone 打包复制完成后扫描最终资源。                                                                            |

页面标题、登录及接入文案、现有产品图标、翻译资源中未发现需要继续替换的 Hindsight 展示文案。
未新增公共 API 地址或凭证；客户接入信息仍仅取显式公开配置，不回退到控制台内部数据面地址。

## 保留的标识与理由

| 保留项                                      | 理由及浏览器边界                                                                                                                                 |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `HINDSIGHT_CP_*` 兼容环境变量               | `src/lib/control-plane-env.ts:3` 在服务端读取，优先使用 `CONTEXTBASE_CP_*`。保留已有部署兼容性；检查的生产浏览器资源中没有这些标识或合成配置值。 |
| `hindsightClient`                           | `src/lib/contextbase-client.ts:43` 及两处服务端路由使用的内部变量；模块有 `server-only`，不进入浏览器包。                                        |
| 仅服务端的历史注释                          | 不进入浏览器包的服务端注释保留；已清理工作区、CSS、图处理和提示词预览中的客户端品牌残留。                                                        |
| 已发布 npm 包、CLI 和镜像的兼容身份         | 保留分发与操作员命令的兼容性；前端物理目录和相关构建/启动路径已迁移到 `contextbase-control-plane/`。                                             |
| SDK 和 Next 服务端 Source Map               | SDK 的 `dist/*.map` 和 `.next/server` 不是公开静态目录。保留服务端调试资料，只禁止浏览器可请求的 map。                                           |
| `contextdb` 路径、协议键、类名、数据属性    | 属于管理扩展和产品配置协议，保留原 API/认证和兼容语义；只修改面向用户的文案。                                                                    |
| 客户正文、文件、名称及 4xx 校验内容中的旧词 | 可能是客户真实数据，禁止全局替换。测试验证成功结果、下载字节和校验输入不被改写。                                                                 |
| 第三方依赖与许可证                          | 保留原标识和版权；没有为了品牌清理改写第三方代码。                                                                                               |

## 复核发现的四项问题及补修

原版 PR 的“无阻断问题”结论经复核修正，已补齐以下内容：

1. 默认扫描同时覆盖 `standalone/.next/server/app` 下的 HTML/RSC；存在 standalone 目录时，缺少关键打包目录会报错。增加独立打包 HTML、RSC 含旧品牌时失败的测试，且 Docker 将扫描移到最终复制完成之后。
2. 源码和生产 HTTP 的检测规则加入仓库登记的历史名称 `agentstratum`；增加内容及资源文件名的拒绝用例。没有在当前正常产物中发现该历史名称，修复的是漏检能力。
3. 依据根 `.prettierrc.json` 的 `trailingComma: es5` 规则修正新测试的逗号，根配置下的格式检查通过。
4. HTTP 脚本串行启动普通模式和 ContextBase 管理模式；每种模式独立管理会话及 stub 后端。新增的 `Browser brand audit` 工作流在每次相关 PR 更新时自动运行该检查。

## GitHub CI 的启动失败根因

已通过 Actions 页面注释确认：[原 CI #53](https://github.com/RSIXDB/hindsight/actions/runs/40864127097)
在启动前被仓库 Actions 允许名单拒绝，列出的依赖包括 `actions/cache@v5`、`astral-sh/setup-uv@v7`、
`dorny/paths-filter@v4`、`jlumbroso/free-disk-space@main`、`docker/setup-buildx-action@v4` 等。
这不是前端测试运行失败：该 run 没有启动任何 job。

本次审计使用独立 `.github/workflows/browser-brand-audit.yml`，仅引用仓库已允许的
`actions/checkout@v6`、`actions/setup-node@v6`，权限为 `contents: read`。
工作流执行前端测试、根配置格式检查、合成私有配置标记构建、最终产物扫描及两种模式 HTTP 审计。
原全量工作流及仓库安全设置未改动；全量 CI 的允许名单阻断仍需独立处理。
新审计工作流的实际运行结果以 PR 的 `Browser brand audit` 检查为准。

## 验证结果

| 检查               | 结果                                                                                                                                                                                                                                                                                                                                                       |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 生产构建           | SDK、Next 编译、TypeScript 类型检查及 standalone 复制成功。使用合成内部 URL、API Key、UI 密码进行构建。                                                                                                                                                                                                                                                    |
| 最终公开资源扫描   | 通过，扫描 120 个文件（包含 standalone 重复复制件），覆盖 25 个 Next 静态文件、25 个 public 文件及静态 HTML/RSC。旧品牌、旧资源名、公开 Source Map、公开源码引用和合成私有标记未命中。                                                                                                                                                                     |
| 前端及扩展 UI 测试 | `TZ=UTC npm test --workspace=contextbase-control-plane -- --maxWorkers=2`；85 个测试文件、860 项全部通过。包含事件创建/刷新路径，以及新增的 5xx、4xx、成功响应、下载、扫描拒绝场景和管理请求关联测试。                                                                                                                                                     |
| 生产 HTTP 审计     | `npm run test:browser-brand --workspace=contextbase-control-plane`；普通模式 67 项检查、20 个加载资源；管理模式 89 项检查、21 个加载资源，均通过。覆盖中英文登录、登录/退出、主要页面、用户创建、密钥仅创建时返回、密钥列表去除 secret/digest、工作区创建/读取/删除、管理 503、管理员权限撤销，以及 PNG、Source Map 404、图与上传错误；数据面是本地 stub。 |
| 前端 ESLint        | 0 errors，203 个现有 warnings；新增测试文件单独 ESLint 通过。                                                                                                                                                                                                                                                                                              |
| 格式与差异         | 按仓库根 `.prettierrc.json` 检查变更 TypeScript 和脚本；`git diff --check` 通过。                                                                                                                                                                                                                                                                          |
| 全仓 lint          | 尝试 `bash scripts/hooks/lint.sh`，但该脚本先同步整个 Python monorepo；本地仅获取了前端及审计所需文件，没有根 Python 项目，无法执行。前端 lint 已单独运行。                                                                                                                                                                                                |
| i18n 检查          | 原 `tsx` CLI 在本环境创建 Unix socket 被拒绝；改用 `node --import tsx scripts/find-untranslated.ts` 执行，仍报告未修改的 `src/components/product-runtime.tsx:57` 已有英文提示。这不是本次新增问题。                                                                                                                                                        |
| Docker             | 修正后的 sed 表达式用实际 package.json 验证，能移除正确依赖且输出有效 JSON；未执行 Docker 镜像构建。                                                                                                                                                                                                                                                       |

扫描可独立重跑：

```bash
npm run audit:browser --workspace=contextbase-control-plane
npm run test:browser-brand --workspace=contextbase-control-plane
```

`BROWSER_AUDIT_PRIVATE_MARKERS` 支持逗号分隔的**合成**配置值，用于构建时验证服务端配置不进入公开资源；
不要为了测试将真实凭证传入该变量。

## 审查结论与剩余范围

本次修复限于公开资源、浏览器事件名、对外文案、代理 5xx 诊断边界与对应构建检查。
已审查发送/接收方一致性、4xx/成功返回值、下载字节、认证与请求关联，未发现待修复的阻断问题。

- 没有访问客户线上环境、网关/CDN 或已发布镜像，不能宣称线上浏览器已经不存在旧标识。
- 没有运行真实 Chromium。React 行为由已有 jsdom 测试覆盖，生产传输层由真实 standalone HTTP 覆盖。
- 反向代理若额外发布 `.next/server`、源码目录或 SDK 调试文件，会绕过本次静态服务边界，部署时必须另查。
- 生产环境的外部脚本、定制运行时公开配置、历史业务数据、后端生成的诊断/成功数据和第三方服务返回值
  可能含旧词。4xx 保持原校验协议和客户输入，不做无差别内容净化；不能由本地 stub 验证所有真实后端文本。
- 图片扫描能拒绝这次识别的两个历史位图，不具备通用 OCR/图像品牌识别能力；新增图片仍需人工检查。
- 若 CDN/浏览器长期缓存了旧 PNG 或 JS，需在部署新版本后更新缓存，不能仅凭仓库修复判断已更新。
- 5xx 原始错误详情不再发送给浏览器，排障应使用服务端日志/请求 ID；HTTP 状态与认证判断保持原逻辑。
- 默认时区运行时，一个已有日期测试会受夏令时影响；在 UTC 下完成最终全量测试，没有改动该无关日期实现。

## 修改文件清单

下表列出本次修改及新增的全部文件，路径相对于仓库根目录。

| 文件                                                                                             | 改动与原因                                                                 |
| ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| `.github/workflows/browser-brand-audit.yml`                                                      | 使用仓库已允许的 Actions，自动运行格式、测试、构建扫描和两种模式 HTTP 验证 |
| `docker/standalone/Dockerfile`                                                                   | 修正旧 SDK 依赖匹配，standalone 打包完成后扫描最终公开资源                 |
| `docs/contextbase/BROWSER-BRAND-AUDIT.md`                                                        | 记录审计发现、保留项、验证证据和边界                                       |
| `contextbase-control-plane/next.config.ts`                                                       | 显式关闭生产浏览器 Source Map                                              |
| `contextbase-control-plane/package.json`                                                         | 生产构建接入扫描，提供可重跑审计命令                                       |
| `contextbase-control-plane/public/favicon.png`                                                   | 以现有产品 SVG 渲染的 PNG 替换旧图，保留 URL                               |
| `contextbase-control-plane/public/logo.png`                                                      | 以现有产品 SVG 渲染的 PNG 替换旧图，保留 URL                               |
| `contextbase-control-plane/scripts/audit-browser-artifacts.mjs`                                  | 公开产物扫描或真实 standalone HTTP 验证                                    |
| `contextbase-control-plane/scripts/test-browser-brand.mjs`                                       | 公开产物扫描或真实 standalone HTTP 验证                                    |
| `contextbase-control-plane/src/app/api/banks/[bankId]/attachments/[attachmentId]/route.ts`       | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/banks/[bankId]/clone/route.ts`                            | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/banks/[bankId]/consolidation-strategies/preview/route.ts` | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/banks/[bankId]/export/route.ts`                           | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/banks/[bankId]/import/route.ts`                           | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/banks/[bankId]/observations/scopes/route.ts`              | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/contextdb/[...path]/route.ts`                             | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/documents/chunks/route.ts`                                | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/documents/reprocess/route.ts`                             | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/documents/route.ts`                                       | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/documents/transfer/route.ts`                              | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/file-storage/config/route.ts`                             | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/files/download/route.ts`                                  | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/files/retain/route.ts`                                    | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/graph/route.ts`                                           | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/knowledge-base/export/route.ts`                           | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/knowledge-base/folders/route.ts`                          | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/knowledge-base/nodes/[nodeId]/route.ts`                   | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/knowledge-base/pages/[pageId]/route.ts`                   | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/knowledge-base/pages/route.ts`                            | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/knowledge-base/search/route.ts`                           | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/knowledge-base/tree/route.ts`                             | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/memories/retain/route.ts`                                 | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/app/api/stats/[agentId]/memories-timeseries/route.ts`             | 限制原始 5xx 诊断外发，保留状态及原调用流程                                |
| `contextbase-control-plane/src/components/bank-selector.tsx`                                     | 同步浏览器事件发送方与监听方的新前缀                                       |
| `contextbase-control-plane/src/components/banks-overview.tsx`                                    | 同步浏览器事件发送方与监听方的新前缀                                       |
| `contextbase-control-plane/src/components/documents-view.tsx`                                    | 同步浏览器事件发送方与监听方的新前缀                                       |
| `contextbase-control-plane/src/lib/contextdb.ts`                                                 | 仅将展示给浏览器的产品文案改为 ContextBase                                 |
| `contextbase-control-plane/src/lib/public-upstream-payload.ts`                                   | 统一保护直接代理的 5xx 返回内容                                            |
| `contextbase-control-plane/tests/lib/browser-artifacts.test.ts`                                  | 对应行为回归或事件契约更新                                                 |
| `contextbase-control-plane/tests/lib/proxy-error-boundary.test.ts`                               | 对应行为回归或事件契约更新                                                 |
| `contextbase-control-plane/tests/lib/public-upstream-payload.test.ts`                            | 对应行为回归或事件契约更新                                                 |
| `hindsight-extensions/contextdb-service/tests/ui/contextdb-native-entrypoints.test.tsx`          | 对应行为回归或事件契约更新                                                 |
| `hindsight-extensions/contextdb-service/tests/ui/contextdb.test.ts`                              | 对应行为回归或事件契约更新                                                 |

## 开发资源路径补充修复（2026-10-29）

基线：主干 `471f80d3f07198f8dc28e2ac27bf2e921b40b956`（已合并 PR #62）。
此前检查了生产产物，未覆盖 `next dev --turbopack` 的可读 chunk 名称。
开发服务器已复现用户报告的 `hindsight-control-plane_src_0hllu7k._.js` 和
`hindsight-control-plane_src_app_globals_1m5duf9.css`；前缀来自物理源码目录。

本次将前端目录迁移到 `contextbase-control-plane/`，同步修改 npm workspace/锁文件、
CI、两套 Docker 打包路径、ContextBase 服务 UI 启动和构建指纹校验、embed 本地 UI
查找、品牌生成器/清单以及相关测试夹具。未修改业务 API、认证或客户数据。
另清理了客户端源码三处历史品牌注释，避免它们出现在未压缩的开发 JS 中。

新增 `test:browser-brand:dev` 并接入独立审计 CI：启动真实开发服务器，读取中英文
登录 HTML，检查并实际请求其中的 JS/CSS 资源，拒绝历史品牌文件名和明文内容。
该检查使用默认 9999 端口，执行前须停止占用该端口的其他开发实例。
它覆盖这两个入口加载的资源，不代表所有动态路由、开发 Source Map 或错误覆盖层均已审计。
生产公开 Source Map 仍然禁用。

### 本地验证

- 开发 HTTP 审计：2 个页面、18 个资源通过，资源前缀为 `contextbase-control-plane_…`。
- 前端：85 个测试文件、860 项测试通过；ESLint 0 错误、203 项既有警告。
- 生产构建和 standalone 打包成功，最终公开产物扫描 120 个文件通过。
- 生产 HTTP 审计：普通模式 67 项、管理模式 89 项通过，使用本地数据面 stub。
- 构建指纹及 UI 密钥契约测试通过；UI 启动器定向检查确认使用新目录且隔离内部凭证。
- 品牌生成器 `--check` 无漂移，完整品牌往返测试通过。
- 修改的 Python 文件语法检查、Shell 语法检查和新增审计脚本格式检查通过。
- 仓库完整 lint 仍因当前部分检出缺少根 `pyproject.toml` 而无法执行；
  未运行完整 API/数据库系统测试、Docker 镜像构建或线上浏览器验证。

### 保留的兼容标识

`@vectorize-io/hindsight-control-plane` npm 包名、旧 CLI 命令、镜像名称和旧进程识别
标记继续保留。本次改变源码目录，不迁移已发布分发身份；它们不是开发静态资源路径。
服务端旧环境变量、内部 SDK 名称及历史审计记录继续按兼容规则保留。

### 部署迁移

停止旧 UI 进程后，更新外部启动器、挂载或 CI 中手写的源码目录，使用干净构建目录
重新安装/构建。不要将旧 `.next` 或 `standalone` 直接移动到新目录继续使用；本地
首次复用旧 Turbopack 缓存曾失败，移走旧缓存后干净生产构建通过。
重新生成 ContextBase 的 `contextdb-release.json` 构建指纹后再发布匹配的 API/UI 镜像。

```sh
npm ci --workspace=contextbase-control-plane --workspace=hindsight-clients/typescript
npm run build --workspace=contextbase-control-plane
npm run audit:browser --workspace=contextbase-control-plane
npm run test:browser-brand --workspace=contextbase-control-plane
npm run test:browser-brand:dev --workspace=contextbase-control-plane
# 正式 UI 服务保留现有运行时配置，使用生产 standalone 启动：
node contextbase-control-plane/standalone/server.js
```

重启后仍需在实际入口检查反向代理是否连接旧开发进程，并处理旧 HTML/CDN 缓存。
仓库改名不会自动修改仓库之外的进程、代理或缓存。

### 开发工具路径的明确例外

首次专项 CI 的生产构建、860 项前端测试和 156 项 HTTP 检查均通过，开发检查发现
Next 第三方开发工具 JS 的 `__NEXT_DIST_DIR` 字段仍含 CI 的绝对检出目录
`/home/runner/work/hindsight/hindsight/…`。本地检出目录为 ContextBase，因而首次本地
检查没有遇到该值。该字段服务于开发诊断，不能通过改业务目录来控制其所有父目录。

开发审计现在只在 Next devtools 这个框架资源中，豁免本次生成目录的准确路径值；
它不是通用的品牌字符串白名单，不豁免资源 URL 或业务 JS/CSS。运行时并未重写第三方
开发工具代码。因此开发服务器仍会暴露调试路径；若检出父目录含历史品牌，该绝对路径
也会带有历史名称。正式服务必须发布生产 standalone。生产扫描没有这一例外，
其公开资源仍按原规则严格检查。此处不宣称开发模式所有源码、调试信息均完成去品牌。

## 业务资源补充修复

PR #63 复查实际访问工作区页面后，确认登录页审计遗漏了业务页面加载的资源。
图转换函数及参数的旧名称，以及提示词预览组件的两处历史品牌注释，仍会进入开发 JS。
这些业务字符串不属于 Next devtools 的诊断路径例外。

- 图转换函数改为 `convertGraphData`，参数改为 `graphData`；同步数据视图、实体视图
  两个调用方及图展示、时间视图测试，数据结构和转换行为保持不变。
- 清理提示词预览、工作区页面和全局 CSS 中的历史品牌注释。
- 开发审计覆盖 10 个页面：中英文登录、首页及工作区，以及接入、设置、仪表盘和指南。
  收集并实际请求这些页面的全部初始静态资源，继续严格检查业务 JS/CSS 和资源 URL。
  管理用户页的生产 HTTP 检查仍在原来的管理模式测试中执行。
- 同一项扩展后的审计已先在修复前失败，定位数据视图 JS 中的旧名称；修复后通过，
  本地检查共 10 个页面、68 个资源。该回归检查已纳入现有专项 CI。

服务端兼容环境变量、仅服务端使用的 SDK 实例名和已发布包身份继续保留；
未重写第三方开发工具或客户数据。本次仍不代表已验证实际部署入口、全部动态加载行为、
开发 Source Map 或错误覆盖层；生产公开资源扫描继续执行，不适用开发诊断路径例外。

本轮修复验证：前端 85 个文件、860 项测试通过；生产编译、类型检查和 standalone
打包成功，最终公开产物扫描 120 个文件通过；生产 HTTP 普通模式 67 项、管理模式
89 项通过。ESLint 为 0 错误、203 项既有警告，修改文件格式与 diff 检查通过。
全仓 lint 仍受当前部分检出缺少根 `pyproject.toml` 限制，未验证线上或构建 Docker 镜像。
