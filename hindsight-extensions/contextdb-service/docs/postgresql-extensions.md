# PostgreSQL 插件安装与运行配置

基础依赖为 `vector + pg_trgm + btree_gin`。英文全文可直接选内置 `native`；中英文选择 PGroonga 或经实际插件/中文分词器验收的 pg_search。以下 PGroonga 命令是本机源码 PG 的已用路径，不是华为云 RDS 的既定默认方案。`pg_stat_statements` 是可选监控插件；`btree_gin` 不是全文分词器。一套部署选一个全文后端，云上选型前提见[总体设计](contextdb-release-design.md#fulltext-selection)。

以下为本机源码安装的 PG 18.4 示例。其他主版本/平台须指定对应 pg_config，安装目录以其输出为准。扩展文件安装与目标数据库 CREATE EXTENSION 分两步。不要覆盖正在运行实例使用的旧二进制来做升级。

## 1 确认编译目标

```bash
export PG_ROOT=/Users/zhuqingping/Work/Database/PG/pg_18_4
export PG_BIN="$PG_ROOT/bin"
export PG_CONFIG="$PG_BIN/pg_config"
export PLUGIN_BUILD_ROOT="$HOME/contextdb-plugin-build"
mkdir -p "$PLUGIN_BUILD_ROOT"
"$PG_CONFIG" --version
"$PG_CONFIG" --pkglibdir
"$PG_CONFIG" --sharedir
"$PG_CONFIG" --pgxs
```

需要 server headers 和 PGXS。macOS 使用 Xcode Command Line Tools；缺少时先安装 `xcode-select --install`。Homebrew 插件包通常安装到 Homebrew PG，不能代替安装到上述源码 PG prefix。

## 2 pgvector 与 PG contrib

```bash
git clone --depth 1 --branch v0.8.6 https://github.com/pgvector/pgvector.git "$PLUGIN_BUILD_ROOT/pgvector-0.8.6"
make -C "$PLUGIN_BUILD_ROOT/pgvector-0.8.6" PG_CONFIG="$PG_CONFIG" OPTFLAGS=""
make -C "$PLUGIN_BUILD_ROOT/pgvector-0.8.6" PG_CONFIG="$PG_CONFIG" install

(
  set -e
  for module in pg_trgm btree_gin pg_stat_statements; do
    make -C "$PG_ROOT/build/postgres/contrib/$module"
    make -C "$PG_ROOT/build/postgres/contrib/$module" install
  done
)
```

contrib 路径必须是匹配当前 PG 的已配置构建树。本机顶层普通 make/install 未包含这些 contrib，需要单独构建。版本 0.8.6 对应本机已验证 vector；当前 MaaS embedding 为 1024 维，Hindsight pgvector/HNSW 路径支持它，不请求 dimensions。

## 3 PGroonga

本机 PGroonga 4.1.0 源码目录已存在，构建依赖 Groonga（该 tag 至少 14.1.0）、Meson、Ninja 和 pkg-config。先检查源码 tag 与编译目标。

```bash
brew install groonga meson ninja pkgconf msgpack xxhash
export PKG_CONFIG_PATH="$(brew --prefix groonga)/lib/pkgconfig:$(brew --prefix msgpack)/lib/pkgconfig:$(brew --prefix xxhash)/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
pkg-config --modversion groonga
export PGROONGA_SOURCE=/Users/zhuqingping/Work/Database/PG/pg_contrib/pgroonga
export PGROONGA_BUILD="$PLUGIN_BUILD_ROOT/pgroonga-4.1.0"
git -C "$PGROONGA_SOURCE" describe --tags --exact-match
meson setup "$PGROONGA_BUILD" "$PGROONGA_SOURCE" --buildtype=release \
  -Dpg_config="$PG_CONFIG" -Dinstall_to_postgresql=true -Dtest=false
meson compile -C "$PGROONGA_BUILD"
meson install -C "$PGROONGA_BUILD"
```

首次配置执行 setup，已有配置目录直接 compile/install。Linux 按官方文档安装平台依赖；本机命令不使用 sudo，安装目录属于当前用户。

## 4 在目标 UTF8 数据库启用

下例用于选择 PGroonga 的部署；英文 native 不执行 pgroonga 那一行。pg_stat_statements 可按监控需求选择。`DB_URL` 指向新建的独立数据库，不是某个 workspace schema：

```bash
"$PG_BIN/psql" -X "$DB_URL" -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;' \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;' \
  -c 'CREATE EXTENSION IF NOT EXISTS btree_gin WITH SCHEMA public;' \
  -c 'CREATE EXTENSION IF NOT EXISTS pgroonga;' \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;' \
  -c 'SHOW server_encoding;' \
  -c 'SELECT extname,extversion,extnamespace::regnamespace FROM pg_extension ORDER BY extname;'
```

可迁移扩展放 public，供不同 workspace schema 使用；固定 schema 的扩展按自身 control 定义创建，不强行迁移。连接角色需要相应 schema USAGE/函数 EXECUTE，扩展 SQL 的 search_path 也要正确。

在创建空间、运行索引迁移前安装 trgm/btree_gin，避免降级索引。晚装插件不会自动重跑已经完成的迁移；检查实际索引，另规划修复或在新库验证。

## 5 生产运行配置不是 CREATE EXTENSION

- `pg_stat_statements` 需要在 shared_preload_libraries 中加载，并启用 compute_query_id=auto/on；改变 preload 要重启 PG。
- PGroonga WAL resource manager 适用于 PG15+。主备都 preload 模块，主库开启 pgroonga.enable_wal_resource_manager；该方案的备库不启用 crash-safer，不同时额外设置 enable_wal。
- resource manager 本身不提供主库的自动崩溃恢复。官方 crash-safer 仍标为实验功能，使用它要独立评估、配 worker 预算并验证故障恢复；不能把启用它当作已达到生产标准。

先合并既有 preload，不覆盖其他模块；在维护窗口由数据库操作者配置并重启。随后检查实际统计查询、PGroonga 参数、真实检索索引和业务中英文样本，完成崩溃、逻辑/物理备份恢复和复制/切换验收。

本机体验库在 2026-10-15 检查时编码为 SQL_ASCII，preload 为空；插件已安装不代表这些生产项完成。生产与完整中文验收使用独立 UTF8 新库。

官方依据：[pgvector](https://github.com/pgvector/pgvector#installation)、[PG contrib](https://www.postgresql.org/docs/18/contrib.html)、[PGroonga 源码安装](https://pgroonga.github.io/install/source.html)、[4.1.0 构建定义](https://github.com/pgroonga/pgroonga/blob/4.1.0/meson.build)、[SQL 统计](https://www.postgresql.org/docs/18/pgstatstatements.html)、[WAL resource manager](https://pgroonga.github.io/reference/modules/pgroonga-wal-resource-manager.html)、[crash-safer 状态](https://pgroonga.github.io/reference/modules/pgroonga-crash-safer.html)。
