# MAS UniSync

MAS UniSync 是一个用于 Monika After Story 的跨设备同步项目。它通过 MAS/Ren'Py submod 把游戏的 `persistent` 数据同步到中心服务，让同一个 Profile Key 可以在多台设备之间共享状态。

> 当前项目只同步 Ren'Py `persistent` 数据，不同步普通 save slots。

## 组成

```text
MAS_UniSync
├── game/Submods/MAS_UniSync/    # MAS submod
├── mas_unisync_server/          # FastAPI 后端服务
├── frontend/                    # React 管理门户
├── scripts/                     # 本地开发和模拟脚本
├── tests/                       # 自动化测试
└── docker-compose.yml           # 一键部署配置
```

## 主要功能

- 通过网页门户登录 Flarum 账号。
- 为账号创建、查看、刷新和删除 Profile Key。
- 在 MAS 设置面板中粘贴服务地址和 Profile Key。
- 启动游戏时拉取云端 `persistent`。
- 游戏保存后自动上传本地 `persistent`。
- 使用 Profile Lock 避免同一个同步档案被多个客户端同时写入。
- 服务端保留每日备份。
- 管理员可以查看用户、档案、备份和审计日志，也可以封禁用户、Profile 或 Key。
- 管理员可以在设置中管理 persistent 对象存储桶，默认使用 Docker 本地存储，也可以添加 WebDAV 存储桶。

## 快速部署

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少设置：

```env
POSTGRES_PASSWORD=change-this-password
SESSION_SECRET=change-this-session-secret
FLARUM_URL=https://forum.monika.love/
```

如果需要管理员权限，配置对应 Flarum 用户组：

```env
ADMIN_FLARUM_GROUP_IDS=16,22
ADMIN_FLARUM_GROUP_NAMES=后台组,管理员组
```

启动：

```powershell
docker compose up -d --build
```

默认访问地址：

- 前端门户：`http://127.0.0.1`
- 后端 API：`http://127.0.0.1:8000`

端口可以在 `.env` 中调整：

```env
FRONTEND_PORT=80
BACKEND_PORT=8000
```

## Submod 安装

发布包会包含 `game` 目录。把发布包里的 `game` 目录合并到 MAS 游戏根目录即可。

安装完成后应能看到：

```text
<MAS 游戏目录>/game/Submods/MAS_UniSync/header.rpy
```

进入 MAS 后，打开 MAS UniSync 设置面板：

1. 填入或粘贴 MAS UniSync API URL。
2. 在网页门户中创建 Profile Key。
3. 把 Profile Key 粘贴到 MAS UniSync 设置面板。
4. 重启游戏，让 submod 执行启动同步。

## 本地开发

后端需要 Python 3.11+。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[test]
Copy-Item .env.example .env
python scripts\run_dev_server.py
```

后端默认运行在：

```text
http://127.0.0.1:8000
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

前端默认运行在：

```text
http://127.0.0.1:5173
```

本地开发时，Vite 会把 `/login`、`/logout`、`/account`、`/admin` 和 `/v1` 代理到后端。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `MAS_UNISYNC_ENV` | 运行环境：`test`、`development`、`production`。 |
| `DATABASE_URL` | 数据库连接串。生产环境必须使用 PostgreSQL。 |
| `POSTGRES_DB` | Docker Compose PostgreSQL 数据库名。 |
| `POSTGRES_USER` | Docker Compose PostgreSQL 用户名。 |
| `POSTGRES_PASSWORD` | Docker Compose PostgreSQL 密码。生产部署必填。 |
| `OBJECT_STORAGE_PATH` | persistent 文件存储目录。 |
| `SESSION_SECRET` | Web 会话密钥。生产部署必须替换。 |
| `FLARUM_URL` | Flarum 论坛地址。 |
| `ADMIN_FLARUM_GROUP_IDS` | 映射为管理员的 Flarum group id。 |
| `ADMIN_FLARUM_GROUP_NAMES` | 映射为管理员的 Flarum group name。 |
| `LOCK_TTL_SECONDS` | Profile Lock 过期时间，单位秒。 |

## 对象存储桶

服务端默认创建一个本地存储桶，路径来自 `OBJECT_STORAGE_PATH`。Docker Compose 默认把它挂载到 `object_data` volume，因此不额外配置时仍然使用本地持久化存储。

管理员可以在后台设置页添加 WebDAV 存储桶并选择活动存储桶。切换活动存储桶只影响新的上传；已有 `persistent` 版本和每日备份会继续从原存储桶读取，不会自动迁移。

WebDAV 密码会使用 `SESSION_SECRET` 派生的密钥加密后保存到后端数据库，后台设置接口不会回显明文密码；编辑 WebDAV 存储桶时密码留空表示保持原密码。生产环境不要更换 `SESSION_SECRET`，否则已有 WebDAV 密码将无法解密，需要重新填写。

如果是在已有生产数据库上升级，需要确保 `persistent_versions` 表包含 nullable `bucket_id` 列，并创建 `storage_buckets` 表。当前服务启动会为缺失的 `bucket_id` 做轻量补列，新表由 SQLAlchemy `create_all` 创建。

## 测试

后端和 submod 测试：

```powershell
pytest
```

前端测试：

```powershell
cd frontend
npm test
```

类型检查：

```powershell
cd frontend
npm run typecheck
```

端到端测试：

```powershell
cd frontend
npm run e2e
```

## 发布

GitHub Actions workflow 位于：

```text
.github/workflows/release.yml
```

触发方式：

- push 到 `main`
- 在 GitHub Actions 中手动运行

手动运行时可以填写版本号。如果不填写，workflow 会从下面的文件读取版本：

```text
game/Submods/MAS_UniSync/header.rpy
```

版本变量：

```python
mas_unisync_version = "0.1.0"
```

发布产物：

```text
MAS_UniSync-<version>.zip
```

## 安全说明

- Profile Key 是 submod 访问同步档案的凭据，请不要公开分享。
- 当前设计允许服务端管理员查看 metadata 并下载 persistent 文件。
- 当前版本不提供端到端加密。
- 冲突处理策略为云端优先。

## 许可证

当前仓库还没有声明许可证。发布前请补充 `LICENSE` 文件。
