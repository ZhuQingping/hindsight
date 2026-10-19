# agentstratum 客户端发行合同

> 来源说明：本文件保留同事PR #3的发行合同及当时验证记录。当前整合验证不继承下文历史PASS，见[整合结果](../../../agentstratum-integration/RESULT.md)与[冲突处理](../../../agentstratum-integration/CONFLICT-RESOLUTION.md)。

2026-10-15：按 Issue #2 的 D1–D9 及“只发行客户端”补充确认实施。公开下载采用华为云 OBS + CDN，Coding Agents 接受 `npm install <下载地址.tgz>`；本轮不建设公共 npm registry，也不要求按包名 `npx`。候选构建不等于公开发布或生产验收。

## 发行清单

| 组件 | 对外标识 | 候选产物 | 连接配置 |
| --- | --- | --- | --- |
| Rust CLI | 命令 `agentstratum` | `agentstratum-cli/<版本>/<linux或darwin>-<amd64或arm64>/agentstratum` | API Endpoint；保留 Profile |
| Coding Agents | npm 包/命令 `agentstratum-coding-agents` | `agentstratum-coding-agents/<版本>/agentstratum-coding-agents-<版本>.tgz` | `~/.agentstratum/coding-agent.json`；单默认连接 |
| 标准 Agent Plugin | manifest 名 `agentstratum` | `agentstratum-agent-plugin/<版本>/agentstratum-agent-plugin-<版本>.zip` | 完整 MCP Endpoint + 凭证；单默认连接 |
| Claude Code | manifest 名 `agentstratum-memory` | `agentstratum-claude-code/<版本>/agentstratum-claude-code-<版本>.zip` | `~/.agentstratum/claude-code.json`；单默认连接 |

品牌统一为 `agentstratum`，组件后缀区分产物。当前各组件使用自己的 manifest/Cargo 版本；尚未占用公共 npm scope，也不声称这些版本已经公开发行。

API/worker 包及镜像、本地引擎、Web 控制台安装包、SDK、Helm Chart 不进入本轮客户发行。保留服务端和内部开发源码；托管服务的构建部署另行管理。

## 当前代码行为

- CLI 无默认 localhost；未配置地址时提示 API Endpoint、`configure`、Profile 或环境变量。删除自动下载安装本地 Web 的 `ui` 命令。
- CLI `configure` 更换地址时不沿用旧地址的已存凭证；具名 Profile 保留各自的连接。
- Coding Agents 安装在缺少地址时停止注册，拒绝 `daemon`。Hook、原生工具、本地 MCP 适配器共享顶层连接；`harnesses`、`paths`、`banks` 不能覆盖地址和凭证，记忆行为设置仍可覆盖。
- Claude Code Hook 和本地 MCP 适配器只连接显式 API Endpoint；SessionEnd 只做写回。客户运行路径不再输出旧的弃用/自动迁移提示。手动 Hook 安装幂等，卸载保留其他插件的 Hook。
- 标准 Agent Plugin 直接使用完整 MCP Endpoint。它提供 Skills + MCP，不包含生命周期 Hook；其 README 记录的宿主限制仍需真实宿主复核。
- 安装包不内置租户地址和凭证。API Endpoint 与 MCP Endpoint 分开配置，不从其中一个猜测另一个。

## 构建与安装

`.github/workflows/release.yml` 改为手动构建四类客户端候选，不执行公开上传。旧 `v*` / `integrations/**` 标签不再触发原来的 PyPI、npm、服务端镜像或本地引擎发布。

插件归档通过 `scripts/package-client-plugins.py --output <目录>` 生成；先构建 Coding Agents。Claude Code 归档排除本地引擎管理模块、测试和缓存。npm 包不含 `daemon-start.js`。各插件版本目录生成 `SHA256SUMS`，归档包含许可证。CLI 构建另附许可证及第三方许可证清单。

### OBS/CDN 对象布局与安装

把候选产物目录原样部署到已确认的 OBS 对象前缀，由 CDN 提供 HTTPS 公开读取。`AGENTSTRATUM_DOWNLOAD_BASE_URL` 表示该前缀的下载根地址；域名/前缀仍待提供。版本目录发布后保持不可变，不覆盖同版本字节；本轮不设置可变 `latest` 或自动 registry 更新。

| 路径（相对下载根） | 内容 |
| --- | --- |
| `installers/install-agentstratum.sh` | 独立 CLI 安装脚本 |
| `installers/SHA256SUMS` | 安装脚本校验和 |
| `agentstratum-cli/<版本>/<平台>/agentstratum` | CLI 二进制；平台为 linux-amd64、linux-arm64、darwin-amd64、darwin-arm64 |
| `agentstratum-cli/<版本>/<平台>/SHA256SUMS` | 二进制及同目录许可证文件的校验和 |
| `agentstratum-cli/<版本>/<平台>/LICENSE`、`THIRD_PARTY_LICENSES.txt` | CLI 及第三方许可证 |
| `agentstratum-coding-agents/<版本>/agentstratum-coding-agents-<版本>.tgz` | Coding Agents npm 安装包 |
| `agentstratum-agent-plugin/<版本>/agentstratum-agent-plugin-<版本>.zip` | 标准 Agent Plugin |
| `agentstratum-claude-code/<版本>/agentstratum-claude-code-<版本>.zip` | Claude Code 插件 |

