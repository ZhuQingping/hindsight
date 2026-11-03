# ContextDB 宿主进程部署（非 Docker）

面向 Linux/macOS 的服务运营者及贡献者，复用已有 Bash/Python 脚本直接启动 Python API（含内置 Worker）和 Node UI。首先阅读[部署总览与共用配置](deployment.md)，本页给出同一源码版本的完整前台执行路径。Windows 本地启动使用[PowerShell 专用流程](deployment-windows.md)；本页的生产宿主部署命令不适用于 Windows。

本页不会要求固定 `/srv`、`/var/lib` 或 UID 10001。源码目录、私密输入、实例运行目录均可由部署账号选择；下面的用户目录只是示例。首次部署使用独立 PG、目录与端口。已有实例只需启停时，直接看[停止与恢复](#native-stop)，不要重复准备新实例。

> 本页命令是待在目标环境执行的部署步骤。静态语法、CLI 和虚构输入渲染检查不代表 Linux/macOS 完整构建及真实服务已验收；本次整理不启停现有服务，不连接真实数据库或 MaaS。

## 1. 工具、PG 与源码

| 前提 | 要求 |
| --- | --- |
| Python | 3.11～3.14，下面 uv 示例选择 3.11 |
| uv | 可按仓库 uv.lock 安装 Python 依赖 |
| Node/npm | 建议 Node 24；也接受至少22.12的22.x。当前构建预检不接受23.x；使用对应 Node 自带的 npm |
| Shell/系统工具 | Bash、Git、curl、awk、install；使用系统包管理器准备所需编译工具和依赖，不要求统一使用 apt 或 Homebrew |
| PostgreSQL | 外部专用 UTF8 库、服务账号及三个扩展，按[共用 PG 准备](deployment.md#pg-preparation)完成；准备机需要支持 \getenv 的 psql |
| 网络 | 宿主可达 PG、MaaS、Python/Node依赖来源。PG 在本机时可用实际本地地址，远程 PG 用其真实地址 |

取得选定版本源码，进入包含 `hindsight-extensions/`、`contextbase-control-plane/` 和 `pyproject.toml` 的仓库根目录。以下命令都沿用同一 Bash 会话；不要在运行中的其他部署目录安装依赖或构建 UI。

```bash
export CONTEXTDB_SOURCE_ROOT="$PWD"
export CONTEXTDB_INSTANCE_ROOT="$HOME/contextdb/example-instance"
export CONTEXTDB_DEPLOY_DIR="$CONTEXTDB_INSTANCE_ROOT/runtime"
export CONTEXTDB_INTENT_FILE="$CONTEXTDB_INSTANCE_ROOT/intent.json"
export CONTEXTDB_PYTHON="$CONTEXTDB_SOURCE_ROOT/.venv/bin/python"
export PYTHON_DOTENV_DISABLED=1
umask 077
mkdir -p "$CONTEXTDB_INSTANCE_ROOT/input" "$CONTEXTDB_DEPLOY_DIR"
chmod 700 "$CONTEXTDB_INSTANCE_ROOT" "$CONTEXTDB_INSTANCE_ROOT/input" "$CONTEXTDB_DEPLOY_DIR"
```

按需把实例目录替换为部署账号拥有的绝对路径，保持它在源码目录之外。中断 Shell 后重新设置这些变量；不要把首次初始化流程用于已有实例。持久秘密缺失时恢复一致备份。

<a id="native-build"></a>

## 2. 安装同版依赖

在上面的源码根目录执行，uv 使用本源码的 `.venv`，Node 使用当前部署会话 PATH 中选定的受支持版本：

```bash
uv sync --frozen --package hindsight-api-slim --no-dev --python 3.11
npm ci --ignore-scripts --include=dev --include=optional --no-audit --no-fund
export PYTHONPATH="$CONTEXTDB_SOURCE_ROOT/hindsight-extensions/contextdb-service:$CONTEXTDB_SOURCE_ROOT/hindsight-api-slim"
```

插件通过本地源码路径导入，不要求从 PyPI 安装独立插件包。自定义 `CONTEXTDB_PYTHON` 时应使用同版依赖环境，并在后续脚本中保持一致。UI 构建在第5节执行。

## 3. 准备私密输入和 intent

先按[共用输入要求](deployment.md#运营者准备三个输入文件)准备三个现有私密源文件；将以下源路径改为真实的绝对路径。文件内容不直接写进命令：

```bash
export CONTEXTDB_DATABASE_URL_SOURCE=/absolute/private/database-url
export CONTEXTDB_MAAS_KEY_SOURCE=/absolute/private/maas-key
export CONTEXTDB_UI_PASSWORD_SOURCE=/absolute/private/ui-password
install -m 0600 "$CONTEXTDB_DATABASE_URL_SOURCE" "$CONTEXTDB_INSTANCE_ROOT/input/database-url"
install -m 0600 "$CONTEXTDB_MAAS_KEY_SOURCE" "$CONTEXTDB_INSTANCE_ROOT/input/maas-key"
install -m 0600 "$CONTEXTDB_UI_PASSWORD_SOURCE" "$CONTEXTDB_INSTANCE_ROOT/input/ui-password"
```

本示例只用于新实例，已有输入文件不要覆盖。宿主部署时数据库 URL 和下列所有路径都按宿主环境填写，不使用容器专用 `/var/lib/contextdb`。

以下标准库片段从已有模板准备一个新的意图文件，自动把目录转为实际绝对路径；不会启动服务或初始化 PG。`open("x")` 防止覆盖已有意图文件。

```bash
"$CONTEXTDB_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

source = Path(os.environ["CONTEXTDB_SOURCE_ROOT"])
instance = Path(os.environ["CONTEXTDB_INSTANCE_ROOT"]).resolve()
runtime = Path(os.environ["CONTEXTDB_DEPLOY_DIR"]).resolve()
intent = Path(os.environ["CONTEXTDB_INTENT_FILE"])
config = json.loads(
    (source / "hindsight-extensions/contextdb-service/deployment/intent.example.json").read_text()
)
config.update(
    instance_id="example-instance",
    cloud_tenant_id="example-tenant",
    worker_id="example-instance-worker-1",
    database_url_file=str(instance / "input/database-url"),
    maas_api_key_file=str(instance / "input/maas-key"),
    ui_password_file=str(instance / "input/ui-password"),
    ui_session_dir=str(runtime / "ui-sessions"),
    api_port=8888,
    ui_port=9999,
    ui_api_url="http://127.0.0.1:8888",
    ui_public_origin="http://127.0.0.1:9999",
)
with intent.open("x") as output:
    json.dump(config, output, indent=2)
    output.write("\n")
intent.chmod(0o600)
PY
```

该片段只准备 JSON 输入，随后仍由已有 node-agent.sh 校验并渲染配置，不引入第二套配置生成器。

随后编辑 `CONTEXTDB_INTENT_FILE` 指向的 JSON，核对实例/归属/Worker标识、端口和浏览器真实 UI origin；远程主机不要照抄 localhost。完整字段及固定华为/merged预设见[共用 intent 说明](deployment.md#4-配置意图校验与渲染)。JSON 不展开环境变量。示例端口占用时同时修改 api/ui端口及对应origin，保持一致。

## 4. 校验和生成配置

```bash
bash "$CONTEXTDB_SOURCE_ROOT/hindsight-extensions/contextdb-service/scripts/node-agent.sh" \
  validate --config "$CONTEXTDB_INTENT_FILE"
bash "$CONTEXTDB_SOURCE_ROOT/hindsight-extensions/contextdb-service/scripts/node-agent.sh" \
  render --config "$CONTEXTDB_INTENT_FILE" --directory "$CONTEXTDB_DEPLOY_DIR"
```

两步都预期 `ok:true`；失败时停止，先修复输入。输出的 api.env/ui.env及会话目录归本部署账号，不使用 sudo/chown 到容器 UID。渲染不访问PG或执行模型调用，PG管理结构在init时准备。

插件四项由render自动写入api.env，见[完整值与加载规则](deployment.md#plugin-configuration)。可按[配置核查](deployment.md#52-如何检查生成与挂载结果)只输出四个类路径。私有CA按实际绝对路径配置，并保证运行账号可读。按需编辑运行目录的ui.env补入真实对外API/MCP/客户端地址；此步骤及秘密/别名优先级见[共用配置](deployment.md#53-其他配置来源与公开连接设置)。

## 5. 预检并构建 UI

预检会连接目标 PG、核对扩展/导入路径，并检查 UI 构建工具；它不是实际模型验收：

```bash
bash "$CONTEXTDB_SOURCE_ROOT/hindsight-extensions/contextdb-service/scripts/service.sh" preflight --ui-build
"$CONTEXTDB_PYTHON" -m hindsight_ext_contextdb build-ui --source-root "$CONTEXTDB_SOURCE_ROOT"
```

先确认预检成功再执行构建。UI命令构建匹配SDK和standalone，并写入`contextdb-release.json`指纹；启动时会验证源码与产物匹配。只运行普通Next构建或从别处复制UI目录不能替代这一步。构建失败不要进入启动；原进程未停时也不要覆盖其源码或产物。

<a id="native-start"></a>

## 6. 离线初始化与前台启动

```bash
bash "$CONTEXTDB_SOURCE_ROOT/hindsight-extensions/contextdb-service/scripts/service.sh" init
bash "$CONTEXTDB_SOURCE_ROOT/hindsight-extensions/contextdb-service/scripts/service.sh" all
```

先确认 init 退出成功，再启动 all。init职责见[共用初始化](deployment.md#6-离线初始化再启动)，已有结构或秘密不匹配时拒绝，不靠反复初始化恢复。

`all` 是前台监督命令，会占用当前终端：先启动API（内置Worker）并等API就绪后启动UI；任一应用主进程退出则停止另一进程。它复用现有脚本加载api.env/ui.env及持久秘密，设置PYTHONPATH，并使用专用`hindsight_ext_contextdb.asgi:create_app`。不要在此 merged 路径另加独立 Worker。

## 7. 在另一个终端验证

新终端使用同一部署账号，先回到原来的源码根目录，再重新设置第1节的源码、实例、运行目录、意图和Python变量；`CONTEXTDB_SOURCE_ROOT="$PWD"` 依赖当前目录，不能在默认用户目录直接重设。默认示例使用下面命令；改过端口或API地址时同步改验证地址。

```bash
curl --fail --show-error http://127.0.0.1:8888/health/ready
bash "$CONTEXTDB_SOURCE_ROOT/hindsight-extensions/contextdb-service/scripts/node-agent.sh" \
  status --config "$CONTEXTDB_INTENT_FILE" --directory "$CONTEXTDB_DEPLOY_DIR" \
  --api-url http://127.0.0.1:8888
```

预期API healthy/database connected，status为`ready:true`和`secrets_present:true`。status同时核对管理员和实例归属，但不检查模型/Worker执行。浏览器访问intent里的ui_public_origin登录；使用与配置不符的Host可能得到421，不关闭Host校验绕过。

再按[管理员操作](../README.md#admin-quickstart)创建空间、用户、读写业务Key，按[业务接入](../README.md#business-quickstart)写入事实并召回；完整验收边界见[共用验证说明](deployment.md#7-验证与交付)。健康检查不是这一步的替代。

<a id="native-stop"></a>

## 8. 停止、恢复与更新

先按[共用维护边界](deployment.md#8-停止重启与版本更新)阻止新业务并等待已有工作结束。前台运行时，在所属all终端按Ctrl+C；监督器将停止本实例API/UI进程组。不要使用`pkill python`等按名称全局停止的方法。

普通恢复重新执行同一 `service.sh all`，沿用配置、产物和秘密，不重跑render/init。更新环境配置时，停止受影响组件后编辑/显式render --replace，并补回人工项，再启动；使用all时整体重启本实例。更改源码时重新准备同版依赖、构建UI并核对迁移要求，保留一致备份。UI改密按持久秘密规则执行，不能只临时export。

## 9. 后台托管与平台差异

前台路径先完成验证，再交给现有监督器托管同一个命令；下表是接入约定，不是已经验证的服务配置模板。

| 平台/方式 | 接入要求 |
| --- | --- |
| Linux systemd | 部署用户、实际源码工作目录、Python/Node绝对PATH和实例变量；ExecStart指向`bash /绝对源码路径/.../service.sh all`；停止发送SIGTERM并等待子进程清理 |
| macOS launchd | 同样配置ProgramArguments、WorkingDirectory和EnvironmentVariables；使用所选Node/uv环境，不依赖交互Shell自动加载；进程组停止与会话目录需独立验收 |
| 已有节点Agent/进程管理平台 | 管理同一前台命令、实例环境、日志和退出重启；不要再叠加另一层隐式后台启动 |

两平台共用源码、配置和启动链路；依赖安装由各自包管理方式完成，运行目录由部署账号选择。完整systemd/launchd模板在独立验证前不标为可直接用于生产，也不通过本次文档任务修改系统服务配置。
