# ContextBase 浏览器品牌检查

本文说明浏览器公开资源和 HTTP 响应的检查入口。
执行结果应记录源码提交、构建配置、命令及报告；历史结果不作为当前版本通过的依据。

## 检查范围

| 检查 | 覆盖范围 |
| --- | --- |
| 生产资源扫描 | `.next/static`、`public`、`.next/server/app` 中的 HTML/RSC，以及 standalone 中的对应复制件 |
| 生产 HTTP | 自建 standalone 服务，检查登录、业务页面、初始静态资源、认证及代理响应；串行运行普通模式和管理模式 |
| 开发资源 | 启动 Turbopack 开发服务，检查中英文登录、首页、工作空间及接入、设置、仪表盘、指南页面的初始 JS/CSS |

生产扫描拒绝历史品牌文本和资源名、公开 Source Map、源码引用、
登记的旧位图哈希，以及指定的合成私有配置标记。
图片哈希检查不具备通用 OCR 能力，新图片仍需人工检查。

## 运行入口

使用独立 checkout，避免安装和构建覆盖正在运行的服务。
以下命令按 CI 的 Bash、Node 24 环境执行；完整步骤见
[Browser brand audit 工作流](../../.github/workflows/browser-brand-audit.yml)。

```bash
(
  set -eu
  unset PORT
  npm ci --workspace=contextbase-control-plane \
    --workspace=hindsight-clients/typescript
  TZ=UTC npm test --workspace=contextbase-control-plane -- --maxWorkers=2
  CONTEXTBASE_CP_DATAPLANE_API_URL=https://synthetic-private-api.invalid \
  CONTEXTBASE_CP_DATAPLANE_API_KEY=synthetic-private-api-key \
  CONTEXTBASE_CP_ACCESS_KEY=synthetic-private-password \
  BROWSER_AUDIT_PRIVATE_MARKERS=synthetic-private-api.invalid,synthetic-private-api-key,synthetic-private-password \
    npm run build --workspace=contextbase-control-plane
  npm run test:browser-brand --workspace=contextbase-control-plane
  PORT=19999 npm run test:browser-brand:dev --workspace=contextbase-control-plane
)
```

生产 `build` 会先构建 TypeScript SDK，再完成 Next 构建、
standalone 打包和公开资源扫描。清除 `PORT` 可保持默认 `.next` 输出路径。
已有生产构建需要独立重扫时，执行：

```bash
npm run audit:browser --workspace=contextbase-control-plane
```

开发示例使用的 `19999` 必须是空闲端口；可通过 `PORT` 改为其他端口。
开发脚本自己启动并清理服务，不应指向另一个正在运行的开发实例。
非默认端口使用 `.next-<PORT>`；开发检查后，发布前重新生成生产产物。

`BROWSER_AUDIT_PRIVATE_MARKERS` 接受逗号分隔的合成配置值。
只使用合成标记验证服务端配置没有进入公开资源，不传入真实凭据。

## 合理保留的内容

- `HINDSIGHT_CP_*` 等服务端兼容配置，以及仅服务端使用的内部变量，
  按现有配置合同保留，并检查其配置值没有进入浏览器。
- `contextdb` 路径、协议键、类名和数据属性沿用管理扩展合同。
- 客户正文、文件、资源名称、成功结果及 4xx 校验中的原始内容保持原值；
  不通过全局替换客户数据来消除命中。
- 第三方代码、许可证和历史归因保持准确；公开资源命中仍须定位来源，
  不因此增加宽泛的旧品牌白名单。
- 非公开的 SDK 或服务端调试文件可保留；部署入口不得额外公开这些目录。

公开身份约定见[品牌定义与生成](../../brand/README.md)。

## 开发与生产边界

开发检查只在 Next devtools 资源中豁免本次生成目录的准确诊断路径值；
业务 JS/CSS、资源 URL 和生产资源没有这项例外。
开发服务仍包含调试信息，正式入口使用匹配版本的生产产物。

HTTP 检查使用受控的数据面替身，不运行 Chromium。
它验证请求、响应及初始资源，不能代替真实浏览器交互、
动态加载、视觉检查、模型质量或实际网关/CDN 的部署验证。
生产公开 Source Map 由 Next 配置关闭，并由扫描和 HTTP 检查复核。

## 失败定位

| 输出或现象 | 检查方向 |
| --- | --- |
| `missing audit root` | 先完成匹配版本的构建和打包，检查输出目录及端口配置 |
| `legacy resource name` / `legacy brand text` | 定位源文件、文案或依赖，再干净构建；不要直接替换产物或客户数据 |
| `retired brand image` | 检查产品图标及其复制件，并人工核对新增图片 |
| `public source map` / `public source reference` | 检查构建配置、静态目录和部署公开边界 |
| `private config marker` | 检查服务端配置是否被导入客户端或序列化到公开响应 |
| HTTP 状态、认证或管理断言失败 | 检查匹配 API/UI 合同；使用服务端日志和请求 ID 排障 |

实际部署后，还需核对代理连接的进程和产物版本、外部静态目录、
HTML/CDN/浏览器缓存，以及新增的脚本和运行时公开配置。