三种插件的版本目录各自包含 `SHA256SUMS`。客户下载不依赖内部 CodeArts 项目权限；OBS/CDN 实际访问策略由发布配置提供，客户端安装流程不携带云账号写权限或客户服务凭证。

CLI 安装（先将下载根和精确版本设为已发布的实际值）：

```bash
curl --proto '=https' --proto-redir '=https' --fail --location \
  "$AGENTSTRATUM_DOWNLOAD_BASE_URL/installers/install-agentstratum.sh" \
  --output install-agentstratum.sh
bash install-agentstratum.sh \
  --base-url "$AGENTSTRATUM_DOWNLOAD_BASE_URL" \
  --version "$AGENTSTRATUM_VERSION"
```

脚本识别 Linux/macOS 和 amd64/arm64，下载并核对二进制 SHA-256 后原子替换。默认安装到 `~/.local/bin/agentstratum`，可用 `--bin-dir` 或 `AGENTSTRATUM_BIN_DIR` 指定目录；不会启动服务、修改 Profile 或写入 API/MCP 凭证。缺少下载根/版本、校验失败、下载失败或不支持的平台会退出。下载安装完成后再配置自己的 API Endpoint/Profile；许可证与二进制同目录提供下载。

Coding Agents 安装（组件版本与 CLI 版本独立）：

```bash
npm install -g "$AGENTSTRATUM_DOWNLOAD_BASE_URL/agentstratum-coding-agents/$AGENTSTRATUM_CODING_AGENTS_VERSION/agentstratum-coding-agents-$AGENTSTRATUM_CODING_AGENTS_VERSION.tgz"
```

再配置单默认 API 连接并运行 `agentstratum-coding-agents install <宿主>`。新版本安装使用新版本的 `.tgz` URL，再执行宿主安装以刷新已暂存的运行时；不设置旧的 `AGENTSTRATUM_CODING_AGENTS_PACKAGE` registry 更新选项。正式分发不依赖 npm 公共包名注册。

标准 Agent Plugin 与 Claude Code 按对应版本路径下载、校验、解压，通过宿主加载。前者填写完整 MCP Endpoint，后者填写 API Endpoint；避免重复安装同一宿主的 Hook。Claude Code 的 Python MCP 依赖仍需包索引访问，OBS/CDN 分发本产品包不等于镜像全部第三方依赖。

本地 HTTPS 分发测试 8 项通过：安装脚本覆盖四个平台的下载路径选择、校验失败保留已有安装、缺失/重复校验项、无效地址/版本和环境变量配置；真实 Coding Agents tarball 经 HTTPS URL 安装成功，并完成 Codex 配置注册和卸载，安装时将 npm registry 设为不可用地址以验证不依赖公共包名解析。CLI 测试使用小型可执行文件，验证安装逻辑，不代表所有平台的 Rust 二进制已验证；插件测试验证配置操作，不代表真实宿主会话已验收。真实华为云首次下载/全新机器验收仍待资源就绪。

## 控制台交接合同（待实现）

由每个客户的服务部署配置提供明确的 API Endpoint 与完整 MCP Endpoint；不要使用控制台代理的内部 API 地址，也不要拼接猜测 `/mcp`。控制台按当前登录客户展示这两个地址、凭证获取/轮换说明，以及 CLI Profile、Coding Agents、Agent Plugin、Claude Code 配置示例。

服务端内部凭证不能返回浏览器；客户凭证应通过既定发放流程提供。此文档定义交接要求，当前提交尚未增加控制台配置接口或页面。页面由专业 Web 团队负责，接口仍在 Issue #2 范围内。

## 验证与剩余门槛

本次本地验证：Rust CLI 116 项单元测试及 3 项进程测试；Coding Agents 1,326 项通过、6 项跳过，ESM/DTS 构建通过；Claude Code 222 项通过。两套插件连接测试使用两个独立 HTTP 端口检查请求目标、Bearer 凭证及 401；这些是隔离协议测试，不代替真实服务/宿主验收。另已从实际归档验证：Claude Code MCP initialize/tools/list/tools/call；Coding Agents tarball 经 npm 安装后执行 Codex 注册、重复注册和卸载；标准 Agent Plugin 清单、地址占位符及许可证。最终配置改动后的 Coding Agents 定向复跑为 298 项通过、2 项跳过。

仓库总 lint 脚本在 `uv sync --frozen` 阶段受当前局部检出缺少根 `pyproject.toml` 阻塞；改动文件的格式和 Python lint 单独检查。GitHub 多平台候选构建尚未执行，不能把 Linux 本地通过当作全平台通过。

未完成：

- OBS/CDN 区域、桶、域名、对象前缀、访问策略和发布身份配置及实际上传。
- 已确认 npm tarball 正式安装方案；实际版本清单、客户下载说明及发布流程接入仍待完成。
- CLI 安装脚本已实现；待接入真实公开渠道，完成全新机器首次安装及多平台二进制验收。
- 控制台接入信息接口与页面交接实现。
- 三类插件真实宿主全新安装、认证、工具调用、Hook、卸载验收及兼容限制复核。
- 数据库环境下原 Issue 的 API/MCP/原 SDK、异步任务/Webhook、监控/tracing 系统回归，以及完整仓库 lint、CI 和独立 review。

上述未完成项继续保留在 Issue #2；未合并、未公开发布。
